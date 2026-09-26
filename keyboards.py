from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_moderation_keyboard(sub_id: int, channel_label: str = "") -> InlineKeyboardMarkup:
    """Кнопки модерации для админ-группы с указанием целевого канала."""
    yes_text = f"✅ Да (В {channel_label})" if channel_label else "✅ Да (В канал)"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=yes_text, callback_data=f"mod_yes:{sub_id}"),
                InlineKeyboardButton(text="❌ Нет (Отклонить)", callback_data=f"mod_no:{sub_id}")
            ]
        ]
    )

def get_decision_keyboard(status_text: str) -> InlineKeyboardMarkup:
    """Кнопка-статус после нажатия Да или Нет."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=status_text, callback_data="noop")
            ]
        ]
    )
