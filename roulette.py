import random
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

ROULETTE_PRICE_STARS = 20

PRIZES = [
    {"id": "balance_50", "label": "💰 50 ₽ на баланс",     "emoji": "💰", "chance": 60},
    {"id": "proxy_fi",   "label": "🇫🇮 Прокси Финляндия",  "emoji": "🇫🇮", "chance": 15},
    {"id": "proxy_de",   "label": "🇩🇪 Прокси Германия",   "emoji": "🇩🇪", "chance": 15},
    {"id": "proxy_nl",   "label": "🇳🇱 Прокси Нидерланды", "emoji": "🇳🇱", "chance": 10},
]

PRIZE_TO_COUNTRY = {
    "proxy_fi": "finland",
    "proxy_de": "germany",
    "proxy_nl": "netherlands",
}

def roll_prize() -> dict:
    rand = random.uniform(0, 100)
    cumulative = 0
    for prize in PRIZES:
        cumulative += prize["chance"]
        if rand < cumulative:
            return prize
    return PRIZES[0]

def roulette_description_text() -> str:
    return (
        "🎰 <b>Рулетка GetTG</b>\n\n"
        f"<b>Цена:</b> {ROULETTE_PRICE_STARS} ⭐ Telegram Stars\n\n"
        "<b>Возможные призы:</b>\n"
        "💰 50 ₽ на баланс — <b>60%</b>\n"
        "🇫🇮 Прокси Финляндия — <b>15%</b>\n"
        "🇩🇪 Прокси Германия — <b>15%</b>\n"
        "🇳🇱 Прокси Нидерланды — <b>10%</b>\n\n"
        "Нажми кнопку ниже, чтобы крутить 👇"
    )

def roulette_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"🎰 Крутить за {ROULETTE_PRICE_STARS} ⭐",
        callback_data="roulette_pay"
    ))
    return kb

def spin_again_keyboard() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"🎰 Крутить ещё за {ROULETTE_PRICE_STARS} ⭐",
        callback_data="roulette_pay"
    ))
    return kb
