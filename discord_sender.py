"""Async Discord webhook client with timeout, rate-limit, and retry handling.

Deliberately takes an injected aiohttp.ClientSession so the whole class is
testable without any real network access.
"""

from __future__ import annotations

import asyncio
import json
import logging
import mimetypes
from pathlib import Path
from typing import Optional, Sequence

import aiohttp

logger = logging.getLogger(__name__)

DISCORD_CONTENT_LIMIT = 2000
MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 1.0
REQUEST_TIMEOUT = aiohttp.ClientTimeout(total=30)
DEFAULT_RATE_LIMIT_WAIT = 5.0


class DiscordSendError(Exception):
    """Raised when a Discord webhook send permanently fails."""


def _truncate(content: str) -> str:
    if len(content) <= DISCORD_CONTENT_LIMIT:
        return content
    suffix = "\n...(truncated)"
    return content[: DISCORD_CONTENT_LIMIT - len(suffix)] + suffix


def _parse_retry_after(body: str) -> float:
    try:
        data = json.loads(body)
        return float(data.get("retry_after", DEFAULT_RATE_LIMIT_WAIT))
    except (ValueError, TypeError, AttributeError, KeyError):
        return DEFAULT_RATE_LIMIT_WAIT


class DiscordSender:
    def __init__(self, webhook_url: str, session: aiohttp.ClientSession):
        self._webhook_url = webhook_url
        self._session = session

    async def send_text(self, content: str) -> None:
        await self._send(content, files=None)

    async def send_with_files(self, content: str, files: Sequence[Path]) -> None:
        await self._send(content, files=files)

    async def _send(self, content: str, files: Optional[Sequence[Path]]) -> None:
        content = _truncate(content)
        last_error: Optional[BaseException] = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                status, body = await self._post_once(content, files)
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                last_error = exc
                logger.warning(
                    "Discord connection error (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc
                )
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue

            if status in (200, 204):
                logger.info("Discord webhook POST succeeded (status=%d)", status)
                return

            if status == 429:
                retry_after = _parse_retry_after(body)
                logger.warning("Discord rate limit hit (429), retrying in %.1fs", retry_after)
                await asyncio.sleep(retry_after)
                continue

            if 500 <= status < 600:
                last_error = DiscordSendError(f"{status} {body}")
                logger.warning(
                    "Discord server error %d (attempt %d/%d): %s",
                    status, attempt, MAX_ATTEMPTS, body,
                )
                await asyncio.sleep(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                continue

            # Other 4xx errors (bad payload, file too large/type rejected, etc.)
            # are not retryable.
            raise DiscordSendError(f"Discord rejected request: {status} {body}")

        raise DiscordSendError(f"Discord send failed after {MAX_ATTEMPTS} attempts: {last_error}")

    async def _post_once(self, content: str, files: Optional[Sequence[Path]]):
        if files:
            form = aiohttp.FormData()
            form.add_field(
                "payload_json",
                json.dumps({"content": content}),
                content_type="application/json",
            )
            opened_files = []
            try:
                for idx, path in enumerate(files):
                    handle = open(path, "rb")
                    opened_files.append(handle)
                    mime_type = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
                    form.add_field(
                        f"files[{idx}]", handle, filename=path.name, content_type=mime_type
                    )
                async with self._session.post(
                    self._webhook_url, data=form, timeout=REQUEST_TIMEOUT
                ) as resp:
                    body = await resp.text()
                    return resp.status, body
            finally:
                for handle in opened_files:
                    handle.close()
        else:
            async with self._session.post(
                self._webhook_url, json={"content": content}, timeout=REQUEST_TIMEOUT
            ) as resp:
                body = await resp.text()
                return resp.status, body
