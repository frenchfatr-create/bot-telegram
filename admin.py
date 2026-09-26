import logging
from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery
from aiogram.exceptions import TelegramBadRequest

import config
import database
from keyboards import get_decision_keyboard

logger = logging.getLogger(__name__)
router = Router()

@router.callback_query(F.data.startswith("mod_yes:"))
async def handle_approve_yes(callback: CallbackQuery, bot: Bot):
    sub_id = int(callback.data.split(":")[1])
    sub = await database.get_submission(sub_id)

    if not sub:
        await callback.answer("⚠️ Предложка не найдена в базе.", show_alert=True)
        return

    if sub["status"] != "pending":
        status_ru = "одобрен" if sub["status"] == "approved" else "отклонен"
        await callback.answer(f"Этот пост уже был {status_ru} ранее!", show_alert=True)
        return

    mod_user = callback.from_user
    mod_name = f"@{mod_user.username}" if mod_user.username else mod_user.full_name

    # Определяем целевые каналы для этого поста
    if sub.get("target_channels"):
        target_channels = [c.strip() for c in sub["target_channels"].split(",") if c.strip()]
    else:
        target_channels = config.get_channels_for_bot(bot.id)

    channel_label = str(target_channels[0]) if target_channels else "канал"

    # Публикуем сообщение в целевой канал (или каналы)
    published_count = 0
    for ch in target_channels:
        try:
            await bot.copy_message(
                chat_id=ch,
                from_chat_id=sub["user_id"],
                message_id=sub["user_message_id"]
            )
            published_count += 1
        except Exception as e:
            logger.error(f"Не удалось опубликовать в канал {ch}: {e}")

    if published_count == 0:
        await callback.answer(
            f"❌ Ошибка публикации! Убедитесь, что бот добавлен администратором в канал {channel_label} с правом публикации сообщений.",
            show_alert=True
        )
        return

    # Обновляем статус в базе данных
    await database.update_status(sub_id, "approved", mod_name)

    # Меняем кнопки под сообщением в группе на статус "Одобрено"
    try:
        decision_kb = get_decision_keyboard(f"✅ В {channel_label} ({mod_name})")
        await callback.message.edit_reply_markup(reply_markup=decision_kb)
    except TelegramBadRequest as e:
        logger.debug(f"Не удалось обновить клавиатуру: {e}")

    # Уведомляем автора предложки
    try:
        await bot.send_message(
            chat_id=sub["user_id"],
            text=(
                f"🎉 <b>Ваш материал опубликован в канале {channel_label}!</b>\n\n"
                "Спасибо за отличный контент! Присылайте ещё!"
            ),
            parse_mode="HTML"
        )
    except Exception:
        pass

    await callback.answer(f"✅ Успешно опубликовано в {channel_label}!")

@router.callback_query(F.data.startswith("mod_no:"))
async def handle_reject_no(callback: CallbackQuery, bot: Bot):
    sub_id = int(callback.data.split(":")[1])
    sub = await database.get_submission(sub_id)

    if not sub:
        await callback.answer("⚠️ Предложка не найдена в базе.", show_alert=True)
        return

    if sub["status"] != "pending":
        status_ru = "одобрен" if sub["status"] == "approved" else "отклонен"
        await callback.answer(f"Этот пост уже был {status_ru} ранее!", show_alert=True)
        return

    mod_user = callback.from_user
    mod_name = f"@{mod_user.username}" if mod_user.username else mod_user.full_name

    # Обновляем статус в БД
    await database.update_status(sub_id, "rejected", mod_name)

    # Меняем кнопки под сообщением в группе на статус "Отклонено"
    try:
        decision_kb = get_decision_keyboard(f"❌ Отклонено ({mod_name})")
        await callback.message.edit_reply_markup(reply_markup=decision_kb)
    except TelegramBadRequest as e:
        logger.debug(f"Не удалось обновить клавиатуру: {e}")

    # Уведомляем автора
    try:
        await bot.send_message(
            chat_id=sub["user_id"],
            text="Благодарим за предложение, но данный материал не подошел для публикации в канале."
        )
    except Exception:
        pass

    await callback.answer("❌ Материал отклонен.")

@router.callback_query(F.data == "noop")
async def handle_noop(callback: CallbackQuery):
    await callback.answer()
