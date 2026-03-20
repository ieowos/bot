import logging
import math
import sys
import asyncio
import os
from aiogram import Bot, Dispatcher, types
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    LabeledPrice
)
from aiogram.utils import executor
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage

print("🚀 Запуск бота...")
print(f"🐍 Python: {sys.version}")

from env import (
    BOT_TOKEN, PAYMENTS_TOKEN,
    MTProto_FINLAND, MTProto_GERMANY, MTProto_NETHERLANDS,
    PAYMENT_PAGE_URL, CHANNEL_URL, SUPPORT_USERNAME,
    ADMIN_ID, DATABASE_URL,
)

from database import (
    create_user, get_balance, add_balance,
    subtract_balance, set_country, get_country, init_db
)

from roulette import (
    roll_prize, roulette_description_text,
    roulette_keyboard, spin_again_keyboard,
    PRIZE_TO_COUNTRY, ROULETTE_PRICE_STARS,
)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

# ─── Константы ───────────────────────────────────────────────────────────────

PRICES = {
    "finland":     35,
    "germany":     40,
    "netherlands": 25,
}

# Цены в звёздах (фиксированные, не пересчитываются по курсу)
STAR_PRICES = {
    "finland":     20,
    "germany":     25,
    "netherlands": 15,
}

COUNTRY_NAMES = {
    "finland":     "🇫🇮 Финляндия",
    "germany":     "🇩🇪 Германия",
    "netherlands": "🇳🇱 Нидерланды",
}

PROXY_LINKS = {
    "finland":     MTProto_FINLAND,
    "germany":     MTProto_GERMANY,
    "netherlands": MTProto_NETHERLANDS,
}

AGREEMENT_TEXT = """📄 ПОЛЬЗОВАТЕЛЬСКОЕ СОГЛАШЕНИЕ

1. Некоторые наши прокси или прокси конкретных стран могут не работать с какими либо сервисами, сайтами или платежными системами, имейте это ввиду и тестируйте прокси перед более крупной покупкой или уточняйте данные вопросы у тех. поддержки.

2. Мы не несем ответственности если наши прокси не подошли к вашей деятельности. Мы несем ответственность только за указанные технические характеристики товара и валидность прокси.

3. Если наши прокси перестали работать то мы НЕ имеем права отказать вам в замене товара. Прокси возврату не подлежат если они вам не пригодились или не подошли.

4. Мы не несем ответственность за ваши действия во время использования прокси, в том числе за использование прокси для противоправных действий.

5. Мы отказываемся от ответственности за ваши финансовые потери во время использования наших прокси.

6. При передаче прокси третьим лицам вы остаетесь ответственным за их действия.

7. При возникновении вопросов по товару уточняйте всё до покупки.

8. В боте могут присутствовать рекламные рассылки, за их содержимое мы ответственности не несём.

📞 По всем вопросам: @GetTG_support
"""

# ─── FSM ─────────────────────────────────────────────────────────────────────

class DepositState(StatesGroup):
    waiting_amount     = State()  # ввод суммы
    waiting_screenshot = State()  # ожидание скриншота

# ─── Клавиатуры ──────────────────────────────────────────────────────────────

def get_main_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    kb.add(
        KeyboardButton("🛒 Купить прокси"),
        KeyboardButton("💰 Пополнить баланс"),
        KeyboardButton("🎰 Рулетка"),
        KeyboardButton("📞 Поддержка"),
        KeyboardButton("👤 Профиль"),
        KeyboardButton("📄 Пользовательское соглашение"),
    )
    return kb

def cancel_keyboard():
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_deposit"))
    return kb

# ─── /start ──────────────────────────────────────────────────────────────────

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    await create_user(message.from_user.id)
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Добро пожаловать в магазин прокси.\n"
        f"Выберите действие в меню ниже:",
        reply_markup=get_main_keyboard()
    )

