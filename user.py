import logging
import time
from html import escape

from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.filters import CommandStart, Command
from aiogram.enums import ChatType

import config
import database
from keyboards import get_moderation_keyboard, get_ban_keyboard, get_appeal_moderation_keyboard

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("id"))
async def cmd_get_id(message: Message):
    await message.reply(
        f"ℹ️ <b>Информация о чате:</b>\nНазвание: <b>{escape(message.chat.title or 'Личные сообщения')}</b>\n"
        f"Точный ID: <code>{message.chat.id}</code>\n\n<code>ADMIN_CHAT_ID={message.chat.id}</code>",
        parse_mode="HTML")


@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def cmd_start(message: Message, bot: Bot):
    user = message.from_user
    if not user:
        return
    ban = await database.get_ban(user.id)
    if ban:
        await message.answer(
            f"⛔ <b>Вы заблокированы в предложке.</b>\n\nПричина: {escape(ban['reason'])}\n\n"
            "Если считаете блокировку ошибочной, подайте обжалование.",
            reply_markup=get_ban_keyboard(), parse_mode="HTML")
        return
    channels = config.get_channels_for_bot(bot.id)
    label = escape(str(channels[0])) if channels else "канала"
    await message.answer(
        f"👋 <b>Добро пожаловать в предложку {label}!</b>\n\n"
        "Отправьте сюда материал, который хотите предложить для публикации.\n\n"
        "⏱ Антиспам: не чаще одного сообщения в минуту.", parse_mode="HTML")


@router.callback_query(F.data == "ban_appeal", F.message.chat.type == ChatType.PRIVATE)
async def start_ban_appeal(callback: CallbackQuery, bot: Bot):
    ban = await database.get_ban(callback.from_user.id)
    if not ban:
        await callback.answer("Вы уже не заблокированы.", show_alert=True)
        return
    await database.create_appeal_draft(callback.from_user.id, bot.id)
    await callback.message.answer("📝 Напишите одним сообщением, почему блокировку нужно снять. Обращение увидят администраторы.")
    await callback.answer()


@router.message(F.chat.type == ChatType.PRIVATE, ~F.text.startswith("/"))
async def handle_private_message(message: Message, bot: Bot):
    user = message.from_user
    if user is None:
        return

    ban = await database.get_ban(user.id)
    if ban:
        # Allow a pending appeal text even though the user is banned.
        pending = await database.get_awaiting_appeal(user.id)
        if not pending:
            await message.answer(
                f"⛔ <b>Вы заблокированы в предложке.</b>\n\nПричина: {escape(ban['reason'])}\n\n"
                "Чтобы обжаловать блокировку, нажмите кнопку ниже.",
                reply_markup=get_ban_keyboard(), parse_mode="HTML")
            return

    pending_appeal = await database.get_awaiting_appeal(user.id)
    if pending_appeal:
        appeal_text = (message.text or message.caption or "").strip()
        if not appeal_text:
            await message.answer("Пожалуйста, отправьте текст обжалования обычным сообщением.")
            return
        await database.submit_appeal(pending_appeal["id"], appeal_text)
        username = f"@{escape(user.username)}" if user.username else "не указан"
        try:
            appeal_msg = await bot.send_message(
                chat_id=config.ADMIN_CHAT_ID,
                text=(f"📝 <b>Обжалование блокировки #{pending_appeal['id']}</b>\n"
                      f"Пользователь: {escape(user.full_name)}\nUsername: {username}\n"
                      f"Telegram ID: <code>{user.id}</code>\n\n"
                      f"<b>Причина обращения:</b>\n{escape(appeal_text)}"),
                parse_mode="HTML", reply_markup=get_appeal_moderation_keyboard(pending_appeal["id"]))
            await database.set_appeal_admin_message_id(pending_appeal["id"], appeal_msg.message_id)
        except Exception:
            logger.exception("Не удалось доставить обжалование #%s администраторам", pending_appeal["id"])
            await database.reset_appeal_for_retry(pending_appeal["id"])
            await message.answer("⚠️ Не удалось передать обжалование администраторам. Попробуйте отправить его ещё раз позже.")
            return
        await message.answer("✅ Обжалование отправлено администраторам. Ожидайте решения.")
        return

    submission_timestamp = time.time()
    allowed, seconds_left = await database.check_and_mark_submission(user.id, submission_timestamp, 60)
    if not allowed:
        await message.answer(f"⏳ Антиспам: отправлять предложку можно раз в минуту. Подождите ещё {seconds_left} сек.")
        return

    channels = config.get_channels_for_bot(bot.id)
    target_str = ",".join(str(c) for c in channels)
    channel_label = str(channels[0]) if channels else "канал"
    try:
        sub_id = await database.add_submission(user.id, message.message_id, bot.id, target_str)
    except Exception:
        logger.exception("Ошибка сохранения предложки в БД")
        await database.rollback_submission_rate_limit(user.id, submission_timestamp)
        await message.answer("⚠️ Не удалось сохранить предложку. Попробуйте позже.")
        return

    admin_chat = config.ADMIN_CHAT_ID
    actual_admin_chat = admin_chat
    admin_msg = None
    try:
        admin_msg = await bot.copy_message(chat_id=actual_admin_chat, from_chat_id=message.chat.id,
            message_id=message.message_id, reply_markup=get_moderation_keyboard(sub_id, channel_label))
    except Exception as first_error:
        logger.warning("Не удалось отправить в админ-чат %s: %s", admin_chat, first_error)
        fallback_chat = None
        try:
            raw = int(admin_chat)
            if raw > 0:
                fallback_chat = int(f"-100{raw}")
        except (ValueError, TypeError):
            pass
        if fallback_chat is not None:
            try:
                admin_msg = await bot.copy_message(chat_id=fallback_chat, from_chat_id=message.chat.id,
                    message_id=message.message_id, reply_markup=get_moderation_keyboard(sub_id, channel_label))
                actual_admin_chat = fallback_chat
            except Exception:
                logger.exception("Не удалось отправить предложку в резервный чат")

    if not admin_msg:
        # Remove the incomplete submission and release the rate-limit reservation so a retry is possible.
        await database.delete_pending_submission(sub_id)
        await database.rollback_submission_rate_limit(user.id, submission_timestamp)
        await message.answer("⚠️ Не удалось доставить предложку администраторам. Проверьте ADMIN_CHAT_ID и права бота, затем попробуйте снова.")
        return

    await database.set_admin_message_id(sub_id, admin_msg.message_id)
    username = f"@{escape(user.username)}" if user.username else "не указан"
    try:
        await bot.send_message(chat_id=actual_admin_chat,
            text=(f"👤 <b>Автор предложки #{sub_id}</b>\nИмя: {escape(user.full_name)}\n"
                  f"Юзернейм: {username}\nTelegram ID: <code>{user.id}</code>"),
            parse_mode="HTML", reply_to_message_id=admin_msg.message_id)
    except Exception:
        logger.exception("Не удалось отправить данные автора для заявки #%s", sub_id)
    await message.answer(f"✅ Ваша предложка отправлена администраторам {escape(channel_label)} на проверку.")
