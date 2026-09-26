import asyncio
import logging
import sys
import socket

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from aiogram import Bot, Dispatcher, BaseMiddleware
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.types import TelegramObject, Message, CallbackQuery

import config
import database
from handlers import user, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class DebugLoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: TelegramObject, data: dict):
        bot: Bot = data.get("bot")
        me = await bot.get_me() if bot else None
        tag = f"@{me.username}" if me else f"bot_id={getattr(bot, 'id', 'unknown')}"
        if isinstance(event, Message):
            u = event.from_user
            u_info = f"{u.id} (@{u.username})" if u else "None"
            logger.info(
                f"[{tag}] СООБЩЕНИЕ: chat_id={event.chat.id} ({event.chat.type}) "
                f"from={u_info} text={event.text!r} caption={event.caption!r} content_type={event.content_type}"
            )
        elif isinstance(event, CallbackQuery):
            u = event.from_user
            u_info = f"{u.id} (@{u.username})" if u else "None"
            logger.info(f"[{tag}] КНОПКА: data={event.data!r} from={u_info}")
        return await handler(event, data)

def detect_local_proxy() -> str | None:
    """Автоматическое обнаружение локального прокси (если включен Happ/v2rayN)."""
    for port in (10809, 10808):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return f"http://127.0.0.1:{port}"
        except Exception:
            pass
    return None

async def main():
    if not config.BOTS_CONFIG:
        print("\n" + "=" * 60, flush=True)
        print("  [ERROR] No bot tokens found in .env!", flush=True)
        print("  Please configure BOT_TOKEN_1, BOT_TOKEN_2... in .env", flush=True)
        print("=" * 60 + "\n", flush=True)
        return

    logger.info("Инициализация базы данных SQLite...")
    await database.init_db()
    logger.info("База данных успешно инициализирована.")

    proxy_url = detect_local_proxy()
    if proxy_url:
        logger.info(f"Обнаружен локальный прокси: {proxy_url}. Подключаемся через него.")

    dp = Dispatcher()
    dp.update.outer_middleware(DebugLoggingMiddleware())
    dp.include_router(admin.router)
    dp.include_router(user.router)

    bots: list[Bot] = []

    print("\n" + "=" * 64, flush=True)
    print("  🚀 ЗАПУСК БОТОВ-ПРЕДЛОЖЕК...", flush=True)
    print("=" * 64, flush=True)

    for item in config.BOTS_CONFIG:
        session = AiohttpSession(proxy=proxy_url) if proxy_url else None
        b = Bot(
            token=item.token,
            session=session,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        try:
            me = await b.get_me()
            config.register_bot_id(me.id, item.channels)
            bots.append(b)
            print(f"  [V] Бот @{me.username} подключен! (Каналы: {item.channels})", flush=True)
        except Exception as e:
            logger.error(f"Не удалось подключить бота с токеном {item.token[:12]}...: {e}")

    if not bots:
        logger.error("Ни одного бота не удалось запустить!")
        return

    print(" ", flush=True)
    print(f"  [>] Чат администраторов: {config.ADMIN_CHAT_ID}", flush=True)
    print(f"  [>] Всего активных ботов: {len(bots)}", flush=True)
    print("  [!] НЕ ЗАКРЫВАЙТЕ ЭТО ОКНО (просто сверните его вниз)", flush=True)
    print("=" * 64 + "\n", flush=True)

    try:
        for b in bots:
            await b.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(*bots, allowed_updates=["message", "callback_query"])
    finally:
        for b in bots:
            await b.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
