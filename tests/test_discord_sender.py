import asyncio
import json

import aiohttp
import pytest

from discord_sender import DiscordSendError, DiscordSender, MAX_ATTEMPTS, _truncate


class FakeResponse:
    def __init__(self, status, body=""):
        self.status = status
        self._body = body

    async def text(self):
        return self._body


class FakeCtx:
    def __init__(self, outcome):
        self._outcome = outcome

    async def __aenter__(self):
        if isinstance(self._outcome, BaseException):
            raise self._outcome
        return self._outcome

    async def __aexit__(self, *exc):
        return False


class FakeSession:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeCtx(self._outcomes.pop(0))


@pytest.fixture(autouse=True)
def fast_sleep(monkeypatch):
    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)


def test_truncate_short_content_unchanged():
    assert _truncate("hello") == "hello"


def test_truncate_long_content_is_shortened():
    long_content = "x" * 3000
    result = _truncate(long_content)
    assert len(result) <= 2000
    assert result.endswith("(truncated)")


@pytest.mark.asyncio
async def test_send_text_success():
    session = FakeSession([FakeResponse(204)])
    sender = DiscordSender("https://example.invalid/webhook", session)

    await sender.send_text("hello")

    assert len(session.calls) == 1
    assert session.calls[0]["json"] == {"content": "hello"}


@pytest.mark.asyncio
async def test_retries_on_5xx_then_succeeds():
    session = FakeSession([FakeResponse(500, "server error"), FakeResponse(204)])
    sender = DiscordSender("https://example.invalid/webhook", session)

    await sender.send_text("hello")

    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_retries_on_429_then_succeeds():
    session = FakeSession(
        [FakeResponse(429, json.dumps({"retry_after": 0.01})), FakeResponse(200)]
    )
    sender = DiscordSender("https://example.invalid/webhook", session)

    await sender.send_text("hello")

    assert len(session.calls) == 2


@pytest.mark.asyncio
async def test_non_retryable_4xx_raises_immediately():
    session = FakeSession([FakeResponse(400, "bad request")])
    sender = DiscordSender("https://example.invalid/webhook", session)

    with pytest.raises(DiscordSendError):
        await sender.send_text("hello")

    assert len(session.calls) == 1


@pytest.mark.asyncio
async def test_connection_errors_are_retried_and_eventually_raise():
    outcomes = [aiohttp.ClientConnectionError("boom")] * MAX_ATTEMPTS
    session = FakeSession(outcomes)
    sender = DiscordSender("https://example.invalid/webhook", session)

    with pytest.raises(DiscordSendError):
        await sender.send_text("hello")

    assert len(session.calls) == MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_send_with_files_success(tmp_path):
    file_path = tmp_path / "photo.jpg"
    file_path.write_bytes(b"fake-image-bytes")

    session = FakeSession([FakeResponse(200)])
    sender = DiscordSender("https://example.invalid/webhook", session)

    await sender.send_with_files("caption", [file_path])

    assert len(session.calls) == 1
    assert "data" in session.calls[0]


@pytest.mark.asyncio
async def test_send_with_files_closes_handles_even_on_error(tmp_path):
    file_path = tmp_path / "photo.jpg"
    file_path.write_bytes(b"fake-image-bytes")

    session = FakeSession([aiohttp.ClientConnectionError("boom")] * MAX_ATTEMPTS)
    sender = DiscordSender("https://example.invalid/webhook", session)

    with pytest.raises(DiscordSendError):
        await sender.send_with_files("caption", [file_path])

    # File must not be locked/left open - renaming (Windows-safe check) should work.
    file_path.rename(tmp_path / "renamed.jpg")