# ─── Купить прокси ────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "🛒 Купить прокси")
async def show_proxies(message: types.Message):
    balance = await get_balance(message.from_user.id)
    text = "🛒 <b>Доступные прокси:</b>\n\n"
    for country, price in PRICES.items():
        stars = STAR_PRICES[country]
        text += f"{COUNTRY_NAMES[country]} — {price} руб. / {stars} ⭐\n"
    text += f"\n💰 Ваш баланс: {balance} руб."
    kb = InlineKeyboardMarkup(row_width=1)
    for country in PRICES:
        kb.add(InlineKeyboardButton(
            f"{COUNTRY_NAMES[country]} — {PRICES[country]} руб.",
            callback_data=f"buy_{country}"
        ))
    await message.answer(text, reply_markup=kb)

# ─── Пополнить баланс — шаг 1: сумма ─────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "💰 Пополнить баланс")
async def deposit_step1(message: types.Message):
    await message.answer(
        "💳 Введите сумму пополнения в рублях (минимум 60 руб.):",
        reply_markup=cancel_keyboard()
    )
    await DepositState.waiting_amount.set()

@dp.callback_query_handler(lambda c: c.data == "cancel_deposit", state="*")
async def cancel_deposit(call: types.CallbackQuery, state: FSMContext):
    await state.finish()
    await bot.send_message(call.from_user.id, "❌ Отменено.", reply_markup=get_main_keyboard())
    await call.answer()

@dp.message_handler(state=DepositState.waiting_amount)
async def deposit_step2(message: types.Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("❌ Введите целое число, например: <b>100</b>")
        return

    amount = int(message.text)
    if amount < 60:
        await message.answer("❌ Минимальная сумма пополнения — <b>60 руб.</b>")
        return

    await state.update_data(expected_amount=amount)
    await DepositState.waiting_screenshot.set()

    payment_url = f"{PAYMENT_PAGE_URL}?user_id={message.from_user.id}&amount={amount}"

    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("💳 Перейти к оплате", url=payment_url))
    kb.add(InlineKeyboardButton("❌ Отмена", callback_data="cancel_deposit"))

    await message.answer(
        f"💰 Сумма пополнения: <b>{amount} ₽</b>\n\n"
        f"<b>Инструкция:</b>\n"
        f"1️⃣ Нажмите <b>«Перейти к оплате»</b> и оплатите\n"
        f"2️⃣ Сделайте скриншот чека об оплате\n"
        f"3️⃣ Отправьте скриншот сюда\n\n"
        f"⏳ Жду ваш скриншот...",
        reply_markup=kb
    )

# ─── Пополнить баланс — шаг 2: скриншот ──────────────────────────────────────

@dp.message_handler(state=DepositState.waiting_screenshot, content_types=types.ContentType.PHOTO)
async def deposit_got_screenshot(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    amount = data.get("expected_amount", 0)

    # Зачисляем баланс сразу
    await add_balance(user_id, amount)
    new_balance = await get_balance(user_id)
    await state.finish()

    # Уведомляем пользователя
    await message.answer(
        f"✅ <b>Оплата принята!</b>\n\n"
        f"💰 Зачислено: <b>{amount} ₽</b>\n"
        f"💳 Новый баланс: <b>{new_balance} ₽</b>",
        reply_markup=get_main_keyboard()
    )

    # Пересылаем скриншот админу для контроля
    username = f"@{message.from_user.username}" if message.from_user.username else "нет username"
    await bot.send_message(
        ADMIN_ID,
        f"💰 <b>Пополнение баланса</b>\n\n"
        f"👤 User: <code>{user_id}</code> ({username})\n"
        f"💵 Сумма: <b>{amount} ₽</b>\n"
        f"💳 Новый баланс: <b>{new_balance} ₽</b>\n\n"
        f"📸 Скриншот чека:"
    )
    await bot.forward_message(ADMIN_ID, user_id, message.message_id)

    # Кнопки для быстрого отката если чек фейковый
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton(
        f"❌ Отменить зачисление",
        callback_data=f"refund_{user_id}_{amount}"
    ))
    await bot.send_message(ADMIN_ID, "Если чек фейковый — нажми кнопку:", reply_markup=kb)

