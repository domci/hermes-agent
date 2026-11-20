"""Handoff/cron threads join the allowed users so they show in the Discord sidebar.

A message-less public thread has only the bot as member; Discord lists only joined
threads in the channel tree, so proactive agent threads were hidden from the user.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import plugins.platforms.discord.adapter as discord_platform
from gateway.config import PlatformConfig
from plugins.platforms.discord.adapter import DiscordAdapter


class _Thread:
    def __init__(self, *, fail_for: int | None = None) -> None:
        self.id, self.members, self._fail_for = 555, [], fail_for

    async def add_user(self, user) -> None:
        if user.id == self._fail_for:
            raise RuntimeError("Unknown User")
        self.members.append(user.id)


def _adapter(monkeypatch: pytest.MonkeyPatch, thread: _Thread, *, seed_only: bool = False) -> DiscordAdapter:
    monkeypatch.setattr(discord_platform, "DISCORD_AVAILABLE", True)
    monkeypatch.setattr(discord_platform.discord, "Object", lambda id: SimpleNamespace(id=id), raising=False)
    monkeypatch.setenv("DISCORD_ALLOWED_USERS", "111,222")

    async def create_thread(**_kw):
        return thread

    async def send(_text):
        return SimpleNamespace(create_thread=create_thread)

    parent = SimpleNamespace(id=700, send=send) if seed_only else SimpleNamespace(
        id=700, send=send, create_thread=create_thread)
    adapter = DiscordAdapter(PlatformConfig(enabled=True, token="fake"))
    adapter._client = SimpleNamespace(get_channel=lambda _id: parent)
    return adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("seed_only", [False, True])
async def test_handoff_thread_adds_allowed_users(monkeypatch, seed_only):
    thread = _Thread()
    adapter = _adapter(monkeypatch, thread, seed_only=seed_only)
    assert await adapter.create_handoff_thread("700", "Daily brief") == "555"
    assert sorted(thread.members) == [111, 222]


@pytest.mark.asyncio
async def test_failing_member_add_does_not_break_thread(monkeypatch):
    thread = _Thread(fail_for=111)
    adapter = _adapter(monkeypatch, thread)
    assert await adapter.create_handoff_thread("700", "Daily brief") == "555"
    assert thread.members == [222]
