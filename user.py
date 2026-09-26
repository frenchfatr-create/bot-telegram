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

# 1. Помощник для админов в группе: узнать точный ID группы
@router.message(Command("id"))
async def cmd_get_id(message: Message, bot: Bot):
    me = await bot.get_me()
    logger.info(f"Команда /id вызвана ботом @{me.username} в чате {message.chat.id} ({message.chat.title})")
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
    me = await bot.get_me()
    channels = config.get_channels_for_bot(bot.id)
    ch_label = str(channels[0]) if channels else "канала"
    text = (
        f"👋 <b>Добро пожаловать в предложку канала {ch_label}!</b>\n\n"
        "Отправьте сюда видео, фото, новость или кругляшок, которое хотите предложить для публикации.\n\n"
        "<i>Бот передаст его администраторам на модерацию!</i>"
    )
    await message.answer(text=text, parse_mode="HTML")

# 3. Прием любого контента в личке и пересылка в группу админов
@router.message(F.chat.type == ChatType.PRIVATE, ~F.text.startswith("/"))
async def handle_any_submission(message: Message, bot: Bot):
    user = message.from_user
    me = await bot.get_me()
    channels = config.get_channels_for_bot(bot.id)
    target_str = ",".join(str(c) for c in channels)
    channel_label = str(channels[0]) if channels else "канал"

    logger.info(f"[@{me.username}] Получена предложка для {channel_label} от user_id={user.id} (@{user.username})")

    # Сохраняем в базу данных
    try:
        sub_id = await database.add_submission(
            user_id=user.id,
            user_message_id=message.message_id,
            bot_id=bot.id,
            target_channels=target_str
        )
    except Exception as db_err:
        logger.error(f"Ошибка сохранения в базу данных: {db_err}", exc_info=True)
        await message.answer("⚠️ Произошла ошибка при сохранении заявки. Попробуйте чуть позже.")
        return

    admin_chat = config.ADMIN_CHAT_ID
    logger.info(f"Отправка сообщения sub_id={sub_id} в админ чат {admin_chat}...")

    # Отправляем в группу админов точную копию сообщения с кнопками
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
        logger.warning(f"Не удалось отправить в {admin_chat}: {e1}")

        # Попытка 2: если ID был без -100, пробуем с префиксом -100
        fallback_chat = None
        if isinstance(admin_chat, int) and admin_chat > 0:
            fallback_chat = int(f"-100{admin_chat}")
        elif str(admin_chat).isdigit():
            fallback_chat = int(f"-100{admin_chat}")

        if fallback_chat:
            try:
                logger.info(f"Пробуем отправить с префиксом -100: {fallback_chat}...")
                admin_msg = await bot.copy_message(
                    chat_id=fallback_chat,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_markup=get_moderation_keyboard(sub_id, channel_label)
                )
                sent_successfully = True
                logger.info(f"Успешно отправлено в fallback чат {fallback_chat}!")
            except Exception as e2:
                logger.error(f"Ошибка отправки и в fallback {fallback_chat}: {e2}")

    if sent_successfully and admin_msg:
        await database.set_admin_message_id(sub_id, admin_msg.message_id)
        await message.answer(
            f"✅ <b>Спасибо! Ваше сообщение отправлено администраторам {channel_label} на проверку.</b>",
            parse_mode="HTML"
        )
        logger.info(f"Заявка #{sub_id} успешно доставлена администраторам.")
    else:
        logger.error(f"Не удалось доставить заявку #{sub_id} ни в один админ-чат.")
        await message.answer(
            "⚠️ <b>Внимание: бот пока не настроен администратором.</b>\n\n"
            "Бот не смог переслать сообщение в группу админов.\n"
            "<i>(Администратору: добавьте бота в группу админов, сделайте администратором и укажите верный ADMIN_CHAT_ID в файле .env)</i>",
            parse_mode="HTML"
        )