# Если прислали не фото
@dp.message_handler(state=DepositState.waiting_screenshot, content_types=types.ContentType.ANY)
async def deposit_wrong_content(message: types.Message):
    await message.answer(
        "📸 Пожалуйста, пришлите <b>фотографию</b> (скриншот) чека об оплате.",
        reply_markup=cancel_keyboard()
    )

# ─── Откат зачисления (для админа) ───────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data.startswith("refund_"))
async def admin_refund(call: types.CallbackQuery):
    if str(call.from_user.id) != str(ADMIN_ID):
        await call.answer("Нет доступа", show_alert=True)
        return

    parts = call.data.split("_")
    user_id = int(parts[1])
    amount = int(parts[2])

    # Списываем обратно
    await subtract_balance(user_id, amount)
    new_balance = await get_balance(user_id)

    await call.message.edit_text(
        f"✅ Зачисление отменено.\n"
        f"User: <code>{user_id}</code>\n"
        f"Списано: <b>{amount} ₽</b>\n"
        f"Остаток: <b>{new_balance} ₽</b>"
    )

    # Уведомляем пользователя
    try:
        await bot.send_message(
            user_id,
            f"❌ Ваш чек не прошёл проверку.\n\n"
            f"Пополнение на {amount} ₽ отменено.\n"
            f"Если это ошибка — обратитесь к @{SUPPORT_USERNAME}"
        )
    except Exception:
        pass

    await call.answer("Зачисление отменено")

# ─── Ручное пополнение командой /add (только для админа) ─────────────────────

@dp.message_handler(commands=["add"])
async def admin_add_balance(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Использование: /add USER_ID AMOUNT\nПример: /add 123456789 100")
        return
    user_id = int(parts[1])
    amount = int(parts[2])
    await add_balance(user_id, amount)
    new_balance = await get_balance(user_id)
    await message.answer(f"✅ Пополнено {amount} ₽\nUser: {user_id}\nНовый баланс: {new_balance} ₽")
    try:
        await bot.send_message(
            user_id,
            f"✅ Баланс пополнен!\n\n"
            f"💰 Зачислено: <b>{amount} ₽</b>\n"
            f"💳 Новый баланс: <b>{new_balance} ₽</b>"
        )
    except Exception:
        pass

# ─── 🎰 Рулетка ───────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "🎰 Рулетка")
async def roulette_menu(message: types.Message):
    await message.answer(roulette_description_text(), reply_markup=roulette_keyboard())

@dp.callback_query_handler(lambda c: c.data == "roulette_pay")
async def roulette_pay(call: types.CallbackQuery):
    await bot.send_invoice(
        chat_id=call.from_user.id,
        title="🎰 Рулетка GetTG",
        description="1 прокрут. Призы: 50₽ на баланс, прокси FI/DE/NL",
        payload=f"roulette:{call.from_user.id}",
        provider_token="",
        currency="XTR",
        prices=[LabeledPrice(label="Прокрут рулетки", amount=ROULETTE_PRICE_STARS)],
        start_parameter="roulette",
    )
    await call.answer()

# ─── Поддержка ────────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "📞 Поддержка")
async def support_menu(message: types.Message):
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("👨‍💻 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"))
    if CHANNEL_URL:
        kb.add(InlineKeyboardButton("📢 Канал", url=CHANNEL_URL))
    await message.answer(f"📞 Поддержка: @{SUPPORT_USERNAME}", reply_markup=kb)

# ─── Профиль ──────────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "👤 Профиль")
async def profile_menu(message: types.Message):
    user_id = message.from_user.id
    balance = await get_balance(user_id)
    country = await get_country(user_id)
    text = f"👤 <b>Ваш профиль:</b>\n\n💰 Баланс: {balance} руб.\n"
    if country:
        text += f"📡 Прокси: ✅ {COUNTRY_NAMES[country]}\n🔗 Ссылка: {PROXY_LINKS[country]}"
    else:
        text += "📡 Прокси: ❌ Нет активного прокси"
    await message.answer(text, disable_web_page_preview=True)

