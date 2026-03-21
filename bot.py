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
    SOCKS5_GERMANY,
    PAYMENT_PAGE_URL, CHANNEL_URL, SUPPORT_USERNAME,
    ADMIN_ID, DATABASE_URL,
)

from database import (
    create_user, get_user, get_balance, add_balance,
    subtract_balance, set_country, get_country, init_db,
    get_user_by_ref_code, is_referred, ensure_ref_code,
    add_purchase, get_purchase_history,
    get_stats, get_top_users, get_all_user_ids,
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

REFERRAL_BONUS = 20
CHANNEL_ID = "@getTelegramm"

# ─── Константы ───────────────────────────────────────────────────────────────

PRICES_RUB = {
    "finland":        35,
    "germany":        40,
    "netherlands":    25,
    "germany_socks5": 80,
}

PRICES_STARS = {
    "finland":        20,
    "germany":        25,
    "netherlands":    15,
    "germany_socks5": 60,
}

COUNTRY_NAMES = {
    "finland":        "🇫🇮 Финляндия",
    "germany":        "🇩🇪 Германия",
    "netherlands":    "🇳🇱 Нидерланды",
    "germany_socks5": "🇩🇪 Германия SOCKS5",
}

PROXY_LINKS = {
    "finland":        MTProto_FINLAND,
    "germany":        MTProto_GERMANY,
    "netherlands":    MTProto_NETHERLANDS,
    "germany_socks5": SOCKS5_GERMANY,
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
    waiting_amount     = State()
    waiting_screenshot = State()

class BroadcastState(StatesGroup):
    waiting_message = State()

# ─── Проверка подписки ────────────────────────────────────────────────────────

async def is_subscribed(user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(CHANNEL_ID, user_id)
        return member.status in ("member", "administrator", "creator")
    except Exception as e:
        print(f"Ошибка проверки подписки: {e}")
        return False

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

def subscribe_keyboard(referrer_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton("📢 Подписаться на канал", url=CHANNEL_URL))
    kb.add(InlineKeyboardButton("✅ Я подписался", callback_data=f"check_sub_{referrer_id}"))
    return kb

# ─── /start ──────────────────────────────────────────────────────────────────

@dp.message_handler(commands=["start"])
async def start(message: types.Message):
    user_id = message.from_user.id
    args = message.get_args()

    referrer_id = None

    if args and args.startswith("ref_"):
        ref_code = args[4:]
        already_referred = await is_referred(user_id)
        if not already_referred:
            referrer = await get_user_by_ref_code(ref_code)
            if referrer and referrer['user_id'] != user_id:
                referrer_id = referrer['user_id']

    await create_user(user_id, referred_by=referrer_id)

    if referrer_id:
        subscribed = await is_subscribed(user_id)
        if subscribed:
            await give_referral_bonus(referrer_id, user_id)
        else:
            await message.answer(
                f"👋 Привет, {message.from_user.first_name}!\n\n"
                f"Вы перешли по реферальной ссылке.\n\n"
                f"📢 Чтобы ваш друг получил бонус <b>{REFERRAL_BONUS} ₽</b>, "
                f"подпишитесь на наш канал:",
                reply_markup=subscribe_keyboard(referrer_id)
            )
            await message.answer(
                "Добро пожаловать в магазин прокси!\n"
                "Выберите действие в меню ниже:",
                reply_markup=get_main_keyboard()
            )
            return

    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        f"Добро пожаловать в магазин прокси.\n"
        f"Выберите действие в меню ниже:",
        reply_markup=get_main_keyboard()
    )

async def give_referral_bonus(referrer_id: int, new_user_id: int):
    await add_balance(referrer_id, REFERRAL_BONUS)
    try:
        await bot.send_message(
            referrer_id,
            f"🎉 Ваш друг подписался на канал и зарегистрировался!\n\n"
            f"💰 Вам начислено <b>{REFERRAL_BONUS} ₽</b> на баланс."
        )
    except Exception:
        pass

@dp.callback_query_handler(lambda c: c.data.startswith("check_sub_"))
async def check_subscription(call: types.CallbackQuery):
    user_id = call.from_user.id
    referrer_id = int(call.data.split("_")[2])

    subscribed = await is_subscribed(user_id)
    if subscribed:
        user_data = await get_user(user_id)
        if user_data and user_data.get('referred_by') == referrer_id:
            await give_referral_bonus(referrer_id, user_id)
            await call.message.edit_reply_markup()
            await call.answer("✅ Спасибо за подписку! Ваш друг получил бонус.", show_alert=True)
        else:
            await call.answer("✅ Подписка подтверждена!", show_alert=True)
    else:
        await call.answer(
            "❌ Вы ещё не подписались!\n\nПодпишитесь на канал и нажмите кнопку снова.",
            show_alert=True
        )

# ─── Купить прокси ────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "🛒 Купить прокси")
async def show_proxies(message: types.Message):
    balance = await get_balance(message.from_user.id)
    text = "🛒 <b>Доступные прокси:</b>\n\n"
    for country in PRICES_RUB:
        text += f"{COUNTRY_NAMES[country]} — {PRICES_RUB[country]} руб. / {PRICES_STARS[country]} ⭐\n"
    text += f"\n⚡ <i>SOCKS5 обходит ВСЕ сервисы</i>"
    text += f"\n\n💰 Ваш баланс: {balance} руб."
    kb = InlineKeyboardMarkup(row_width=1)
    for country in PRICES_RUB:
        kb.add(InlineKeyboardButton(
            f"{COUNTRY_NAMES[country]} — {PRICES_RUB[country]} руб. / {PRICES_STARS[country]} ⭐",
            callback_data=f"buy_{country}"
        ))
    await message.answer(text, reply_markup=kb)

# ─── Пополнить баланс ─────────────────────────────────────────────────────────

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

@dp.message_handler(state=DepositState.waiting_screenshot, content_types=types.ContentType.PHOTO)
async def deposit_got_screenshot(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    data = await state.get_data()
    amount = data.get("expected_amount", 0)

    await add_balance(user_id, amount)
    new_balance = await get_balance(user_id)
    await state.finish()

    await message.answer(
        f"✅ <b>Оплата принята!</b>\n\n"
        f"💰 Зачислено: <b>{amount} ₽</b>\n"
        f"💳 Новый баланс: <b>{new_balance} ₽</b>",
        reply_markup=get_main_keyboard()
    )

    username = f"@{message.from_user.username}" if message.from_user.username else "нет"
    await bot.send_message(
        ADMIN_ID,
        f"💰 <b>Пополнение баланса</b>\n\n"
        f"👤 User: <code>{user_id}</code> ({username})\n"
        f"💵 Сумма: <b>{amount} ₽</b>\n"
        f"💳 Баланс: <b>{new_balance} ₽</b>\n\n"
        f"📸 Скриншот:"
    )
    await bot.forward_message(ADMIN_ID, user_id, message.message_id)
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("❌ Отменить зачисление", callback_data=f"refund_{user_id}_{amount}"))
    await bot.send_message(ADMIN_ID, "Если чек фейковый — нажми:", reply_markup=kb)

@dp.message_handler(state=DepositState.waiting_screenshot, content_types=types.ContentType.ANY)
async def deposit_wrong_content(message: types.Message):
    await message.answer(
        "📸 Пожалуйста, пришлите <b>фотографию</b> скриншота чека об оплате.",
        reply_markup=cancel_keyboard()
    )

# ─── Откат зачисления ────────────────────────────────────────────────────────

@dp.callback_query_handler(lambda c: c.data.startswith("refund_"))
async def admin_refund(call: types.CallbackQuery):
    if str(call.from_user.id) != str(ADMIN_ID):
        await call.answer("Нет доступа", show_alert=True)
        return
    parts = call.data.split("_")
    user_id = int(parts[1])
    amount = int(parts[2])
    await subtract_balance(user_id, amount)
    new_balance = await get_balance(user_id)
    await call.message.edit_text(
        f"✅ Зачисление отменено.\nUser: <code>{user_id}</code>\n"
        f"Списано: <b>{amount} ₽</b> | Остаток: <b>{new_balance} ₽</b>"
    )
    try:
        await bot.send_message(
            user_id,
            f"❌ Ваш чек не прошёл проверку.\n"
            f"Пополнение на {amount} ₽ отменено.\n"
            f"Если ошибка — обратитесь к @{SUPPORT_USERNAME}"
        )
    except Exception:
        pass
    await call.answer("Зачисление отменено")

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

# ─── Профиль ─────────────────────────────────────────────────────────────────

@dp.message_handler(lambda m: m.text == "👤 Профиль")
async def profile_menu(message: types.Message):
    user_id = message.from_user.id
    user = await get_user(user_id)
    balance = user['balance'] if user else 0
    country = user['country'] if user else None

    # ensure_ref_code генерирует и сохраняет код если его нет
    ref_code = await ensure_ref_code(user_id)

    bot_info = await bot.get_me()
    ref_link = f"https://t.me/{bot_info.username}?start=ref_{ref_code}"

    text = f"👤 <b>Ваш профиль:</b>\n\n"
    text += f"💰 Баланс: <b>{balance} руб.</b>\n"

    if country:
        text += f"📡 Прокси: ✅ {COUNTRY_NAMES.get(country, country)}\n"
        text += f"🔗 Ссылка: {PROXY_LINKS.get(country, '')}\n"
    else:
        text += f"📡 Прокси: ❌ Нет активного прокси\n"

    text += (
        f"\n👥 <b>Реферальная ссылка:</b>\n{ref_link}\n"
        f"<i>За каждого друга, подписавшегося на канал +{REFERRAL_BONUS} ₽</i>\n"
    )

    history = await get_purchase_history(user_id, limit=5)
    if history:
        text += f"\n📋 <b>Последние покупки:</b>\n"
        for p in history:
            date = p['purchased_at'].strftime("%d.%m.%y")
            text += f"• {p['product']} — {p['amount_rub']} ₽ [{date}]\n"
    else:
        text += f"\n📋 <b>Покупок пока нет</b>"

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
    price_rub = PRICES_RUB[country]
    price_stars = PRICES_STARS[country]
    balance = await get_balance(user_id)
    kb = InlineKeyboardMarkup(row_width=1)
    kb.add(InlineKeyboardButton(f"⭐ Купить за {price_stars} звёзд", callback_data=f"buy_stars_{country}"))
    if balance >= price_rub:
        kb.add(InlineKeyboardButton(f"💰 С баланса ({price_rub} руб.)", callback_data=f"buy_balance_{country}"))
    else:
        kb.add(InlineKeyboardButton(f"❌ Недостаточно средств ({balance} руб.)", callback_data="no_money"))
    kb.add(InlineKeyboardButton("◀ Назад", callback_data="back_to_proxies"))
    extra = "\n⚡ <i>Обходит ВСЕ сервисы</i>" if country == "germany_socks5" else ""
    await bot.send_message(
        user_id,
        f"{COUNTRY_NAMES[country]}{extra}\n\n"
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
    country = "_".join(call.data.split("_")[1:])
    await show_buy_options(call, country)
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("buy_stars_"))
async def buy_proxy_stars(call: types.CallbackQuery):
    country = "_".join(call.data.split("_")[2:])
    price_stars = PRICES_STARS[country]
    await bot.send_invoice(
        call.from_user.id,
        title=f"Прокси {COUNTRY_NAMES[country]}",
        description=f"Оплата {price_stars} ⭐",
        provider_token=PAYMENTS_TOKEN,
        currency="XTR",
        prices=[LabeledPrice(label=f"Прокси {COUNTRY_NAMES[country]}", amount=price_stars)],
        start_parameter="buy_proxy",
        payload=f"proxy_{country}_{PRICES_RUB[country]}"
    )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("buy_balance_"))
async def buy_proxy_balance(call: types.CallbackQuery):
    user_id = call.from_user.id
    country = "_".join(call.data.split("_")[2:])
    price_rub = PRICES_RUB[country]
    if await subtract_balance(user_id, price_rub):
        await set_country(user_id, country)
        new_balance = await get_balance(user_id)
        await add_purchase(user_id, COUNTRY_NAMES[country], price_rub, "balance")
        kb = InlineKeyboardMarkup()
        if CHANNEL_URL:
            kb.add(InlineKeyboardButton("📢 Канал", url=CHANNEL_URL))
        kb.add(InlineKeyboardButton("👨‍💻 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"))
        await bot.send_message(
            user_id,
            f"✅ Прокси {COUNTRY_NAMES[country]} активирован!\n\n"
            f"💰 Списано: {price_rub} руб. | Остаток: {new_balance} руб.\n\n"
            f"🔗 Ваша ссылка:\n{PROXY_LINKS[country]}",
            reply_markup=kb, disable_web_page_preview=True
        )
    else:
        bal = await get_balance(user_id)
        await bot.send_message(
            user_id,
            f"❌ Недостаточно средств.\n💰 Баланс: {bal} руб.\n💳 Нужно: {price_rub} руб."
        )
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "no_money")
async def no_money(call: types.CallbackQuery):
    await bot.send_message(call.from_user.id, "❌ Пополните баланс через кнопку «💰 Пополнить баланс».")
    await call.answer()

