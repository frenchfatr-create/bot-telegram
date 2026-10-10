
import logging
from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType

import config
import database
from keyboards import get_moderation_keyboard

logger = logging.getLogger(__name__)
router = Router()

# ID второго канала логов зашит в config.py
LOG_CHAT_ID = -1003445217080


async def log_media_sender(message: Message, bot: Bot):
    """Отправляет сведения об отправителе фото или видео во второй канал логов."""
    user = message.from_user
    if not user:
        return

    if message.photo:
        media_type = "Фото"
    elif message.video:
        media_type = "Видео"
    elif message.animation:
        media_type = "GIF / анимация"
    else:
        return

    username = f"@{user.username}" if user.username else "не указан"

    text = (
        "📥 <b>Получен медиаматериал</b>\n\n"
        f"Тип: <b>{media_type}</b>\n"
        f"Username: {username}\n"
        f"Telegram ID: <code>{user.id}</code>"
    )

    try:
        await bot.send_message(
            chat_id=LOG_CHAT_ID,
            text=text,
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Не удалось отправить лог во второй канал %s", LOG_CHAT_ID)


# 1. Помощник для админов в группе: узнать точный ID группы
@router.message(Command("id"))
async def cmd_get_id(message: Message, bot: Bot):
    me = await bot.get_me()
    logger.info(
        "Команда /id вызвана ботом @%s в чате %s (%s)",
        me.username, message.chat.id, message.chat.title
    )
    await message.reply(
        f"ℹ️ <b>Информация о чате:</b>\n"
        f"Название: <b>{message.chat.title or 'Чат'}</b>\n"
        f"Точный ID: <code>{message.chat.id}</code>\n\n"
        f"👉 <b>Скопируйте эту строчку в ваш файл .env:</b>\n"
        f"<code>ADMIN_CHAT_ID={message.chat.id}</code>",
        parse_mode="HTML"
    )


# 2. Старт в личке у бота
@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, bot: Bot):
    channels = config.get_channels_for_bot(bot.id)
    ch_label = str(channels[0]) if channels else "канала"

    text = (
        f"👋 <b>Добро пожаловать в предложку канала {ch_label}!</b>\n\n"
        "Отправьте сюда видео, фото, новость или кругляшок, которое хотите предложить для публикации.\n\n"
        "<i>Бот передаст его администраторам на модерацию!</i>"
    )
    await message.answer(text=text, parse_mode="HTML")


# 3. Прием контента в личке и пересылка в группу админов
@router.message(F.chat.type == ChatType.PRIVATE, ~F.text.startswith("/"))
async def handle_any_submission(message: Message, bot: Bot):
    user = message.from_user
    if not user:
        return

    channels = config.get_channels_for_bot(bot.id)
    target_str = ",".join(str(c) for c in channels)
    channel_label = str(channels[0]) if channels else "канал"

    logger.info(
        "Получена предложка от user_id=%s (@%s)",
        user.id, user.username
    )

    # Логируем отправителя фото/видео во второй канал.
    # Это не влияет на доставку заявки модераторам.
    await log_media_sender(message, bot)

    # Сохраняем заявку в базу данных
    try:
        sub_id = await database.add_submission(
            user_id=user.id,
            user_message_id=message.message_id,
            bot_id=bot.id,
            target_channels=target_str
        )
    except Exception as db_err:
        logger.error(
            "Ошибка сохранения в базу данных: %s",
            db_err,
            exc_info=True
        )
        await message.answer(
            "⚠️ Произошла ошибка при сохранении заявки. Попробуйте чуть позже."
        )
        return

    admin_chat = config.ADMIN_CHAT_ID
    logger.info(
        "Отправка сообщения sub_id=%s в админ чат %s...",
        sub_id, admin_chat
    )

    sent_successfully = False
    admin_msg = None

    try:
        admin_msg = await bot.copy_message(
            chat_id=admin_chat,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=get_moderation_keyboard(sub_id, channel_label)
        )
        sent_successfully = True

    except Exception as e1:
        logger.warning("Не удалось отправить в %s: %s", admin_chat, e1)

        fallback_chat = None
        if isinstance(admin_chat, int) and admin_chat > 0:
            fallback_chat = int(f"-100{admin_chat}")
        elif str(admin_chat).isdigit():
            fallback_chat = int(f"-100{admin_chat}")

        if fallback_chat:
            try:
                logger.info(
                    "Пробуем отправить с префиксом -100: %s...",
                    fallback_chat
                )
                admin_msg = await bot.copy_message(
                    chat_id=fallback_chat,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_markup=get_moderation_keyboard(sub_id, channel_label)
                )
                sent_successfully = True
                logger.info("Успешно отправлено в fallback чат %s!", fallback_chat)

            except Exception as e2:
                logger.error(
                    "Ошибка отправки и в fallback %s: %s",
                    fallback_chat, e2
                )

    if sent_successfully and admin_msg:
        await database.set_admin_message_id(sub_id, admin_msg.message_id)
        await message.answer(
            f"✅ <b>Спасибо! Ваше сообщение отправлено администраторам "
            f"{channel_label} на проверку.</b>",
            parse_mode="HTML"
        )
        logger.info("Заявка #%s успешно доставлена администраторам.", sub_id)

    else:
        logger.error("Не удалось доставить заявку #%s ни в один админ-чат.", sub_id)
        await message.answer(
            "⚠️ <b>Внимание: бот пока не настроен администратором.</b>\n\n"
            "Бот не смог переслать сообщение в группу админов.\n"
            "<i>(Администратору: добавьте бота в группу админов, "
            "сделайте администратором и укажите верный ADMIN_CHAT_ID "
            "в файле .env)</i>",
            parse_mode="HTML"
        )
