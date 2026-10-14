import logging
from html import escape
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, Message
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest

import config
import database
from keyboards import get_decision_keyboard

logger = logging.getLogger(__name__)
router = Router()


def _in_admin_chat(message_or_callback) -> bool:
    chat = getattr(message_or_callback, "chat", None)
    if chat is None and getattr(message_or_callback, "message", None):
        chat = message_or_callback.message.chat
    return bool(chat and config.ADMIN_CHAT_ID and chat.id == config.ADMIN_CHAT_ID)


@router.message(Command("block"), F.chat.id == config.ADMIN_CHAT_ID)
async def block_command(message: Message, bot: Bot):
    args = (message.text or "").split(maxsplit=2)
    if len(args) < 3 or not args[1].lstrip("-").isdigit():
        await message.reply("Формат: <code>/block TELEGRAM_ID причина</code>\nНапример: <code>/block 123456789 Спам</code>", parse_mode="HTML")
        return
    user_id = int(args[1])
    reason = args[2].strip()
    await database.ban_user(user_id, reason, message.from_user.id if message.from_user else None)
    try:
        await bot.send_message(user_id, f"⛔ <bВы заблокированы в предложке.</b>\nПричина: {escape(reason)}", parse_mode="HTML")
        notice = " Пользователю отправлено уведомление."
    except Exception:
        notice = " Не удалось написать пользователю в личку (возможно, он не запускал бота)."
    await message.reply(f"✅ Пользователь <code>{user_id}</code> заблокирован. Причина: {escape(reason)}.{notice}", parse_mode="HTML")


@router.message(Command("unblock"), F.chat.id == config.ADMIN_CHAT_ID)
async def unblock_command(message: Message):
    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].lstrip("-").isdigit():
        await message.reply("Формат: <code>/unblock TELEGRAM_ID</code>", parse_mode="HTML")
        return
    user_id = int(args[1])
    removed = await database.unban_user(user_id)
    if removed:
        try:
            await message.bot.send_message(user_id, "✅ Ваша блокировка снята. Теперь вы снова можете отправлять предложки.")
        except Exception:
            pass
        await message.reply(f"✅ Пользователь <code>{user_id}</code> разблокирован.", parse_mode="HTML")
    else:
        await message.reply(f"Пользователь <code>{user_id}</code> не найден в списке блокировок.", parse_mode="HTML")


@router.message(F.chat.id == config.ADMIN_CHAT_ID, F.reply_to_message)
async def reply_to_submission_author(message: Message, bot: Bot):
    if not message.from_user or message.from_user.is_bot:
        return
    if (message.text or "").startswith(("/block", "/unblock")):
        return
    submission = await database.get_submission_by_admin_message(bot.id, message.reply_to_message.message_id)
    if not submission:
        # Also support replying to the author-info message, which itself replies to the submission.
        parent_id = message.reply_to_message.reply_to_message.message_id if message.reply_to_message.reply_to_message else None
        if parent_id:
            submission = await database.get_submission_by_admin_message(bot.id, parent_id)
    if not submission:
        return
    try:
        if message.text:
            await bot.send_message(submission["user_id"], f"💬 <b>Ответ администрации на вашу предложку:</b>\n\n{escape(message.text)}", parse_mode="HTML")
        elif message.caption:
            await bot.send_message(submission["user_id"], f"💬 <b>Ответ администрации на вашу предложку:</b>\n\n{escape(message.caption)}", parse_mode="HTML")
        else:
            await message.reply("Пока можно отправить ответ пользователю текстом или подписью к медиа.")
            return
        await message.reply(f"✅ Ответ доставлен пользователю <code>{submission['user_id']}</code>.", parse_mode="HTML")
    except Exception as e:
        logger.exception("Не удалось доставить ответ автору предложки")
        await message.reply(f"⚠️ Не удалось отправить сообщение пользователю: {escape(str(e))}", parse_mode="HTML")


