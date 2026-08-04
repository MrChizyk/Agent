"""
Обробка завантажених документів (PDF, DOCX): витягування тексту та
інтерактивне меню дій — конспект, тест або відповіді на питання по документу.
"""
import os
import tempfile

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from services.document_service import extract_text_from_pdf, extract_text_from_docx
from services.ai_service import make_summary, generate_quiz, answer_about_document
from services.pdf_service import create_pdf
from utils import send_ai_text

DOC_MENU_KEYBOARD = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("📝 Зробити конспект", callback_data="doc_summary")],
        [InlineKeyboardButton("❓ Згенерувати тест", callback_data="doc_quiz")],
        [InlineKeyboardButton("💬 Задати питання по документу", callback_data="doc_ask")],
    ]
)


async def handle_document_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    file_name = document.file_name or ""
    ext = os.path.splitext(file_name)[1].lower()

    if ext not in (".pdf", ".docx"):
        await update.message.reply_text(
            "Наразі я вмію аналізувати лише файли форматів PDF та DOCX."
        )
        return

    await update.message.chat.send_action(action="typing")
    tg_file = await document.get_file()

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        tmp_path = tmp.name
    await tg_file.download_to_drive(tmp_path)

    try:
        if ext == ".pdf":
            text = extract_text_from_pdf(tmp_path)
        else:
            text = extract_text_from_docx(tmp_path)
    finally:
        os.remove(tmp_path)

    if not text.strip():
        await update.message.reply_text(
            "Не вдалося витягти текст з документа. Можливо, це скановане "
            "зображення без текстового шару."
        )
        return

    context.user_data["document_text"] = text
    context.user_data["document_name"] = file_name
    context.user_data["doc_qa_mode"] = False

    await update.message.reply_text(
        f"✅ Документ «{file_name}» оброблено. Що зробити далі?",
        reply_markup=DOC_MENU_KEYBOARD,
    )


async def handle_document_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    document_text = context.user_data.get("document_text")
    if not document_text:
        await query.edit_message_text(
            "Текст документа більше не доступний. Надішли файл ще раз, будь ласка."
        )
        return

    action = query.data
    doc_name = context.user_data.get("document_name", "документ")

    if action == "doc_summary":
        await query.edit_message_text("⏳ Роблю конспект...")
        result = make_summary(document_text)
        pdf_path = create_pdf(f"Конспект: {doc_name}", result)
        try:
            with open(pdf_path, "rb") as f:
                await query.message.reply_document(document=f, filename="konspekt.pdf")
        finally:
            os.remove(pdf_path)

    elif action == "doc_quiz":
        await query.edit_message_text("⏳ Генерую тест...")
        result = generate_quiz(document_text)
        pdf_path = create_pdf(f"Тест: {doc_name}", result)
        try:
            with open(pdf_path, "rb") as f:
                await query.message.reply_document(document=f, filename="test.pdf")
        finally:
            os.remove(pdf_path)

    elif action == "doc_ask":
        context.user_data["doc_qa_mode"] = True
        await query.edit_message_text(
            "💬 Добре, постав своє питання по документу звичайним повідомленням. "
            "Щоб вийти з цього режиму, надішли /start."
        )
