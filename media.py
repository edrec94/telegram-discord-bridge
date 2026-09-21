"""Helpers for building Telegram source links, captions, and lightweight
in-memory duplicate protection. No network calls live here.
"""

from __future__ import annotations

import collections
import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def build_source_link(channel_username: Optional[str], channel_id: int, message_id: int) -> str:
    """Build a clickable https://t.me/... link to the original post."""
    if channel_username:
        return f"https://t.me/{channel_username}/{message_id}"
    # Private channel with no public username: use the internal link format.
    internal_id = str(channel_id)
    if internal_id.startswith("-100"):
        internal_id = internal_id[4:]
    return f"https://t.me/c/{internal_id}/{message_id}"


def pick_caption(messages: Iterable) -> str:
    """Return the first non-empty caption/text found among a group of messages.

    Telegram albums usually carry the caption on only one item in the group.
    """
    for msg in messages:
        if msg.message:
            return msg.message
    return ""


def is_downloadable_size(message, max_bytes: int) -> bool:
    """False (and logs a warning) if the message's media is too large to
    bother downloading at all - saves bandwidth/disk on files that are
    almost certainly bigger than Discord will accept anyway.
    """
    size = getattr(getattr(message, "file", None), "size", None)
    if size is not None and size > max_bytes:
        logger.warning(
            "Skipping download for message id=%s: media size %.1fMB exceeds limit %.1fMB",
            message.id,
            size / 1024 / 1024,
            max_bytes / 1024 / 1024,
        )
        return False
    return True


class RecentMessageIds:
    """Bounded set of recently-processed message IDs, used as a cheap
    extra guard against duplicate Discord sends if Telethon were ever to
    redeliver an event within a single run (e.g. transient hiccups).

    This is a defense-in-depth measure, not the primary anti-duplicate
    mechanism - the primary one is simply not enabling Telethon's
    catch_up/history-replay behavior, so a reconnect resumes the live
    update stream instead of re-walking history.
    """

    def __init__(self, maxlen: int = 1000):
        self._order: collections.deque = collections.deque(maxlen=maxlen)
        self._ids: set = set()

    def seen_or_add(self, message_id: int) -> bool:
        if message_id in self._ids:
            return True
        if len(self._order) == self._order.maxlen:
            oldest = self._order.popleft()
            self._ids.discard(oldest)
        self._order.append(message_id)
        self._ids.add(message_id)
        return False
