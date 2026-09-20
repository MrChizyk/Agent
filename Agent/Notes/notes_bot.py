"""
Телеграм-бот «Сейф» — нотатки з персональним паролем у кожного користувача.

Встановлення:
    pip install python-telegram-bot --upgrade

Запуск:
    export BOT_TOKEN="твій_токен"     # або впиши в CONFIG нижче
    python notes_bot.py

Що нового:
- Пароль задається ПРЯМО В БОТІ (/start → придумай пароль → повтори його).
- У кожного user_id свій пароль, тож ботом можуть користуватись різні люди.
- Паролі НЕ зберігаються у відкритому вигляді: тільки PBKDF2-HMAC-SHA256
  (200 000 ітерацій) + унікальна сіль. Навіть маючи notes.db, пароль не прочитати.
- Після 5 невдалих спроб — блокування на 5 хвилин.
- /password — змінити пароль (спитає старий).
- Усі повідомлення зникають з чату через 60 сек; паролі — миттєво.
"""

import os
import asyncio
import sqlite3
import hashlib
import hmac
import secrets
import logging
from datetime import datetime, timedelta
from html import escape

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ─────────────────────────── CONFIG ───────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")   # або впиши сюди рядком: "123:ABC..."
DB_PATH = os.environ.get("NOTES_DB_PATH", "notes.db")
AUTODELETE_SECONDS = 60      # через скільки секунд повідомлення зникає з чату
MIN_PASSWORD_LEN = 4         # мінімальна довжина пароля
MAX_ATTEMPTS = 5             # спроб до блокування
LOCKOUT_MINUTES = 5          # на скільки блокуємо
PBKDF2_ROUNDS = 200_000
# ──────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

if not BOT_TOKEN:
    raise RuntimeError("Заповни BOT_TOKEN — у CONFIG вище або через export BOT_TOKEN=...")

DIVIDER = "─" * 18

# Стан діалогу: {user_id: {"step": ..., "data": ...}}
# step ∈ {"set_new", "set_repeat", "ask_old", "auth_show", "auth_clear"}
state: dict[int, dict] = {}


# ═══════════════════════ ХЕШУВАННЯ ПАРОЛЯ ═══════════════════════
def hash_password(password: str, salt: bytes | None = None) -> tuple[str, str]:
    """Повертає (hex-сіль, hex-хеш). Пароль у відкритому вигляді ніде не лишається."""
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return salt.hex(), digest.hex()


def verify_password(password: str, salt_hex: str, hash_hex: str) -> bool:
    _, candidate = hash_password(password, bytes.fromhex(salt_hex))
    # compare_digest — захист від timing-атак
    return hmac.compare_digest(candidate, hash_hex)


# ═══════════════════════════ БАЗА ═══════════════════════════
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       INTEGER PRIMARY KEY,
                salt          TEXT    NOT NULL,
                pwd_hash      TEXT    NOT NULL,
                created_at    TEXT    NOT NULL,
                failed_tries  INTEGER NOT NULL DEFAULT 0,
                locked_until  TEXT
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER NOT NULL,
                text       TEXT    NOT NULL,
                created_at TEXT    NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id)")


