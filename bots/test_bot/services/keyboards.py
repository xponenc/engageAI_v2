from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


async def reply_start_keyboard(items: list, buttons_per_row: int = 2):
    kb = ([[InlineKeyboardButton(text=f"{item.get('name')}",
                                 callback_data=f"{item.get('callback_data')}") for item in line]
           for line in (items[i: i + buttons_per_row]
                        for i in range(0, len(items), buttons_per_row))])
    return InlineKeyboardMarkup(
        inline_keyboard=kb,
    )