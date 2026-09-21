# Telegram → Discord Bridge

A Python service that monitors a Telegram channel and forwards messages and media to Discord through a webhook.

I built this project to automate message forwarding between platforms while handling real-world issues such as media delivery, retries, duplicate messages, configuration management and logging.

## Features

- Telegram channel monitoring with Telethon
- Text forwarding to Discord
- Image and media forwarding
- Grouped media / album handling
- Retry and error handling
- Duplicate-message protection
- Media size safeguards
- Structured logging
- Environment-based configuration
- Automated pytest test suite

## Tech Stack

Python, Telethon, aiohttp, python-dotenv, pytest, pytest-asyncio and Discord Webhooks.

## Project Structure

```text
telegram-discord-bridge/
├── config.py
├── discord_sender.py
├── media.py
├── tg_to_discord.py
├── requirements.txt
├── requirements-dev.txt
├── .env.example
├── .gitignore
└── tests/
    ├── test_config.py
    ├── test_discord_sender.py
    ├── test_media.py
    └── test_tg_to_discord.py
