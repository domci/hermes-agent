from __future__ import annotations


#: Default wall-clock budget (seconds) for one `codex app-server` turn.
DEFAULT_CODEX_TURN_TIMEOUT = 1800.0


def _coerce_timeout(raw: object) -> float | None:
    try:
        timeout = float(raw)
    except (TypeError, ValueError):
        return None
    return timeout if timeout > 0 else None


def _configured_timeout(provider_id: str, model: str | None, model_key: str, provider_key: str) -> float | None:
    """Per-model ``providers.<id>.models.<model>.<model_key>`` wins over ``providers.<id>.<provider_key>``."""
    if not provider_id:
        return None
    try:
        from hermes_cli.config import load_config_readonly
        config = load_config_readonly()
    except Exception:
        return None
    providers = config.get("providers", {}) if isinstance(config, dict) else {}
    provider_config = providers.get(provider_id, {}) if isinstance(providers, dict) else {}
    if not isinstance(provider_config, dict):
        return None
    model_config = _get_model_config(provider_config, model)
    if model_config is not None:
        timeout = _coerce_timeout(model_config.get(model_key))
        if timeout is not None:
            return timeout
    return _coerce_timeout(provider_config.get(provider_key))


def get_provider_request_timeout(provider_id: str, model: str | None = None) -> float | None:
    """Return a configured provider request timeout in seconds, if any."""
    return _configured_timeout(provider_id, model, "timeout_seconds", "request_timeout_seconds")


def get_provider_stale_timeout(provider_id: str, model: str | None = None) -> float | None:
    """Return a configured non-stream stale timeout in seconds, if any."""
    return _configured_timeout(provider_id, model, "stale_timeout_seconds", "stale_timeout_seconds")


def get_codex_turn_timeout() -> float:
    """Return the configured `codex app-server` turn wall-clock (seconds).

    Reads ``agent.codex_turn_timeout`` from config.yaml. Missing,
    non-numeric, or non-positive values fall back to
    :data:`DEFAULT_CODEX_TURN_TIMEOUT` — a wedged Codex subprocess must
    always have a finite deadline.
    """
    try:
        from hermes_cli.config import load_config_readonly
        config = load_config_readonly()
    except Exception:
        return DEFAULT_CODEX_TURN_TIMEOUT

    agent = config.get("agent", {}) if isinstance(config, dict) else {}
    if not isinstance(agent, dict):
        return DEFAULT_CODEX_TURN_TIMEOUT
    return _coerce_timeout(agent.get("codex_turn_timeout")) or DEFAULT_CODEX_TURN_TIMEOUT


def _get_model_config(provider_config: dict[str, object], model: str | None) -> dict[str, object] | None:
    if not model:
        return None
    models = provider_config.get("models", {})
    model_config = models.get(model, {}) if isinstance(models, dict) else {}
    return model_config if isinstance(model_config, dict) else None
