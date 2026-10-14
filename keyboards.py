from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def get_moderation_keyboard(sub_id: int, channel_label: str = "") -> InlineKeyboardMarkup:
    yes_text = f"✅ Да (В {channel_label})" if channel_label else "✅ Да (В канал)"
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=yes_text, callback_data=f"mod_yes:{sub_id}"),
        InlineKeyboardButton(text="❌ Нет (Отклонить)", callback_data=f"mod_no:{sub_id}")
    ]])


def get_decision_keyboard(status_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=status_text, callback_data="noop")]])


def get_ban_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📝 Обжаловать блокировку", callback_data="ban_appeal")]])


def get_appeal_moderation_keyboard(appeal_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Разблокировать", callback_data=f"appeal_approve:{appeal_id}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"appeal_reject:{appeal_id}")
    ]])
