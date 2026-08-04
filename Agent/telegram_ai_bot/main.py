"""
Точка входу бота. Реєструє всі обробники команд та повідомлень,
запускає планувальник перевірки цін і стартує polling.

Запуск: python main.py
"""
import logging
import asyncio

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import TELEGRAM_BOT_TOKEN, PRICE_CHECK_INTERVAL_HOURS
from database import init_db
from services.tracker_service import check_all_prices

from handlers.common import start_command, help_command, handle_text_message
from handlers.ai_handlers import explain_command, summary_command, quiz_command
from handlers.document_handlers import handle_document_upload, handle_document_menu_callback
from handlers.shopping_handlers import (
    find_command,
    track_command,
    mytracked_command,
    untrack_command,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


async def post_init(application: Application):
    """Запускається один раз після ініціалізації бота: старт планувальника цін."""
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        check_all_prices,
        "interval",
        hours=PRICE_CHECK_INTERVAL_HOURS,
        args=[application.bot],
    )
    scheduler.start()
    logger.info(
        "Планувальник перевірки цін запущено (кожні %s год.)",
        PRICE_CHECK_INTERVAL_HOURS,
    )


def main():
    # Python 3.13+/3.14 більше не створює event loop автоматично,
    # тому робимо це вручну для сумісності з python-telegram-bot.
    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    init_db()

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Базові команди
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))

    # Навчальні AI-команди
    application.add_handler(CommandHandler("explain", explain_command))
    application.add_handler(CommandHandler("summary", summary_command))
    application.add_handler(CommandHandler("quiz", quiz_command))

    # Робота з документами
    application.add_handler(MessageHandler(filters.Document.ALL, handle_document_upload))
    application.add_handler(
        CallbackQueryHandler(handle_document_menu_callback, pattern="^doc_")
    )

    # Модуль пошуку та відстеження товарів
    application.add_handler(CommandHandler("find", find_command))
    application.add_handler(CommandHandler("track", track_command))
    application.add_handler(CommandHandler("mytracked", mytracked_command))
    application.add_handler(CommandHandler("untrack", untrack_command))

    # Довільний текст — як питання до AI (реєструємо останнім)
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message)
    )

    logger.info("Бот запускається...")
    # УВАГА: run_polling() сам керує event loop. Не обгортайте цей виклик
    # у asyncio.run() — це спричинить RuntimeError: event loop is already running.
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
