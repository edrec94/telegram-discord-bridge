import os
from types import SimpleNamespace

import pytest

from config import Config
from discord_sender import DiscordSendError
from media import RecentMessageIds
from tg_to_discord import build_content, process_messages


class FakeMessage:
    def __init__(self, id, text="", grouped_id=None, has_media=False, size=1024, download_ok=True):
        self.id = id
        self.message = text
        self.grouped_id = grouped_id
        self.media = object() if has_media else None
        self.file = SimpleNamespace(size=size) if has_media else None
        self._download_ok = download_ok

    async def download_media(self, file=None):
        if not self._download_ok:
            raise RuntimeError("download failed")
        path = os.path.join(file, f"{self.id}.jpg")
        with open(path, "wb") as f:
            f.write(b"fake-bytes")
        return path


class FakeSender:
    def __init__(self, fail_with_files=False):
        self.text_calls = []
        self.file_calls = []
        self._fail_with_files = fail_with_files

    async def send_text(self, content):
        self.text_calls.append(content)

    async def send_with_files(self, content, files):
        if self._fail_with_files:
            raise DiscordSendError("simulated failure")
        self.file_calls.append((content, list(files)))


def make_config(**overrides):
    defaults = dict(
        telegram_api_id=1,
        telegram_api_hash="hash",
        telegram_channel="chan",
        discord_webhook_url="https://example.invalid/webhook",
    )
    defaults.update(overrides)
    return Config(**defaults)


def test_build_content_with_caption():
    content = build_content("Header", "https://t.me/x/1", "caption text")
    assert content.startswith("Header\nhttps://t.me/x/1")
    assert "caption text" in content


def test_build_content_without_caption():
    content = build_content("Header", "https://t.me/x/1", "")
    assert content == "Header\nhttps://t.me/x/1"


@pytest.mark.asyncio
async def test_text_only_message_sent_once():
    sender = FakeSender()
    config = make_config()
    recent = RecentMessageIds()
    msg = FakeMessage(1, text="hello world")

    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    assert len(sender.text_calls) == 1
    assert "hello world" in sender.text_calls[0]
    assert len(sender.file_calls) == 0


@pytest.mark.asyncio
async def test_album_sent_as_single_message_with_one_caption():
    sender = FakeSender()
    config = make_config()
    recent = RecentMessageIds()
    messages = [
        FakeMessage(10, text="", grouped_id=999, has_media=True),
        FakeMessage(11, text="album caption", grouped_id=999, has_media=True),
        FakeMessage(12, text="", grouped_id=999, has_media=True),
    ]

    await process_messages(
        messages, config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    assert len(sender.file_calls) == 1
    content, files = sender.file_calls[0]
    assert content.count("album caption") == 1
    assert len(files) == 3
    assert len(sender.text_calls) == 0


@pytest.mark.asyncio
async def test_duplicate_processing_is_skipped():
    sender = FakeSender()
    config = make_config()
    recent = RecentMessageIds()
    msg = FakeMessage(5, text="hi")

    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )
    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    assert len(sender.text_calls) == 1


@pytest.mark.asyncio
async def test_media_send_failure_falls_back_to_text():
    sender = FakeSender(fail_with_files=True)
    config = make_config()
    recent = RecentMessageIds()
    msg = FakeMessage(7, text="caption", has_media=True)

    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    assert len(sender.text_calls) == 1
    assert "media failed to upload" in sender.text_calls[0]


@pytest.mark.asyncio
async def test_media_too_large_skips_download_and_sends_text():
    sender = FakeSender()
    config = make_config(max_media_download_bytes=100)
    recent = RecentMessageIds()
    msg = FakeMessage(8, text="caption", has_media=True, size=10_000)

    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    assert len(sender.text_calls) == 1
    assert len(sender.file_calls) == 0


@pytest.mark.asyncio
async def test_download_failure_falls_back_to_text():
    sender = FakeSender()
    config = make_config()
    recent = RecentMessageIds()
    msg = FakeMessage(9, text="caption", has_media=True, download_ok=False)

    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    assert len(sender.text_calls) == 1
    assert len(sender.file_calls) == 0


@pytest.mark.asyncio
async def test_temp_media_files_are_cleaned_up_after_send():
    sender = FakeSender()
    config = make_config()
    recent = RecentMessageIds()
    msg = FakeMessage(20, text="caption", has_media=True)

    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    _, files = sender.file_calls[0]
    for f in files:
        assert not f.exists()
        assert not f.parent.exists()


@pytest.mark.asyncio
async def test_temp_media_files_are_cleaned_up_even_on_send_failure():
    sender = FakeSender(fail_with_files=True)
    config = make_config()
    recent = RecentMessageIds()
    msg = FakeMessage(21, text="caption", has_media=True)

    captured = {}
    orig_send_with_files = sender.send_with_files

    async def spy(content, files):
        captured["files"] = list(files)
        return await orig_send_with_files(content, files)

    sender.send_with_files = spy

    await process_messages(
        [msg], config=config, sender=sender, channel_username="chan",
        channel_id=100, channel_display="@chan", recent_ids=recent,
    )

    for f in captured["files"]:
        assert not f.exists()
