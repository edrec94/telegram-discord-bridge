"""Mirrors posts from a single Telegram channel into a Discord channel via
a Discord webhook, in near real-time using Telethon event handlers.

Run:  python tg_to_discord.py
Stop: Ctrl+C (or SIGTERM)
"""

from __future__ import annotations

import asyncio
import logging
import signal
import tempfile
from logging.handlers import RotatingFileHandler
from pathlib import Path

import aiohttp
from telethon import TelegramClient, events

from config import Config, load_config
from discord_sender import DiscordSendError, DiscordSender
from media import RecentMessageIds, build_source_link, is_downloadable_size, pick_caption

logger = logging.getLogger("tg_to_discord")


def setup_logging(log_file: str) -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S"
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    root.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def build_content(header: str, link: str, caption: str) -> str:
    content = f"{header}\n{link}"
    if caption:
        content += f"\n\n{caption}"
    return content


async def process_messages(
    messages: list,
    *,
    config: Config,
    sender: DiscordSender,
    channel_username: str | None,
    channel_id: int,
    channel_display: str,
    recent_ids: RecentMessageIds,
) -> None:
    first = messages[0]
    is_album = first.grouped_id is not None

    logger.info(
        "Detected message id=%s (album=%s, items=%d)", first.id, is_album, len(messages)
    )

    if recent_ids.seen_or_add(first.id):
        logger.info("Skipping already-processed message id=%s", first.id)
        return

    caption = pick_caption(messages)
    link = build_source_link(channel_username, channel_id, first.id)
    content = build_content(f"New post from {channel_display}", link, caption)

    media_messages = [m for m in messages if m.media]

    if not media_messages:
        await sender.send_text(content)
        logger.info("Sent text-only message for id=%s", first.id)
        return

    with tempfile.TemporaryDirectory(prefix="tg_media_") as tmpdir:
        downloaded: list[Path] = []
        for m in media_messages:
            if not is_downloadable_size(m, config.max_media_download_bytes):
                continue
            try:
                path = await m.download_media(file=f"{tmpdir}/")
                if path:
                    downloaded.append(Path(path))
                    logger.info("Downloaded media for message id=%s -> %s", m.id, Path(path).name)
            except Exception:
                logger.exception("Failed to download media for message id=%s", m.id)

        if not downloaded:
            logger.warning(
                "No media could be downloaded for id=%s; sending text/caption only", first.id
            )
            await sender.send_text(content)
            logger.info("Sent text-only fallback for id=%s", first.id)
            return

        try:
            await sender.send_with_files(content, downloaded)
            logger.info(
                "Sent message with %d media file(s) for id=%s", len(downloaded), first.id
            )
        except DiscordSendError as exc:
            logger.error(
                "Media upload failed for id=%s (%s); falling back to text/caption only",
                first.id, exc,
            )
            await sender.send_text(content + "\n\n_(media failed to upload - see log)_")
            logger.info("Sent text-only fallback after media failure for id=%s", first.id)
    # TemporaryDirectory cleans up its contents here unconditionally,
    # including when an exception propagated out of the block above.


async def main() -> None:
    config = load_config()
    setup_logging(config.log_file)
    logger.info("Starting tg_to_discord bot")

    client = TelegramClient(config.session_name, config.telegram_api_id, config.telegram_api_hash)

    async with aiohttp.ClientSession() as http_session:
        sender = DiscordSender(config.discord_webhook_url, http_session)

        await client.start()
        logger.info("Telegram client connected and authorized")

        entity = await client.get_entity(config.telegram_channel)
        channel_username = getattr(entity, "username", None)
        channel_title = getattr(entity, "title", None) or channel_username or str(entity.id)
        channel_display = f"@{channel_username}" if channel_username else channel_title
        logger.info("Watching channel: %s (id=%s)", channel_title, entity.id)

        recent_ids = RecentMessageIds()

        @client.on(events.NewMessage(chats=entity))
        async def _on_new_message(event: events.NewMessage.Event) -> None:
            if event.message.grouped_id is not None:
                # Part of an album - the Album handler below processes the
                # whole group as one unit, so skip it here to avoid
                # duplicate/partial Discord messages.
                return
            try:
                await process_messages(
                    [event.message],
                    config=config,
                    sender=sender,
                    channel_username=channel_username,
                    channel_id=entity.id,
                    channel_display=channel_display,
                    recent_ids=recent_ids,
                )
            except Exception:
                logger.exception("Unhandled error processing message id=%s", event.message.id)

        @client.on(events.Album(chats=entity))
        async def _on_album(event: events.Album.Event) -> None:
            try:
                await process_messages(
                    event.messages,
                    config=config,
                    sender=sender,
                    channel_username=channel_username,
                    channel_id=entity.id,
                    channel_display=channel_display,
                    recent_ids=recent_ids,
                )
            except Exception:
                logger.exception("Unhandled error processing album (first id=%s)", event.messages[0].id)

        loop = asyncio.get_running_loop()

        def _request_shutdown() -> None:
            logger.info("Shutdown signal received, disconnecting...")
            asyncio.ensure_future(client.disconnect())

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _request_shutdown)
            except NotImplementedError:
                # Signal handlers aren't available on some platforms (e.g. Windows);
                # asyncio.run's default KeyboardInterrupt handling still applies.
                pass

        logger.info("Bot is running. Press Ctrl+C to stop.")
        await client.run_until_disconnected()

    logger.info("Bot stopped cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