def get_user(user_id: int):
    with db() as conn:
        return conn.execute(
            "SELECT * FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()


def set_password(user_id: int, password: str) -> None:
    salt, pwd_hash = hash_password(password)
    with db() as conn:
        conn.execute(
            """
            INSERT INTO users (user_id, salt, pwd_hash, created_at, failed_tries, locked_until)
            VALUES (?, ?, ?, ?, 0, NULL)
            ON CONFLICT(user_id) DO UPDATE SET
                salt = excluded.salt,
                pwd_hash = excluded.pwd_hash,
                failed_tries = 0,
                locked_until = NULL
            """,
            (user_id, salt, pwd_hash, datetime.now().isoformat(timespec="seconds")),
        )


def check_password(user_id: int, password: str) -> bool:
    user = get_user(user_id)
    if not user:
        return False
    return verify_password(password, user["salt"], user["pwd_hash"])


def is_locked(user_id: int) -> int:
    """Повертає скільки секунд лишилось блокування (0 — не заблоковано)."""
    user = get_user(user_id)
    if not user or not user["locked_until"]:
        return 0
    left = (datetime.fromisoformat(user["locked_until"]) - datetime.now()).total_seconds()
    return max(0, int(left))


def register_fail(user_id: int) -> int:
    """Рахує невдалу спробу. Повертає скільки спроб лишилось (0 = заблоковано)."""
    with db() as conn:
        row = conn.execute(
            "SELECT failed_tries FROM users WHERE user_id = ?", (user_id,)
        ).fetchone()
        tries = (row["failed_tries"] if row else 0) + 1
        if tries >= MAX_ATTEMPTS:
            until = (datetime.now() + timedelta(minutes=LOCKOUT_MINUTES)).isoformat()
            conn.execute(
                "UPDATE users SET failed_tries = 0, locked_until = ? WHERE user_id = ?",
                (until, user_id),
            )
            return 0
        conn.execute(
            "UPDATE users SET failed_tries = ? WHERE user_id = ?", (tries, user_id)
        )
        return MAX_ATTEMPTS - tries


def reset_fails(user_id: int) -> None:
    with db() as conn:
        conn.execute(
            "UPDATE users SET failed_tries = 0, locked_until = NULL WHERE user_id = ?",
            (user_id,),
        )


def save_note(user_id: int, text: str) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO notes (user_id, text, created_at) VALUES (?, ?, ?)",
            (user_id, text, datetime.now().isoformat(timespec="seconds")),
        )


def get_notes(user_id: int) -> list:
    with db() as conn:
        return conn.execute(
            "SELECT text, created_at FROM notes WHERE user_id = ? ORDER BY id",
            (user_id,),
        ).fetchall()


def count_notes(user_id: int) -> int:
    with db() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM notes WHERE user_id = ?", (user_id,)
        ).fetchone()[0]


def clear_notes(user_id: int) -> int:
    with db() as conn:
        return conn.execute("DELETE FROM notes WHERE user_id = ?", (user_id,)).rowcount


# ═══════════════════ АВТОВИДАЛЕННЯ ПОВІДОМЛЕНЬ ═══════════════════
async def _delete_later(bot, chat_id: int, message_id: int, delay: int) -> None:
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError as e:
        logger.debug("Не вдалось видалити %s: %s", message_id, e)


def autodelete(context, chat_id: int, message_id: int, delay: int = AUTODELETE_SECONDS):
    asyncio.create_task(_delete_later(context.bot, chat_id, message_id, delay))


async def delete_now(context, chat_id: int, message_id: int) -> None:
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except TelegramError:
        pass


async def reply(context, chat_id: int, text: str, delay: int = AUTODELETE_SECONDS,
                keyboard=None, keep: bool = False):
    """Надсилає HTML-повідомлення і (за замовчуванням) ставить його на самознищення."""
    msg = await context.bot.send_message(
        chat_id, text, parse_mode=ParseMode.HTML, reply_markup=keyboard
    )
    if not keep:
        autodelete(context, chat_id, msg.message_id, delay)
    return msg


# ═══════════════════════════ UI ═══════════════════════════
MAIN_KB = InlineKeyboardMarkup(
    [
        [
            InlineKeyboardButton("🔓 Показати", callback_data="show"),
            InlineKeyboardButton("🗑 Очистити", callback_data="clear"),
        ],
        [InlineKeyboardButton("🔑 Змінити пароль", callback_data="chpwd")],
    ]
)


# ═══════════════════════════ КОМАНДИ ═══════════════════════════
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    chat_id = update.message.chat_id
    name = escape(user.first_name or "друже")

    if not get_user(user.id):
        state[user.id] = {"step": "set_new"}
        await reply(
            context, chat_id,
            f"🔐 <b>Особистий сейф</b>\n"
            f"{DIVIDER}\n"
            f"Вітаю, <b>{name}</b>!\n\n"
            f"Спершу придумай <b>пароль</b> — ним ти відкриватимеш свої записи.\n"
            f"Мінімум {MIN_PASSWORD_LEN} символи.\n\n"
            f"<i>Надішли його наступним повідомленням — я одразу його зітру з чату "
            f"і збережу лише незворотний хеш.</i>",
            delay=120,
        )
        return

    await reply(
        context, chat_id,
        f"🔐 <b>Особистий сейф</b>\n"
        f"{DIVIDER}\n"
        f"З поверненням, <b>{name}</b>!\n\n"
        f"Надішли будь-який текст — збережу.\n"
        f"📦 У сейфі: <b>{count_notes(user.id)}</b> запис(ів)\n"
        f"{DIVIDER}\n"
        f"<code>/show</code> — показати\n"
        f"<code>/clear</code> — очистити\n"
        f"<code>/password</code> — змінити пароль",
        keyboard=MAIN_KB, keep=True,
    )