@router.callback_query(F.data.startswith("mod_yes:"))
async def handle_approve_yes(callback: CallbackQuery, bot: Bot):
    if not _in_admin_chat(callback):
        await callback.answer("Эта кнопка работает только в админ-группе.", show_alert=True)
        return
    sub_id = int(callback.data.split(":")[1])
    sub = await database.get_submission(sub_id)
    if not sub:
        await callback.answer("⚠️ Предложка не найдена в базе.", show_alert=True)
        return
    if sub["status"] != "pending":
        await callback.answer("Эта предложка уже обработана.", show_alert=True)
        return
    mod = callback.from_user
    mod_name = f"@{mod.username}" if mod.username else mod.full_name
    target_channels = [c.strip() for c in sub.get("target_channels", "").split(",") if c.strip()] or config.get_channels_for_bot(bot.id)
    published = 0
    for channel in target_channels:
        try:
            await bot.copy_message(chat_id=channel, from_chat_id=sub["user_id"], message_id=sub["user_message_id"])
            published += 1
        except Exception as e:
            logger.error("Не удалось опубликовать в канал %s: %s", channel, e)
    if published == 0:
        await callback.answer("❌ Не удалось опубликовать. Проверьте права бота в канале.", show_alert=True)
        return
    label = str(target_channels[0]) if target_channels else "канал"
    await database.update_status(sub_id, "approved", mod_name)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_decision_keyboard(f"✅ Опубликовано ({mod_name})"))
    except TelegramBadRequest:
        pass
    try:
        await bot.send_message(sub["user_id"], f"🎉 Ваш материал опубликован в канале {escape(label)}!", parse_mode="HTML")
    except Exception:
        pass
    await callback.answer("✅ Опубликовано!")


@router.callback_query(F.data.startswith("mod_no:"))
async def handle_reject_no(callback: CallbackQuery, bot: Bot):
    if not _in_admin_chat(callback):
        await callback.answer("Эта кнопка работает только в админ-группе.", show_alert=True)
        return
    sub_id = int(callback.data.split(":")[1])
    sub = await database.get_submission(sub_id)
    if not sub:
        await callback.answer("⚠️ Предложка не найдена в базе.", show_alert=True)
        return
    if sub["status"] != "pending":
        await callback.answer("Эта предложка уже обработана.", show_alert=True)
        return
    mod = callback.from_user
    mod_name = f"@{mod.username}" if mod.username else mod.full_name
    await database.update_status(sub_id, "rejected", mod_name)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_decision_keyboard(f"❌ Отклонено ({mod_name})"))
    except TelegramBadRequest:
        pass
    try:
        await bot.send_message(sub["user_id"], "Благодарим за предложение, но этот материал не подошёл для публикации.")
    except Exception:
        pass
    await callback.answer("❌ Материал отклонён.")


@router.callback_query(F.data.startswith("appeal_approve:"))
async def approve_appeal(callback: CallbackQuery, bot: Bot):
    if not _in_admin_chat(callback):
        await callback.answer("Эта кнопка работает только в админ-группе.", show_alert=True)
        return
    appeal_id = int(callback.data.split(":")[1])
    appeal = await database.get_appeal(appeal_id)
    if not appeal or appeal["status"] != "pending":
        await callback.answer("Обжалование уже обработано или не найдено.", show_alert=True)
        return
    await database.unban_user(appeal["user_id"])
    await database.resolve_appeal(appeal_id, "approved", callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_decision_keyboard("✅ Обжалование одобрено — пользователь разблокирован"))
    except TelegramBadRequest:
        pass
    try:
        await bot.send_message(appeal["user_id"], "✅ Ваше обжалование одобрено. Блокировка снята, вы снова можете отправлять предложки.")
    except Exception:
        pass
    await callback.answer("Пользователь разблокирован.")


@router.callback_query(F.data.startswith("appeal_reject:"))
async def reject_appeal(callback: CallbackQuery):
    if not _in_admin_chat(callback):
        await callback.answer("Эта кнопка работает только в админ-группе.", show_alert=True)
        return
    appeal_id = int(callback.data.split(":")[1])
    appeal = await database.get_appeal(appeal_id)
    if not appeal or appeal["status"] != "pending":
        await callback.answer("Обжалование уже обработано или не найдено.", show_alert=True)
        return
    await database.resolve_appeal(appeal_id, "rejected", callback.from_user.id)
    try:
        await callback.message.edit_reply_markup(reply_markup=get_decision_keyboard("❌ Обжалование отклонено"))
    except TelegramBadRequest:
        pass
    try:
        await callback.bot.send_message(appeal["user_id"], "❌ Администраторы отклонили ваше обжалование. Блокировка остаётся активной.")
    except Exception:
        pass
    await callback.answer("Обжалование отклонено.")


@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer()
