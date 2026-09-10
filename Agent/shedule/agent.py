"""
Бот-навігатор за розкладом та кабінетами.

Команди:
    /start  — підписатися на нагадування (бот запам'ятає ваш chat_id)
    /today  — розклад на сьогодні
    /next   — яка пара зараз/наступна і скільки часу лишилось
    /week   — розклад на весь тиждень (з кнопками по днях)

Розклад лежить у файлі schedule.json поруч зі скриптом.
Ключі "0".."6" — дні тижня: 0 = понеділок, 1 = вівторок, ..., 6 = неділя
(як у Python: datetime.weekday()).

Встановлення залежностей:
    pip install "python-telegram-bot[job-queue]" --upgrade

Запуск:
    python bot.py
"""

import json
import logging
import os
from datetime import datetime, time, timedelta
from pathlib import Path

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Налаштування
# ---------------------------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8883394316:AAE1RLUmqDZmLIT7ncFcjxYN-4UZVfCovYE")

SCHEDULE_FILE = Path(__file__).parent / "schedule.json"
SUBSCRIBERS_FILE = Path(__file__).parent / "subscribers.json"

REMINDER_MINUTES_BEFORE = 6  # за скільки хвилин до пари надсилати нагадування

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

DAY_NAMES = [
    "Понеділок", "Вівторок", "Середа", "Четвер",
    "П'ятниця", "Субота", "Неділя",
]

DAY_SHORT = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Нд"]
DAY_EMOJI = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]

# ---------------------------------------------------------------------------
# Робота з розкладом та підписниками
# ---------------------------------------------------------------------------


def load_schedule() -> dict:
    with open(SCHEDULE_FILE, encoding="utf-8") as f:
        return json.load(f)


def load_subscribers() -> set:
    if not SUBSCRIBERS_FILE.exists():
        return set()
    with open(SUBSCRIBERS_FILE, encoding="utf-8") as f:
        return set(json.load(f))


def save_subscribers(subs: set) -> None:
    with open(SUBSCRIBERS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(subs), f)


def parse_time(t: str) -> time:
    hh, mm = map(int, t.split(":"))
    return time(hour=hh, minute=mm)


def get_day_lessons(schedule: dict, weekday: int) -> list:
    return schedule.get(str(weekday), [])


def format_day_block(day_idx: int, lessons: list, highlight_now: datetime | None = None) -> str:
    """Формує красиво оформлений текстовий блок розкладу на один день (HTML)."""
    header = f"{DAY_EMOJI[day_idx]} <b>{DAY_NAMES[day_idx]}</b>"

    if not lessons:
        return f"{header}\n<i>Пар немає 🎉</i>"

    lines = [header, "▬" * 18]
    current_time = highlight_now.time() if highlight_now else None

    for i, lesson in enumerate(lessons, start=1):
        marker = "▶️ "
        is_current = False
        if current_time is not None:
            start_t = parse_time(lesson["start"])
            end_t = parse_time(lesson["end"])
            is_current = start_t <= current_time <= end_t
        marker = "▶️ " if is_current else f"{i}."

        subject = f"<b>{lesson['subject']}</b>" if is_current else lesson["subject"]
        lines.append(f"{marker} <code>{lesson['start']}–{lesson['end']}</code>  {subject}")
        lines.append(f"     📍 {lesson['room']}")

    return "\n".join(lines)


def format_week_overview(schedule: dict, today_idx: int | None = None) -> str:
    """Компактний огляд усього тижня — по одному рядку на день."""
    lines = ["🗓 <b>Розклад на тиждень</b>", ""]
    for day_idx in range(7):
        lessons = get_day_lessons(schedule, day_idx)
        today_mark = " 👈 сьогодні" if day_idx == today_idx else ""
        if not lessons:
            lines.append(f"{DAY_EMOJI[day_idx]} {DAY_NAMES[day_idx]} — вихідний{today_mark}")
        else:
            first, last = lessons[0]["start"], lessons[-1]["end"]
            lines.append(
                f"{DAY_EMOJI[day_idx]} <b>{DAY_NAMES[day_idx]}</b> — "
                f"{len(lessons)} пар, {first}–{last}{today_mark}"
            )
    lines.append("")
    lines.append("👇 Натисни день, щоб побачити деталі")
    return "\n".join(lines)


def week_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(DAY_SHORT[i], callback_data=f"day:{i}") for i in range(7)
    ]
    # розбиваємо на два ряди по 4/3 кнопки + окрема кнопка "весь тиждень"
    rows = [buttons[:4], buttons[4:], [InlineKeyboardButton("📋 Весь тиждень", callback_data="day:all")]]
    return InlineKeyboardMarkup(rows)


def back_to_week_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Назад до тижня", callback_data="week")]])


# ---------------------------------------------------------------------------
# Хендлери команд
# ---------------------------------------------------------------------------


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    subs = load_subscribers()
    subs.add(chat_id)
    save_subscribers(subs)

    await update.message.reply_text(
        "Привіт! Я бот-навігатор за розкладом. 👋\n\n"
        "Команди:\n"
        "/today — розклад на сьогодні\n"
        "/next — яка пара зараз/наступна\n"
        "/week — розклад на весь тиждень\n\n"
        "Тепер я також надсилатиму тобі нагадування "
        f"за {REMINDER_MINUTES_BEFORE} хв до початку пари."
    )


