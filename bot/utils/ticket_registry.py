"""In-memory ticket channel registry (panel_id cache for relay routing)."""

from __future__ import annotations

# channel_id -> panel_id (str) or None for legacy tickets
_panel_id_by_channel: dict[int, str | None] = {}


def register_ticket_channel(channel_id: int, panel_id: str | None) -> None:
    _panel_id_by_channel[int(channel_id)] = panel_id


def clear_ticket_channel(channel_id: int) -> None:
    _panel_id_by_channel.pop(int(channel_id), None)


def get_panel_id_for_channel(channel_id: int) -> str | None | object:
    """Return panel_id, None if known legacy ticket, or _MISSING if not cached."""
    if channel_id in _panel_id_by_channel:
        return _panel_id_by_channel[channel_id]
    return _MISSING


class _Missing:
    pass


_MISSING = _Missing()
