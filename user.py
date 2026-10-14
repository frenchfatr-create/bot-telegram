
import logging
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType

import config
import database
from keyboards import get_moderation_keyboard

logger = logging.getLogger(__name__)
router = Router()


# 1. Получение ID группы администраторов
@router.message(Command("id"))
async def cmd_get_id(message: Message, bot: Bot):
    me = await bot.get_me()

    logger.info(
        f"Команда /id вызвана ботом @{me.username} "
        f"в чате {message.chat.id} ({message.chat.title})"
    )

    await message.reply(
        f"ℹ️ <b>Информация о чате:</b>\n"
        f"Название: <b>{escape(message.chat.title or 'Чат')}</b>\n"
        f"Точный ID: <code>{message.chat.id}</code>\n\n"
        f"👉 <b>Скопируйте эту строку в файл .env:</b>\n"
        f"<code>ADMIN_CHAT_ID={message.chat.id}</code>",
        parse_mode="HTML"
    )


# 2. Старт в личных сообщениях
@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, bot: Bot):
    channels = config.get_channels_for_bot(bot.id)
    ch_label = str(channels[0]) if channels else "канала"

    text = (
        f"👋 <b>Добро пожаловать в предложку канала "
        f"{escape(ch_label)}!</b>\n\n"
        "Отправьте сюда видео, фото, новость или кружок, "
        "которое хотите предложить для публикации.\n\n"
        "<i>Бот передаст материал администраторам на модерацию!</i>"
    )

    await message.answer(text=text, parse_mode="HTML")


# 3. Приём предложки от пользователя
@router.message(
    F.chat.type == ChatType.PRIVATE,
    ~F.text.startswith("/")
)
async def handle_any_submission(message: Message, bot: Bot):
    user = message.from_user

    if user is None:
        await message.answer("Не удалось определить отправителя.")
        return

    me = await bot.get_me()
    channels = config.get_channels_for_bot(bot.id)

    target_str = ",".join(str(c) for c in channels)
    channel_label = str(channels[0]) if channels else "канал"

    logger.info(
        f"[@{me.username}] Получена предложка для {channel_label} "
        f"от user_id={user.id}, username=@{user.username}"
    )

    # Сохраняем заявку в базе данных
    try:
        sub_id = await database.add_submission(
            user_id=user.id,
            user_message_id=message.message_id,
            bot_id=bot.id,
            target_channels=target_str
        )
    except Exception as db_err:
        logger.error(
            f"Ошибка сохранения заявки в БД: {db_err}",
            exc_info=True
        )
        await message.answer(
            "⚠️ Произошла ошибка при сохранении заявки. "
            "Попробуйте отправить её немного позже."
        )
        return

    admin_chat = config.ADMIN_CHAT_ID
    actual_admin_chat = admin_chat
    admin_msg = None

    channel_label_safe = escape(channel_label)

    logger.info(
        f"Отправка заявки #{sub_id} в админ-чат {admin_chat}"
    )

    # 4. Отправляем оригинальное сообщение в админ-чат
    try:
        admin_msg = await bot.copy_message(
            chat_id=actual_admin_chat,
            from_chat_id=message.chat.id,
            message_id=message.message_id,
            reply_markup=get_moderation_keyboard(
                sub_id, channel_label
            )
        )

    except Exception as first_error:
        logger.warning(
            f"Не удалось отправить заявку в чат "
            f"{admin_chat}: {first_error}"
        )

        # Резервная попытка, если указан ID без префикса -100
        fallback_chat = None

        try:
            chat_id_int = int(admin_chat)

            if chat_id_int > 0:
                fallback_chat = int(f"-100{chat_id_int}")

        except (ValueError, TypeError):
            logger.error(
                f"Некорректный ADMIN_CHAT_ID: {admin_chat}"
            )

        if fallback_chat is not None:
            try:
                logger.info(
                    f"Повторная отправка заявки #{sub_id} "
                    f"в резервный чат {fallback_chat}"
                )

                admin_msg = await bot.copy_message(
                    chat_id=fallback_chat,
                    from_chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_markup=get_moderation_keyboard(
                        sub_id, channel_label
                    )
                )

                # Важно: используем именно тот чат,
                # в который сообщение действительно отправлено.
                actual_admin_chat = fallback_chat

            except Exception as fallback_error:
                logger.error(
                    f"Не удалось отправить заявку #{sub_id} "
                    f"в резервный чат {fallback_chat}: "
                    f"{fallback_error}",
                    exc_info=True
                )

    # 5. Если сообщение доставлено — отправляем данные автора
    if admin_msg is not None:
        try:
            await database.set_admin_message_id(
                sub_id,
                admin_msg.message_id
            )
        except Exception as db_err:
            logger.error(
                f"Не удалось сохранить ID сообщения "
                f"администратора для заявки #{sub_id}: {db_err}",
                exc_info=True
            )

        username_text = (
            f"@{escape(user.username)}"
            if user.username
            else "не указан"
        )

        full_name = escape(user.full_name)

        author_text = (
            f"👤 <b>Автор предложки #{sub_id}</b>\n"
            f"Имя: {full_name}\n"
            f"Юзернейм: {username_text}\n"
            f"Telegram ID: <code>{user.id}</code>"
        )

        try:
            # Отправляем данные отдельным сообщением
            # в тот же чат и отвечаем на сообщение с предложкой.
            await bot.send_message(
                chat_id=actual_admin_chat,
                text=author_text,
                parse_mode="HTML",
                reply_to_message_id=admin_msg.message_id
            )

            logger.info(
                f"Данные автора заявки #{sub_id} "
                f"отправлены в чат {actual_admin_chat}"
            )

        except Exception as info_err:
            logger.error(
                f"Не удалось отправить данные автора "
                f"заявки #{sub_id}: {info_err}",
                exc_info=True
            )

            # Резервная отправка данных без ответа на сообщение
            try:
                await bot.send_message(
                    chat_id=actual_admin_chat,
                    text=author_text,
                    parse_mode="HTML"
                )

                logger.info(
                    f"Данные автора заявки #{sub_id} "
                    f"отправлены без привязки к сообщению"
                )

            except Exception as retry_error:
                logger.error(
                    f"Повторная отправка данных автора "
                    f"заявки #{sub_id} не удалась: {retry_error}",
                    exc_info=True
                )

        # Подтверждаем получение предложки пользователю
        await message.answer(
            f"✅ <b>Спасибо! Ваша предложка отправлена "
            f"администраторам {channel_label_safe} на проверку.</b>",
            parse_mode="HTML"
        )

        logger.info(
            f"Заявка #{sub_id} успешно доставлена "
            f"в чат {actual_admin_chat}"
        )

    else:
        # 6. Если не удалось отправить предложку
        logger.error(
            f"Не удалось доставить заявку #{sub_id} "
            f"в админ-чат {admin_chat}"
        )

        await message.answer(
            "⚠️ <b>Не удалось отправить предложку администраторам.</b>\n\n"
            "Попробуйте немного позже.\n\n"
            "<i>Администратору: проверьте ADMIN_CHAT_ID "
            "в файле .env, добавление бота в группу "
            "и его права на отправку сообщений.</i>",
            parse_mode="HTML"
        )