async def today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    schedule = load_schedule()
    now = datetime.now()
    lessons = get_day_lessons(schedule, now.weekday())

    text = format_day_block(now.weekday(), lessons, highlight_now=now)
    await update.message.reply_text(text, parse_mode=ParseMode.HTML)


async def week(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    schedule = load_schedule()
    now = datetime.now()
    text = format_week_overview(schedule, today_idx=now.weekday())
    await update.message.reply_text(
        text, parse_mode=ParseMode.HTML, reply_markup=week_keyboard()
    )


async def week_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    schedule = load_schedule()
    now = datetime.now()

    if query.data == "week":
        text = format_week_overview(schedule, today_idx=now.weekday())
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=week_keyboard()
        )
        return

    if query.data == "day:all":
        blocks = []
        for day_idx in range(7):
            lessons = get_day_lessons(schedule, day_idx)
            highlight = now if day_idx == now.weekday() else None
            blocks.append(format_day_block(day_idx, lessons, highlight_now=highlight))
        text = "\n\n".join(blocks)
        await query.edit_message_text(
            text, parse_mode=ParseMode.HTML, reply_markup=back_to_week_keyboard()
        )
        return

    # day:0 .. day:6
    day_idx = int(query.data.split(":")[1])
    lessons = get_day_lessons(schedule, day_idx)
    highlight = now if day_idx == now.weekday() else None
    text = format_day_block(day_idx, lessons, highlight_now=highlight)
    await query.edit_message_text(
        text, parse_mode=ParseMode.HTML, reply_markup=back_to_week_keyboard()
    )


async def next_lesson(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    schedule = load_schedule()
    now = datetime.now()
    lessons = get_day_lessons(schedule, now.weekday())
    current_time = now.time()

    if not lessons:
        await update.message.reply_text("Сьогодні пар немає. 🎉")
        return

    # Перевіряємо, чи йде зараз якась пара
    for lesson in lessons:
        start_t = parse_time(lesson["start"])
        end_t = parse_time(lesson["end"])
        if start_t <= current_time <= end_t:
            end_dt = datetime.combine(now.date(), end_t)
            minutes_left = int((end_dt - now).total_seconds() // 60)
            await update.message.reply_text(
                f"▶️ Зараз йде: {lesson['subject']}\n"
                f"📍 {lesson['room']}\n"
                f"⏳ До кінця пари: {minutes_left} хв"
            )
            return

    # Якщо зараз перерва — шукаємо найближчу наступну пару
    for lesson in lessons:
        start_t = parse_time(lesson["start"])
        if start_t > current_time:
            start_dt = datetime.combine(now.date(), start_t)
            minutes_left = int((start_dt - now).total_seconds() // 60)
            await update.message.reply_text(
                f"⏭️ Наступна пара: {lesson['subject']}\n"
                f"📍 {lesson['room']}\n"
                f"⏳ Почнеться через {minutes_left} хв (о {lesson['start']})"
            )
            return

    await update.message.reply_text("На сьогодні пари вже закінчились. 🎉")


# ---------------------------------------------------------------------------
# Фонова задача: нагадування за N хвилин до пари
# ---------------------------------------------------------------------------

# Щоб не надсилати одне й те саме нагадування декілька разів,
# запам'ятовуємо, яким парам сьогодні вже надіслано сповіщення.
_notified_today: set[tuple[str, str]] = set()
_last_reset_date = None


async def check_reminders(context: ContextTypes.DEFAULT_TYPE) -> None:
    global _last_reset_date

    now = datetime.now()

    # Обнуляємо список надісланих сповіщень з настанням нового дня
    if _last_reset_date != now.date():
        _notified_today.clear()
        _last_reset_date = now.date()

    schedule = load_schedule()
    lessons = get_day_lessons(schedule, now.weekday())
    subscribers = load_subscribers()

    if not lessons or not subscribers:
        return

    for lesson in lessons:
        key = (now.date().isoformat(), lesson["start"])
        if key in _notified_today:
            continue

        start_dt = datetime.combine(now.date(), parse_time(lesson["start"]))
        minutes_until = (start_dt - now).total_seconds() / 60

        # Нагадуємо у вікні [0, REMINDER_MINUTES_BEFORE] хвилин до початку
        if 0 <= minutes_until <= REMINDER_MINUTES_BEFORE:
            text = (
                f"🔔 Через {int(minutes_until)} хв починається: {lesson['subject']}\n"
                f"📍 {lesson['room']}"
            )
            for chat_id in subscribers:
                try:
                    await context.bot.send_message(chat_id=chat_id, text=text)
                except Exception as e:
                    logger.warning("Не вдалося надіслати %s: %s", chat_id, e)

            _notified_today.add(key)


# ---------------------------------------------------------------------------
# Запуск бота
# ---------------------------------------------------------------------------

app = Application.builder().token(BOT_TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("today", today))
app.add_handler(CommandHandler("next", next_lesson))
app.add_handler(CommandHandler("week", week))
app.add_handler(CallbackQueryHandler(week_button_handler, pattern=r"^(day:|week$)"))

# Перевіряємо нагадування щохвилини
app.job_queue.run_repeating(check_reminders, interval=60, first=5)

if __name__ == "__main__":
    app.run_polling()
