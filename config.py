import os
from pathlib import Path
from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=env_path)

# Второй канал логов — ID зашит в коде
LOG_CHAT_ID: int = -1003445217080

DATABASE_PATH: str = os.getenv(
    "DATABASE_PATH",
    str(Path(__file__).parent / "database.sqlite")
)

raw_admin_chat = os.getenv("ADMIN_CHAT_ID", "").strip()
if raw_admin_chat.lstrip("-").isdigit():
    ADMIN_CHAT_ID: int | str = int(raw_admin_chat)
else:
    ADMIN_CHAT_ID = raw_admin_chat


class BotItem:
    def __init__(self, token: str, channels: list[str | int]):
        self.token = token
        self.channels = channels


BOTS_CONFIG: list[BotItem] = []

# Боты BOT_TOKEN_1, BOT_TOKEN_2 и т. д.
for i in range(1, 20):
    t = os.getenv(f"BOT_TOKEN_{i}", "").strip()
    if t:
        raw_ch = os.getenv(
            f"CHANNELS_{i}",
            os.getenv(f"CHANNEL_{i}", "")
        ).strip()

        chs = []
        if raw_ch:
            for item in raw_ch.split(","):
                ch = item.strip()
                if ch:
                    chs.append(int(ch) if ch.lstrip("-").isdigit() else ch)

        BOTS_CONFIG.append(BotItem(token=t, channels=chs))

# Стандартная конфигурация, если нумерованных ботов нет
if not BOTS_CONFIG:
    main_token = os.getenv("BOT_TOKEN", "").strip()
    if main_token:
        raw_channels = os.getenv(
            "CHANNELS",
            os.getenv("CHANNEL_ID", "@KrumYalta")
        ).strip()

        chs = []
        if raw_channels:
            for item in raw_channels.split(","):
                ch = item.strip()
                if ch:
                    chs.append(int(ch) if ch.lstrip("-").isdigit() else ch)

        BOTS_CONFIG.append(BotItem(token=main_token, channels=chs))

# Каналы публикации для каждого бота
BOT_ID_TO_CHANNELS: dict[int, list[str | int]] = {}


def register_bot_id(bot_id: int, channels: list[str | int]):
    BOT_ID_TO_CHANNELS[bot_id] = channels


def get_channels_for_bot(bot_id: int) -> list[str | int]:
    return BOT_ID_TO_CHANNELS.get(bot_id, [])
