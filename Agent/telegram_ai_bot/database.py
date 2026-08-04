"""
Проста робота з SQLite для збереження товарів, ціни яких відстежує бот.
"""
import sqlite3
from contextlib import contextmanager

from config import DATABASE_PATH


@contextmanager
def get_connection():
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tracked_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                query TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT,
                last_price TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )


def add_tracked_item(chat_id: int, query: str, url: str, title: str, price: str):
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO tracked_items (chat_id, query, url, title, last_price) "
            "VALUES (?, ?, ?, ?, ?)",
            (chat_id, query, url, title, price),
        )


def get_tracked_items(chat_id: int):
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM tracked_items WHERE chat_id = ? ORDER BY created_at DESC",
            (chat_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_all_tracked_items():
    with get_connection() as conn:
        rows = conn.execute("SELECT * FROM tracked_items").fetchall()
        return [dict(r) for r in rows]


def update_tracked_price(item_id: int, new_price: str):
    with get_connection() as conn:
        conn.execute(
            "UPDATE tracked_items SET last_price = ? WHERE id = ?",
            (new_price, item_id),
        )


def delete_tracked_item(item_id: int, chat_id: int) -> bool:
    with get_connection() as conn:
        cur = conn.execute(
            "DELETE FROM tracked_items WHERE id = ? AND chat_id = ?",
            (item_id, chat_id),
        )
        return cur.rowcount > 0