@dp.callback_query_handler(lambda c: c.data == "back_to_proxies")
async def back_to_proxies(call: types.CallbackQuery):
    user_id = call.from_user.id
    balance = await get_balance(user_id)
    text = "🛒 <b>Доступные прокси:</b>\n\n"
    for country in PRICES_RUB:
        text += f"{COUNTRY_NAMES[country]} — {PRICES_RUB[country]} руб. / {PRICES_STARS[country]} ⭐\n"
    text += f"\n⚡ <i>SOCKS5 обходит ВСЕ сервисы</i>"
    text += f"\n\n💰 Ваш баланс: {balance} руб."
    kb = InlineKeyboardMarkup(row_width=1)
    for country in PRICES_RUB:
        kb.add(InlineKeyboardButton(
            f"{COUNTRY_NAMES[country]} — {PRICES_RUB[country]} руб. / {PRICES_STARS[country]} ⭐",
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
            await add_purchase(user_id, COUNTRY_NAMES[country] + " (рулетка)", 0, "stars")
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

    if payload.startswith("proxy_"):
        parts = payload.split("_")
        country = "_".join(parts[1:-1])
        price_rub = PRICES_RUB.get(country, 0)
        await set_country(user_id, country)
        await add_purchase(user_id, COUNTRY_NAMES.get(country, country), price_rub, "stars")
        kb = InlineKeyboardMarkup()
        if CHANNEL_URL:
            kb.add(InlineKeyboardButton("📢 Канал", url=CHANNEL_URL))
        kb.add(InlineKeyboardButton("👨‍💻 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}"))
        await message.answer(
            f"✅ Прокси {COUNTRY_NAMES.get(country, country)} активирован!\n\n"
            f"🔗 Ваша ссылка:\n{PROXY_LINKS.get(country, '')}",
            reply_markup=kb, disable_web_page_preview=True
        )

# ─── Админ команды ────────────────────────────────────────────────────────────

@dp.message_handler(commands=["add"])
async def admin_add_balance(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    parts = message.text.split()
    if len(parts) != 3 or not parts[1].isdigit() or not parts[2].isdigit():
        await message.answer("Использование: /add USER_ID СУММА")
        return
    user_id = int(parts[1])
    amount = int(parts[2])
    await add_balance(user_id, amount)
    new_balance = await get_balance(user_id)
    await message.answer(f"✅ Пополнено {amount} ₽\nUser: {user_id}\nБаланс: {new_balance} ₽")
    try:
        await bot.send_message(user_id, f"✅ Баланс пополнен!\n\n💰 Зачислено: <b>{amount} ₽</b>\n💳 Баланс: <b>{new_balance} ₽</b>")
    except Exception:
        pass

@dp.message_handler(commands=["stats"])
async def admin_stats(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    stats = await get_stats()
    await message.answer(
        f"📊 <b>Статистика GetTG</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"🆕 Новых сегодня: <b>{stats['new_today']}</b>\n\n"
        f"🛒 Всего покупок: <b>{stats['total_purchases']}</b>\n"
        f"💰 Выручка (с баланса): <b>{stats['total_revenue']} ₽</b>\n"
        f"⭐ Покупок за Stars: <b>{stats['total_stars_purchases']}</b>\n\n"
        f"🏆 Топ товар: <b>{stats['top_product']}</b>"
    )

@dp.message_handler(commands=["users"])
async def admin_users(message: types.Message):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    top = await get_top_users(10)
    if not top:
        await message.answer("Нет данных.")
        return
    text = "🏆 <b>Топ пользователей по покупкам:</b>\n\n"
    for i, u in enumerate(top, 1):
        text += (
            f"{i}. <code>{u['user_id']}</code>\n"
            f"   💰 Баланс: {u['balance']} ₽ | "
            f"Покупок: {u['purchases_count']} | "
            f"Потрачено: {u['total_spent']} ₽\n\n"
        )
    await message.answer(text)

@dp.message_handler(commands=["broadcast"])
async def admin_broadcast_start(message: types.Message, state: FSMContext):
    if str(message.from_user.id) != str(ADMIN_ID):
        return
    text_after = message.text.partition(" ")[2].strip()
    if text_after:
        await do_broadcast(message, text_after)
    else:
        await message.answer("Введите текст для рассылки:")
        await BroadcastState.waiting_message.set()

@dp.message_handler(state=BroadcastState.waiting_message)
async def admin_broadcast_send(message: types.Message, state: FSMContext):
    await state.finish()
    await do_broadcast(message, message.text)

async def do_broadcast(message: types.Message, text: str):
    user_ids = await get_all_user_ids()
    sent = 0
    failed = 0
    status_msg = await message.answer(f"📤 Рассылаем {len(user_ids)} пользователям...")
    for uid in user_ids:
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(
        f"✅ Рассылка завершена!\n\n"
        f"📨 Отправлено: <b>{sent}</b>\n"
        f"❌ Не доставлено: <b>{failed}</b>"
    )

# ─── Запуск ───────────────────────────────────────────────────────────────────

async def on_startup(dp):
    print("🔄 Инициализация БД...")
    await init_db()
    print(f"✅ Бот готов | Реферальный канал: {CHANNEL_ID}")

if __name__ == "__main__":
    print("=" * 50)
    executor.start_polling(dp, skip_updates=True, on_startup=on_startup)
