"""
Базові команди бота (/start, /help) та обробка звичайних текстових
повідомлень як питань до AI-помічника.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.ai_service import answer_question, answer_about_document
from utils import send_ai_text, format_ai_error

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 10  # скільки останніх повідомлень зберігати для контексту

WELCOME_TEXT = (
    "👋 Привіт! Я твій AI-помічник для навчання та пошуку інформації.\n\n"
    "📚 *Навчання:*\n"
    "• Просто напиши питання — відповім\n"
    "• /explain <тема> — поясню складну тему простими словами\n"
    "• /summary <текст> — зроблю конспект (або надішли PDF/DOCX)\n"
    "• /quiz <тема> — згенерую тестові завдання\n"
    "• Надішли файл PDF або DOCX — проаналізую документ\n\n"
    "🛒 *Пошук товарів:*\n"
    "• /find <товар> — знайду та порівняю варіанти в інтернеті\n"
    "• /track <товар> — відстежуватиму зміну ціни\n"
    "• /mytracked — список товарів, які я відстежую\n"
    "• /untrack <id> — прибрати товар з відстеження\n\n"
    "Напиши /help, щоб побачити цей список ще раз."
)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(WELCOME_TEXT, parse_mode="Markdown")


async def handle_text_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробляє довільний текст як питання до AI, підтримуючи короткий контекст діалогу."""
    question = update.message.text

    # Якщо користувач у режимі "питання по документу" — відповідаємо на основі його тексту
    if context.user_data.get("doc_qa_mode") and context.user_data.get("document_text"):
        await update.message.chat.send_action(action="typing")
        try:
            answer = answer_about_document(context.user_data["document_text"], question)
        except Exception as e:
            logger.exception("Помилка при відповіді по документу")
            await update.message.reply_text(format_ai_error(e))
            return
        await send_ai_text(update.message, answer)
        return

    history = context.user_data.get("chat_history", [])

    await update.message.chat.send_action(action="typing")
    try:
        answer = answer_question(question, history=history)
    except Exception as e:
        logger.exception("Помилка при відповіді на питання")
        await update.message.reply_text(format_ai_error(e))
        return

    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer})
    context.user_data["chat_history"] = history[-MAX_HISTORY_MESSAGES:]

    await send_ai_text(update.message, answer)