# ─── Соглашение ───────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "📄 Пользовательское соглашение")
async def agreement_menu(message: types.Message):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("👨‍💻 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"))
    await message.answer(AGREEMENT_TEXT, reply_markup=kb, disable_web_page_preview=True)

# ─── Покупка прокси ───────────────────────────────────────────────────────────

async def show_buy_options(call: types.CallbackQuery, country: str):
    user_id = call.from_user.id
    price_rub = PRICES[country]
    price_stars = STAR_PRICES[country]  # ← исправлено: фиксированная цена в звёздах
    balance = await get_balance(user_id)
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(f"⭐ Купить за {price_stars} звёзд", callback_data=f"buy_stars_{country}"))
    if balance >= price_rub:
        kb.add(InlineKeyboardButton(f"💰 С баланса ({price_rub} руб.)", callback_data=f"buy_balance_{country}"))
    else:
        kb.add(InlineKeyboardButton(f"❌ Недостаточно средств ({balance} руб.)", callback_data="no_money"))
    kb.add(InlineKeyboardButton("◀ Назад", callback_data="back_to_proxies"))
    await bot.send_message(
        user_id,
        f"{COUNTRY_NAMES[country]}\n"
        f"💰 Цена: {price_rub} руб. / {price_stars} ⭐\n"
        f"💳 Ваш баланс: {balance} руб.\n\n"
        f"Выберите способ оплаты:",
        reply_markup=kb
    )

@dp.callback_query_handler(
    lambda c: c.data.startswith("buy_")
    and not c.data.startswith("buy_stars_")
    and not c.data.startswith("buy_balance_")
)
async def process_buy_callback(call: types.CallbackQuery):
    await show_buy_options(call, call.data.split("_")[1])
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("buy_stars_"))
async def buy_proxy_stars(call: types.CallbackQuery):
    country = call.data.split("_")[2]
    price_stars = STAR_PRICES[country]  # ← исправлено: фиксированная цена
    await bot.send_invoice(
        call.from_user.id,
        title=f"Прокси {COUNTRY_NAMES[country]}",
        description=f"Оплата {price_stars} ⭐",
        provider_token=PAYMENTS_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label=f"Прокси {COUNTRY_NAMES[country]}", amount=price_stars)],
        start_parameter="buy_proxy",
        payload=f"proxy_{country}_{PRICES[country]}"
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("buy_balance_"))
async def buy_proxy_balance(call: types.CallbackQuery):
    user_id = call.from_user.id
    country = call.data.split("_")[2]
    price_rub = PRICES[country]
    if await subtract_balance(user_id, price_rub):
        await set_country(user_id, country)
        new_balance = await get_balance(user_id)
        kb = InlineKeyboardMarkup()
        if CHANNEL_URL:
            kb.add(InlineKeyboardButton("📢 Канал", url=CHANNEL_URL))
        kb.add(InlineKeyboardButton("👨‍💻 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"))
        await bot.send_message(
            user_id,
            f"✅ Прокси {COUNTRY_NAMES[country]} активирован!\n\n"
            f"💰 Списано: {price_rub} руб. | Остаток: {new_balance} руб.\n\n"
            f"🔗 Ваша ссылка:\n{PROXY_LINKS[country]}",
            reply_markup=kb,
            disable_web_page_preview=True
        )
    else:
        bal = await get_balance(user_id)
        await bot.send_message(
            user_id,
            f"❌ Недостаточно средств.\n"
            f"💰 Баланс: {bal} руб.\n"
            f"💳 Нужно: {price_rub} руб."
        )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "no_money")
