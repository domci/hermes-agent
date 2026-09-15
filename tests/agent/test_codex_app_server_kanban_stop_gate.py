"""Codex app-server turns skip conversation_loop's stop gates, so a kanban worker that
narrates and stops must still get the bounded kanban_complete/kanban_block nudge."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agent.codex_runtime import run_codex_app_server_turn
from hermes_cli.codex_runtime_plugin_migration import _build_hermes_tools_mcp_entry
from tests.agent.test_codex_app_server_kanban_fallback import _make_agent, _make_turn, _terminal_message


def _run(monkeypatch, turns, board_status=None):
    monkeypatch.setenv("HERMES_KANBAN_TASK", "t_gate")
    monkeypatch.setenv("HERMES_KANBAN_BOARD", "frub-ai-incidents")
    monkeypatch.delenv("HERMES_KANBAN_STOP_NUDGE", raising=False)
    agent = _make_agent(turns[0])
    agent._codex_session.run_turn.side_effect = turns
    task = None if board_status is None else SimpleNamespace(status=board_status)
    messages = [{"role": "user", "content": "work kanban task t_gate"}]
    with patch("hermes_cli.timeouts.get_codex_turn_timeout", return_value=1800.0), \
            patch("hermes_cli.kanban_db.get_task", return_value=task):
        result = run_codex_app_server_turn(
            agent, user_message="work", original_user_message="work", messages=messages, effective_task_id="x",
        )
    return agent, result, messages


def test_narrated_stop_is_nudged_until_terminal_call(monkeypatch):
    done = _make_turn(projected_messages=[_terminal_message("mcp.hermes-tools.kanban_complete")], final_text="done")
    agent, result, messages = _run(monkeypatch, [_make_turn(), done], board_status="running")
    calls = agent._codex_session.run_turn.call_args_list
    assert len(calls) == 2
    nudge = calls[1].kwargs["user_input"]
    assert "kanban_complete" in nudge and "hermes kanban --board frub-ai-incidents complete t_gate" in nudge
    assert any(m.get("_kanban_stop_synthetic") for m in messages)
    assert result["final_response"] == "done"
    assert result["kanban_stop_nudges"] == 1


def test_nudges_are_bounded(monkeypatch):
    agent, result, _ = _run(monkeypatch, [_make_turn(), _make_turn(), _make_turn(), _make_turn()], "running")
    assert agent._codex_session.run_turn.call_count == 3  # first turn + 2 nudges
    assert result["completed"] is True


def test_no_nudge_when_board_already_terminal(monkeypatch):
    """Completion through the shell CLI leaves no tool call but the board row is done."""
    agent, result, _ = _run(monkeypatch, [_make_turn()], board_status="done")
    assert agent._codex_session.run_turn.call_count == 1
    assert "kanban_stop_nudges" not in result


def test_no_nudge_outside_kanban_worker(monkeypatch):
    monkeypatch.delenv("HERMES_KANBAN_TASK", raising=False)
    agent = _make_agent(_make_turn())
    with patch("hermes_cli.timeouts.get_codex_turn_timeout", return_value=1800.0):
        run_codex_app_server_turn(agent, user_message="hi", original_user_message="hi",
                                  messages=[{"role": "user", "content": "hi"}], effective_task_id="x")
    assert agent._codex_session.run_turn.call_count == 1


def test_mcp_entry_forwards_kanban_env():
    """Codex gives MCP servers a minimal env; without HERMES_KANBAN_TASK the kanban tools are hidden."""
    env_vars = _build_hermes_tools_mcp_entry()["env_vars"]
    assert "HERMES_KANBAN_TASK" in env_vars and "HERMES_KANBAN_DB" in env_vars
