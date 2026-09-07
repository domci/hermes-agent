"""Reader tests for agent.codex_turn_timeout (codex app-server wall clock)."""

from __future__ import annotations

from unittest.mock import patch

from hermes_cli.timeouts import (
    DEFAULT_CODEX_TURN_TIMEOUT,
    get_codex_turn_timeout,
)


def test_default_when_config_missing():
    with patch(
        "hermes_cli.config.load_config_readonly",
        side_effect=RuntimeError("no config"),
    ):
        assert get_codex_turn_timeout() == DEFAULT_CODEX_TURN_TIMEOUT


def test_configured_value_used():
    with patch(
        "hermes_cli.config.load_config_readonly",
        return_value={"agent": {"codex_turn_timeout": 3600}},
    ):
        assert get_codex_turn_timeout() == 3600.0


def test_non_positive_falls_back_to_default():
    for raw in (0, -5, "nonsense", None):
        with patch(
            "hermes_cli.config.load_config_readonly",
            return_value={"agent": {"codex_turn_timeout": raw}},
        ):
            assert get_codex_turn_timeout() == DEFAULT_CODEX_TURN_TIMEOUT


def test_default_constant_is_1800():
    assert DEFAULT_CODEX_TURN_TIMEOUT == 1800.0
