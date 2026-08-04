"""
Обробники команд навчального AI-модуля: /explain, /summary, /quiz.
"""
import os

from telegram import Update
from telegram.ext import ContextTypes

from services.ai_service import explain_topic, make_summary, generate_quiz
from services.pdf_service import create_pdf
from utils import send_ai_text, format_ai_error


async def explain_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Напиши тему після команди, наприклад:\n/explain квантова заплутаність"
        )
        return

    topic = " ".join(context.args)
    await update.message.chat.send_action(action="typing")
    result = explain_topic(topic)
    await send_ai_text(update.message, result)


async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Надішли текст після команди /summary, або просто надішли PDF/DOCX файл — "
            "я сам зроблю конспект."
        )
        return

    text = " ".join(context.args)
    await update.message.chat.send_action(action="typing")

    try:
        result = make_summary(text)
    except Exception as e:
        await update.message.reply_text(format_ai_error(e))
        return

    await _send_as_pdf(update.message, "Конспект", result, "konspekt.pdf")


async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Напиши тему після команди, наприклад:\n/quiz Друга світова війна"
        )
        return

    topic = " ".join(context.args)
    await update.message.chat.send_action(action="typing")

    try:
        result = generate_quiz(topic)
    except Exception as e:
        await update.message.reply_text(format_ai_error(e))
        return

    await _send_as_pdf(update.message, f"Тест: {topic}", result, "test.pdf")


async def _send_as_pdf(message, title: str, content: str, filename: str):
    """Генерує PDF з тексту AI і надсилає його як документ у чат."""
    pdf_path = create_pdf(title, content)
    try:
        with open(pdf_path, "rb") as f:
            await message.reply_document(document=f, filename=filename)
    finally:
        os.remove(pdf_path)
