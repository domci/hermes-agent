"""Regression: a codex app-server turn that hits the wall-clock deadline
must not exit as a silent clean run for kanban workers.

When the turn deadline fires after a completed assistant message but
before turn/completed, the text is accepted as the terminal response with
no error — the worker CLI then exits rc=0 with no terminal board call and
the dispatcher records crashed/protocol-violation. The runtime must
single-shot ``kanban_complete`` with a runbook-shaped (schemaVersion 1)
``blocked`` verdict instead, so the repair caller closes the dispatch
with a diagnosis rather than re-dispatching it.
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from agent.codex_runtime import _kanban_deadline_fallback, run_codex_app_server_turn


def _make_turn(**overrides):
    fields = dict(
        interrupted=False,
        error=None,
        thread_id="thread-1",
        turn_id="turn-1",
        projected_messages=[{"role": "assistant", "content": "CODEX_ASSISTANT"}],
        tool_iterations=0,
        final_text="CODEX_ASSISTANT",
        should_retire=False,
        deadline_accepted=False,
    )
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _make_agent(turn):
    agent = MagicMock()
    # Pre-seed the session so run_codex_app_server_turn skips the spawn block.
    agent._codex_session = MagicMock()
    agent._codex_session.run_turn.return_value = turn
    agent.tool_progress_callback = None
    agent._iters_since_skill = 0
    agent._skill_nudge_interval = 0
    agent.valid_tool_names = set()
    agent._session_db = None
    agent._session_db_created = True
    agent.session_id = "sess-codex-fallback"
    return agent


def _terminal_message(name="kanban_complete"):
    return {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call-1",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
        ],
    }


def _run(turn, messages, monkeypatch):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_fallback")
    monkeypatch.delenv("HERMES_KANBAN_STOP_NUDGE", raising=False)
    agent = _make_agent(turn)
    with patch(
        "hermes_cli.timeouts.get_codex_turn_timeout", return_value=1800.0
    ), patch(
        "tools.kanban_tools._handle_complete",
        return_value=json.dumps({"ok": True, "task_id": "t_fallback"}),
    ) as complete:
        result = run_codex_app_server_turn(
            agent,
            user_message="hello",
            original_user_message="hello",
            messages=messages,
            effective_task_id="task-1",
        )
    return result, complete


def test_deadline_accept_without_terminal_call_completes_blocked(monkeypatch):
    """The fallback fires once with a runbook-shaped blocked verdict."""
    result, complete = _run(
        _make_turn(deadline_accepted=True),
        [{"role": "user", "content": "hello"}],
        monkeypatch,
    )
    assert complete.call_count == 1
    args = complete.call_args[0][0]
    assert args["summary"]
    metadata = args["metadata"]
    assert metadata["schemaVersion"] == 1
    assert metadata["classification"] == "blocked"
    assert metadata["commitSha"] is None
    assert metadata["blockedReason"]
    assert metadata["tests"]
    assert result["kanban_deadline_fallback"] == "blocked"
    # The worker still exits with the accepted text as usual.
    assert result["completed"] is True
    assert result["final_response"] == "CODEX_ASSISTANT"


def test_fallback_skipped_when_terminal_call_made(monkeypatch):
    """A real kanban_complete in the turn must not be double-completed."""
    result, complete = _run(
        _make_turn(deadline_accepted=True),
        [
            {"role": "user", "content": "hello"},
            _terminal_message("kanban_complete"),
        ],
        monkeypatch,
    )
    assert complete.call_count == 0
    assert result["kanban_deadline_fallback"] == (
        "skipped: terminal call already made"
    )


def test_fallback_skipped_for_mcp_namespaced_terminal_call(monkeypatch):
    """Codex invokes Hermes tools through the hermes-tools MCP server, so
    the projected name is namespaced — still a real terminal call."""
    result, complete = _run(
        _make_turn(deadline_accepted=True),
        [
            {"role": "user", "content": "hello"},
            _terminal_message("mcp.hermes-tools.kanban_block"),
        ],
        monkeypatch,
    )
    assert complete.call_count == 0


def test_fallback_skipped_without_deadline_accept(monkeypatch):
    """Clean turn/completed must never trigger the fallback."""
    result, complete = _run(
        _make_turn(deadline_accepted=False),
        [{"role": "user", "content": "hello"}],
        monkeypatch,
    )
    assert complete.call_count == 0
    assert "kanban_deadline_fallback" not in result


def test_fallback_skipped_when_not_a_kanban_worker(monkeypatch):
    """No HERMES_KANBAN_TASK (interactive/CLI use) → no board write."""
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    monkeypatch.delenv("HERMES_KANBAN_STOP_NUDGE", raising=False)
    agent = _make_agent(_make_turn(deadline_accepted=True))
    with patch(
        "hermes_cli.timeouts.get_codex_turn_timeout", return_value=1800.0
    ), patch(
        "tools.kanban_tools._handle_complete",
        return_value=json.dumps({"ok": True}),
    ) as complete:
        result = run_codex_app_server_turn(
            agent,
            user_message="hello",
            original_user_message="hello",
            messages=[{"role": "user", "content": "hello"}],
            effective_task_id="task-1",
        )
    assert complete.call_count == 0
    assert result["kanban_deadline_fallback"] == "skipped: not a kanban worker"


def test_fallback_rejection_never_raises(monkeypatch):
    """A rejected complete (e.g. already terminal) is a status, not a crash."""
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_fallback")
    monkeypatch.delenv("HERMES_KANBAN_STOP_NUDGE", raising=False)
    agent = _make_agent(_make_turn(deadline_accepted=True))
    with patch(
        "hermes_cli.timeouts.get_codex_turn_timeout", return_value=1800.0
    ), patch(
        "tools.kanban_tools._handle_complete",
        return_value=json.dumps({"error": "could not complete (already terminal)"}),
    ):
        result = run_codex_app_server_turn(
            agent,
            user_message="hello",
            original_user_message="hello",
            messages=[{"role": "user", "content": "hello"}],
            effective_task_id="task-1",
        )
    assert result["kanban_deadline_fallback"] == "failed: rejected"
    assert result["completed"] is True


def test_configured_timeout_reaches_run_turn(monkeypatch):
    """agent.codex_turn_timeout must arrive at run_turn as turn_timeout."""
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_fallback")
    monkeypatch.delenv("HERMES_KANBAN_STOP_NUDGE", raising=False)
    agent = _make_agent(_make_turn(deadline_accepted=False))
    with patch(
        "hermes_cli.timeouts.get_codex_turn_timeout", return_value=1800.0
    ), patch("tools.kanban_tools._handle_complete") as complete:
        run_codex_app_server_turn(
            agent,
            user_message="hello",
            original_user_message="hello",
            messages=[{"role": "user", "content": "hello"}],
            effective_task_id="task-1",
        )
    _, kwargs = agent._codex_session.run_turn.call_args
    assert kwargs["turn_timeout"] == 1800.0
    assert complete.call_count == 0


def test_fallback_helper_never_raises_without_kanban_stack():
    """Unit-level: missing kanban modules degrade to a status string."""
    with patch.dict("sys.modules", {"agent.kanban_stop": None}):
        assert _kanban_deadline_fallback([], turn_timeout=1800.0).startswith(
            "skipped:"
        )