async def no_money(call: types.CallbackQuery):
    await bot.send_message(
        call.from_user.id,
        "❌ Пополните баланс через кнопку «💰 Пополнить баланс»."
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_proxies")
async def back_to_proxies(call: types.CallbackQuery):
    user_id = call.from_user.id
    balance = await get_balance(user_id)
    text = "🛒 <b>Доступные прокси:</b>\n\n"
    for country, price in PRICES.items():
        stars = STAR_PRICES[country]
        text += f"{COUNTRY_NAMES[country]} — {price} руб. / {stars} ⭐\n"
    text += f"\n💰 Ваш баланс: {balance} руб."
    kb = InlineKeyboardMarkup(row_width=1)
    for country in PRICES:
        kb.add(InlineKeyboardButton(
            f"{COUNTRY_NAMES[country]} — {PRICES[country]} руб.",
            callback_data=f"buy_{country}"
        ))
    await bot.send_message(user_id, text, reply_markup=kb)
    await call.answer()

# ─── Pre-checkout ─────────────────────────────────────────────────────────────

@dp.pre_checkout_query_handler(lambda q: True)
async def pre_checkout(query: types.PreCheckoutQuery):
    await bot.answer_pre_checkout_query(query.id, ok=True)

# ─── Успешная оплата Stars ────────────────────────────────────────────────────

@dp.message_handler(content_types=types.ContentType.SUCCESSFUL_PAYMENT)
async def successful_payment(message: types.Message):
    user_id = message.from_user.id
    payload = message.successful_payment.invoice_payload

    # 🎰 Рулетка
    if payload.startswith("roulette:"):
        prize = roll_prize()
        spin_msg = await message.answer("🎰 Крутим...")
        for frame in ["🎰 ⬛⬛·", "🎰 ⬛·⬛", "🎰 ·⬛⬛", "🎰 ⬛·⬛", "🎰 ⬛⬛·", "🎰 ·⬛⬛"]:
            await asyncio.sleep(0.4)
            try:
                await bot.edit_message_text(frame, chat_id=user_id, message_id=spin_msg.message_id)
            except Exception:
                pass
        if prize["id"] == "balance_50":
            await add_balance(user_id, 50)
            result_extra = "✅ <b>50 ₽ зачислены на твой баланс!</b>"
        else:
            country = PRIZE_TO_COUNTRY[prize["id"]]
            await set_country(user_id, country)
            result_extra = f"✅ Прокси активирован!\n🔗 {PROXY_LINKS[country]}"
            await bot.send_message(
                ADMIN_ID,
                f"🎰 Рулетка\nUser: <code>{user_id}</code>\nПриз: <b>{prize['label']}</b>"
            )
        result_text = f"🎰 <b>Результат:</b>\n\n{prize['emoji']} <b>{prize['label']}</b>\n\n{result_extra}"
        try:
            await bot.edit_message_text(
                result_text, chat_id=user_id, message_id=spin_msg.message_id,
                reply_markup=spin_again_keyboard(), disable_web_page_preview=True
            )
        except Exception:
            await message.answer(result_text, reply_markup=spin_again_keyboard(), disable_web_page_preview=True)
        return

    # Прокси за Stars
    if payload.startswith("proxy_"):
        country = payload.split("_")[1]
        await set_country(user_id, country)
        kb = InlineKeyboardMarkup()
        if CHANNEL_URL:
            kb.add(InlineKeyboardButton("📢 Канал", url=CHANNEL_URL))
        kb.add(InlineKeyboardButton("👨‍💻 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"))
        await message.answer(
            f"✅ Прокси {COUNTRY_NAMES[country]} активирован!\n\n"
            f"🔗 Ваша ссылка:\n{PROXY_LINKS.get(country, '')}",
            reply_markup=kb,
            disable_web_page_preview=True
        )

# ─── Запуск ───────────────────────────────────────────────────────────────────

async def on_startup(dp):
    print("🔄 Инициализация БД...")
    await init_db()
    print("✅ Бот запущен и готов к работе")

if __name__ == "__main__":
    print("=" * 50)
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)