async def need_setup(context, chat_id: int) -> None:
    await reply(
        context, chat_id,
        f"⚠️ <b>Пароль ще не встановлено</b>\n{DIVIDER}\nНатисни /start, щоб його задати.",
        delay=30,
    )


async def ask_password(context, chat_id: int, user_id: int, action: str) -> None:
    if not get_user(user_id):
        await need_setup(context, chat_id)
        return

    left = is_locked(user_id)
    if left:
        await reply(
            context, chat_id,
            f"🚫 <b>Заблоковано</b>\n{DIVIDER}\n"
            f"Забагато невдалих спроб.\nСпробуй через <b>{left // 60 + 1} хв</b>.",
            delay=30,
        )
        return

    state[user_id] = {"step": f"auth_{action}"}
    what = "перегляду записів" if action == "show" else "<b>видалення всіх</b> записів"
    await reply(
        context, chat_id,
        f"🔑 <b>Введи пароль</b>\n{DIVIDER}\nДля {what}.\n"
        f"<i>Повідомлення з паролем зітреться миттєво.</i>",
        delay=45,
    )


async def show_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await delete_now(context, update.message.chat_id, update.message.message_id)
    await ask_password(context, update.message.chat_id, update.effective_user.id, "show")


async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await delete_now(context, update.message.chat_id, update.message.message_id)
    await ask_password(context, update.message.chat_id, update.effective_user.id, "clear")


async def password_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    await delete_now(context, chat_id, update.message.message_id)
    await start_change_password(context, chat_id, user_id)


async def start_change_password(context, chat_id: int, user_id: int) -> None:
    if not get_user(user_id):
        await need_setup(context, chat_id)
        return
    state[user_id] = {"step": "ask_old"}
    await reply(
        context, chat_id,
        f"🔑 <b>Зміна пароля</b>\n{DIVIDER}\nНадішли <b>поточний</b> пароль.",
        delay=45,
    )


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat_id, user_id = query.message.chat_id, query.from_user.id
    if query.data == "chpwd":
        await start_change_password(context, chat_id, user_id)
    else:
        await ask_password(context, chat_id, user_id, query.data)


# ═══════════════════════ ВИВІД НОТАТОК ═══════════════════════
async def send_notes(context, chat_id: int, user_id: int) -> None:
    notes = get_notes(user_id)
    if not notes:
        await reply(context, chat_id,
                    f"📭 <b>Сейф порожній</b>\n{DIVIDER}\nНадішли щось — я збережу.")
        return

    header = (
        f"🔓 <b>Доступ відкрито</b>\n{DIVIDER}\n"
        f"📦 Записів: <b>{len(notes)}</b>\n"
        f"⏳ Зникне через {AUTODELETE_SECONDS} сек\n"
    )
    chunk = header
    for i, n in enumerate(notes, 1):
        date, time = n["created_at"].split("T")
        block = (f"\n<b>{i}.</b> <i>{date} {time}</i>\n"
                 f"<blockquote>{escape(n['text'])}</blockquote>")
        if len(chunk) + len(block) > 3500:
            await reply(context, chat_id, chunk)
            chunk = ""
        chunk += block
    if chunk.strip():
        await reply(context, chat_id, chunk)


