"""
Допоміжні функції для форматування та безпечного надсилання повідомлень
у Telegram: AI повертає текст у "звичайному" Markdown (**жирний**, ### заголовок,
* пункт списку), а ми конвертуємо це у HTML, який Telegram парсить набагато
стійкіше до "кривих" символів (одинарні зірочки, недомальовані пари тощо).
"""
import html
import re

from telegram import Message


def format_ai_error(e: Exception) -> str:
    """Формує зрозуміле користувачу повідомлення про помилку звернення до AI."""
    error_text = str(e)
    if "UNAVAILABLE" in error_text or "503" in error_text:
        return (
            "⚠️ Сервери Google Gemini зараз тимчасово перевантажені "
            "(це трапляється на безкоштовному рівні). Я вже спробував кілька разів — "
            "спробуй, будь ласка, ще раз через хвилину."
        )
    if "RESOURCE_EXHAUSTED" in error_text or "429" in error_text:
        return (
            "⚠️ Вичерпано денний/хвилинний ліміт безкоштовних запитів до Gemini API. "
            "Спробуй трохи пізніше."
        )
    return f"⚠️ Помилка звернення до AI: {e}"


def to_telegram_html(text: str) -> str:
    """Конвертує типовий Markdown від AI у HTML-розмітку, яку розуміє Telegram."""
    # Спершу екрануємо HTML-спецсимволи, щоб текст не зламав розмітку
    escaped = html.escape(text, quote=False)

    lines = escaped.split("\n")
    processed_lines = []
    for line in lines:
        header_match = re.match(r"^(#{1,6})\s*(.+)$", line)
        if header_match:
            processed_lines.append(f"<b>{header_match.group(2)}</b>")
            continue

        # Пункти списку "* текст" або "- текст" -> "• текст"
        line = re.sub(r"^(\s*)[*\-]\s+", r"\1• ", line)
        processed_lines.append(line)

    result = "\n".join(processed_lines)

    # **жирний** -> <b>жирний</b>
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)

    return result


async def send_ai_text(message: Message, text: str):
    """
    Надсилає текст від AI із застосуванням HTML-форматування Telegram.
    Якщо з якоїсь причини форматування все ж ламає парсинг —
    безпечно повертається до звичайного тексту без розмітки.
    """
    formatted = to_telegram_html(text)
    try:
        await message.reply_text(formatted, parse_mode="HTML")
    except Exception:
        # Прибираємо розмітку повністю, щоб хоч сирий текст дійшов до користувача
        plain = re.sub(r"<.*?>", "", formatted)
        await message.reply_text(plain)
