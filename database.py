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
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                balance INTEGER DEFAULT 0,
                country TEXT
            )
        ''')
        print("✅ Таблица users готова")
    finally:
        await conn.close()

async def create_user(user_id: int):
    conn = await get_connection()
    try:
        await conn.execute('''
            INSERT INTO users (user_id) VALUES ($1)
            ON CONFLICT (user_id) DO NOTHING
        ''', user_id)
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
            INSERT INTO users (user_id, balance) VALUES ($1, $2)
            ON CONFLICT (user_id) DO UPDATE SET balance = users.balance + $2
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
