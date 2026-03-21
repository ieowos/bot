import asyncpg
import os
from typing import Optional

DATABASE_URL = os.getenv('DATABASE_URL')

async def get_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL не задан")
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_connection()
    try:
        # Основная таблица пользователей
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                country TEXT,
                referral_code TEXT UNIQUE,
                referred_by BIGINT DEFAULT NULL,
                created_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        # Добавляем колонки если их нет (для старых БД)
        for col, definition in [
            ("referral_code", "TEXT UNIQUE"),
            ("referred_by",   "BIGINT DEFAULT NULL"),
            ("created_at",    "TIMESTAMP DEFAULT NOW()"),
        ]:
            try:
                await conn.execute(f'ALTER TABLE users ADD COLUMN {col} {definition}')
            except Exception:
                pass

        # Таблица истории покупок
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS purchases (
                id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL,
                product TEXT NOT NULL,
                amount_rub INTEGER NOT NULL,
                paid_with TEXT NOT NULL,
                purchased_at TIMESTAMP DEFAULT NOW()
            )
        ''')
        print("✅ БД готова")
    finally:
        await conn.close()

async def create_user(user_id: int, referred_by: int = None):
    conn = await get_connection()
    try:
        import hashlib, time
        ref_code = hashlib.md5(f"{user_id}{time.time()}".encode()).hexdigest()[:8].upper()
        await conn.execute('''
            INSERT INTO users (user_id, referral_code, referred_by)
            VALUES ($1, $2, $3)
            ON CONFLICT (user_id) DO NOTHING
        ''', user_id, ref_code, referred_by)
    finally:
        await conn.close()

async def get_user(user_id: int) -> Optional[dict]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow('SELECT * FROM users WHERE user_id = $1', user_id)
        return dict(row) if row else None
    finally:
        await conn.close()

async def get_balance(user_id: int) -> int:
    conn = await get_connection()
    try:
        row = await conn.fetchrow('SELECT balance FROM users WHERE user_id = $1', user_id)
        return row['balance'] if row else 0
    finally:
        await conn.close()

async def add_balance(user_id: int, amount: int):
    conn = await get_connection()
    try:
        await conn.execute('''
            INSERT INTO users (user_id, balance)
            VALUES ($1, $2)
            ON CONFLICT (user_id)
            DO UPDATE SET balance = users.balance + $2
        ''', user_id, amount)
    finally:
        await conn.close()

async def subtract_balance(user_id: int, amount: int) -> bool:
    conn = await get_connection()
    try:
        async with conn.transaction():
            row = await conn.fetchrow('SELECT balance FROM users WHERE user_id = $1', user_id)
            if row and row['balance'] >= amount:
                await conn.execute(
                    'UPDATE users SET balance = balance - $1 WHERE user_id = $2',
                    amount, user_id
                )
                return True
            return False
    finally:
        await conn.close()

async def set_country(user_id: int, country: str):
    conn = await get_connection()
    try:
        await conn.execute('UPDATE users SET country = $1 WHERE user_id = $2', country, user_id)
    finally:
        await conn.close()

async def get_country(user_id: int) -> Optional[str]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow('SELECT country FROM users WHERE user_id = $1', user_id)
        return row['country'] if row else None
    finally:
        await conn.close()

async def get_user_by_ref_code(ref_code: str) -> Optional[dict]:
    conn = await get_connection()
    try:
        row = await conn.fetchrow(
            'SELECT * FROM users WHERE referral_code = $1', ref_code.upper()
        )
        return dict(row) if row else None
    finally:
        await conn.close()

async def is_referred(user_id: int) -> bool:
    """Проверяет был ли пользователь уже кем-то приглашён."""
    conn = await get_connection()
    try:
        row = await conn.fetchrow('SELECT referred_by FROM users WHERE user_id = $1', user_id)
        return row is not None and row['referred_by'] is not None
    finally:
        await conn.close()

async def add_purchase(user_id: int, product: str, amount_rub: int, paid_with: str):
    """Записывает покупку в историю."""
    conn = await get_connection()
    try:
        await conn.execute('''
            INSERT INTO purchases (user_id, product, amount_rub, paid_with)
            VALUES ($1, $2, $3, $4)
        ''', user_id, product, amount_rub, paid_with)
    finally:
        await conn.close()

async def get_purchase_history(user_id: int, limit: int = 10) -> list:
    conn = await get_connection()
    try:
        rows = await conn.fetch('''
            SELECT product, amount_rub, paid_with, purchased_at
            FROM purchases
            WHERE user_id = $1
            ORDER BY purchased_at DESC
            LIMIT $2
        ''', user_id, limit)
        return [dict(r) for r in rows]
    finally:
        await conn.close()

# ─── Статистика для админа ────────────────────────────────────────────────────

async def get_stats() -> dict:
    conn = await get_connection()
    try:
        total_users = await conn.fetchval('SELECT COUNT(*) FROM users')
        total_purchases = await conn.fetchval('SELECT COUNT(*) FROM purchases')
        total_revenue = await conn.fetchval(
            "SELECT COALESCE(SUM(amount_rub), 0) FROM purchases WHERE paid_with = 'balance'"
        )
        total_stars_purchases = await conn.fetchval(
            "SELECT COUNT(*) FROM purchases WHERE paid_with = 'stars'"
        )
        top_country = await conn.fetchrow('''
            SELECT product, COUNT(*) as cnt
            FROM purchases
            GROUP BY product
            ORDER BY cnt DESC
            LIMIT 1
        ''')
        new_today = await conn.fetchval(
            "SELECT COUNT(*) FROM users WHERE created_at >= NOW() - INTERVAL '1 day'"
        )
        return {
            "total_users":           total_users,
            "new_today":             new_today,
            "total_purchases":       total_purchases,
            "total_revenue":         total_revenue,
            "total_stars_purchases": total_stars_purchases,
            "top_product":           top_country['product'] if top_country else "нет данных",
        }
    finally:
        await conn.close()

async def get_top_users(limit: int = 10) -> list:
    conn = await get_connection()
    try:
        rows = await conn.fetch('''
            SELECT u.user_id, u.balance,
                   COUNT(p.id) as purchases_count,
                   COALESCE(SUM(p.amount_rub), 0) as total_spent
            FROM users u
            LEFT JOIN purchases p ON p.user_id = u.user_id
            GROUP BY u.user_id, u.balance
            ORDER BY total_spent DESC
            LIMIT $1
        ''', limit)
        return [dict(r) for r in rows]
    finally:
        await conn.close()

async def get_all_user_ids() -> list:
    conn = await get_connection()
    try:
        rows = await conn.fetch('SELECT user_id FROM users')
        return [r['user_id'] for r in rows]
    finally:
        await conn.close()