# ═══════════════════════ ГОЛОВНИЙ ХЕНДЛЕР ═══════════════════════
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    chat_id = update.message.chat_id
    text = update.message.text
    st = state.get(user_id)

    # ─── Будь-який крок із паролем: стираємо повідомлення миттєво ───
    if st:
        await delete_now(context, chat_id, update.message.message_id)
        step = st["step"]

        # 1. Створення пароля
        if step == "set_new":
            if len(text) < MIN_PASSWORD_LEN:
                await reply(context, chat_id,
                            f"⚠️ Закороткий пароль — мінімум {MIN_PASSWORD_LEN} символи. "
                            f"Спробуй ще раз.", delay=30)
                return
            state[user_id] = {"step": "set_repeat", "pwd": text}
            await reply(context, chat_id,
                        f"🔁 <b>Повтори пароль</b>\n{DIVIDER}\nЩоб не було друкарської помилки.",
                        delay=60)
            return

        if step == "set_repeat":
            if text != st["pwd"]:
                state[user_id] = {"step": "set_new"}
                await reply(context, chat_id,
                            f"❌ <b>Паролі не збіглися</b>\n{DIVIDER}\nНадішли новий пароль ще раз.",
                            delay=45)
                return
            set_password(user_id, text)
            state.pop(user_id, None)
            await reply(context, chat_id,
                        f"✅ <b>Пароль встановлено</b>\n{DIVIDER}\n"
                        f"Тепер просто пиши мені — я збережу.\n"
                        f"Щоб переглянути: /show",
                        keyboard=MAIN_KB, keep=True)
            return

        # 2. Зміна пароля
        if step == "ask_old":
            if not check_password(user_id, text):
                left = register_fail(user_id)
                state.pop(user_id, None)
                await reply(context, chat_id, fail_text(left), delay=30)
                return
            reset_fails(user_id)
            state[user_id] = {"step": "set_new"}
            await reply(context, chat_id,
                        f"✅ Пароль підтверджено.\n{DIVIDER}\nНадішли <b>новий</b> пароль.",
                        delay=60)
            return

        # 3. Авторизація для show / clear
        if step in ("auth_show", "auth_clear"):
            state.pop(user_id, None)
            if not check_password(user_id, text):
                left = register_fail(user_id)
                await reply(context, chat_id, fail_text(left), delay=30)
                return
            reset_fails(user_id)
            if step == "auth_show":
                await send_notes(context, chat_id, user_id)
            else:
                removed = clear_notes(user_id)
                await reply(context, chat_id,
                            f"🧹 <b>Сейф очищено</b>\n{DIVIDER}\n"
                            f"Видалено записів: <b>{removed}</b>", delay=25)
            return

    # ─── Немає пароля взагалі → просимо створити ───
    if not get_user(user_id):
        await delete_now(context, chat_id, update.message.message_id)
        state[user_id] = {"step": "set_new"}
        await reply(context, chat_id,
                    f"🔐 <b>Спершу пароль</b>\n{DIVIDER}\n"
                    f"Придумай пароль (мін. {MIN_PASSWORD_LEN} символи) і надішли його.",
                    delay=60)
        return

    # ─── Звичайне повідомлення → в сейф ───
    save_note(user_id, text)
    autodelete(context, chat_id, update.message.message_id)
    msg = await update.message.reply_text(
        f"✅ <b>Збережено</b>  <i>#{count_notes(user_id)}</i>\n"
        f"{DIVIDER}\n"
        f"🕓 {datetime.now().strftime('%H:%M:%S')}\n"
        f"👻 Зникне з чату через {AUTODELETE_SECONDS} сек",
        parse_mode=ParseMode.HTML,
        reply_markup=MAIN_KB,
    )
    autodelete(context, chat_id, msg.message_id)


def fail_text(attempts_left: int) -> str:
    if attempts_left == 0:
        return (f"🚫 <b>Заблоковано на {LOCKOUT_MINUTES} хв</b>\n{DIVIDER}\n"
                f"Вичерпано ліміт спроб.")
    return (f"⛔️ <b>Невірний пароль</b>\n{DIVIDER}\n"
            f"Лишилось спроб: <b>{attempts_left}</b>\nСпробуй ще: /show")


def main() -> None:
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("show", show_cmd))
    app.add_handler(CommandHandler("clear", clear_cmd))
    app.add_handler(CommandHandler("password", password_cmd))
    app.add_handler(CallbackQueryHandler(on_button, pattern="^(show|clear|chpwd)$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Бот запущено ✅")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
