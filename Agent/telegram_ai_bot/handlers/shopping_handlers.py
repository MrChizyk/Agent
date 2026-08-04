"""
Обробники команд шопінг-модуля: /find, /track, /mytracked, /untrack.
"""
import logging

from telegram import Update
from telegram.ext import ContextTypes

from services.web_service import collect_product_data, search_products, fetch_page_summary
from services.ai_service import analyze_products
from database import add_tracked_item, get_tracked_items, delete_tracked_item
from utils import send_ai_text, format_ai_error

logger = logging.getLogger(__name__)


async def find_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Напиши, що шукати, наприклад:\n/find бездротові навушники до 2000 грн"
        )
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"🔎 Шукаю варіанти для «{query}»...")
    await update.message.chat.send_action(action="typing")

    try:
        collected_text, _ = collect_product_data(query, max_results=5)
    except Exception as e:
        logger.exception("Помилка пошуку товарів")
        await update.message.reply_text(
            f"⚠️ Не вдалося виконати пошук (можливо, тимчасове обмеження від "
            f"пошукової системи). Спробуй ще раз через хвилину.\n\nДеталі: {e}"
        )
        return

    if collected_text == "Дані не знайдено.":
        await update.message.reply_text(
            "На жаль, не вдалося зібрати дані по цьому запиту. Спробуй сформулювати інакше."
        )
        return

    try:
        result = analyze_products(query, collected_text)
    except Exception as e:
        logger.exception("Помилка AI-аналізу товарів")
        await update.message.reply_text(format_ai_error(e))
        return

    await send_ai_text(update.message, result)


async def track_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text(
            "Напиши, який товар відстежувати, наприклад:\n/track iPhone 15 128GB"
        )
        return

    query = " ".join(context.args)
    await update.message.reply_text(f"🔎 Шукаю «{query}» для відстеження...")
    await update.message.chat.send_action(action="typing")

    try:
        results = search_products(query, max_results=1)
    except Exception as e:
        logger.exception("Помилка пошуку товару для відстеження")
        await update.message.reply_text(
            f"⚠️ Не вдалося виконати пошук (можливо, тимчасове обмеження від "
            f"пошукової системи). Спробуй ще раз через хвилину.\n\nДеталі: {e}"
        )
        return

    if not results:
        await update.message.reply_text("Нічого не знайдено за цим запитом.")
        return

    top_result = results[0]
    summary = fetch_page_summary(top_result["url"])

    if "error" in summary or not summary.get("prices"):
        await update.message.reply_text(
            "Знайшов сторінку, але не зміг розпізнати на ній ціну. "
            "Спробуй уточнити назву товару."
        )
        return

    price = summary["prices"][0]
    add_tracked_item(
        chat_id=update.effective_chat.id,
        query=query,
        url=summary["url"],
        title=summary["title"],
        price=price,
    )

    await update.message.reply_text(
        f"✅ Додано до відстеження!\n\n"
        f"Товар: {summary['title']}\n"
        f"Поточна ціна: {price}\n"
        f"🔗 {summary['url']}\n\n"
        f"Я перевірятиму ціну регулярно і повідомлю про зміну."
    )


async def mytracked_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    items = get_tracked_items(update.effective_chat.id)
    if not items:
        await update.message.reply_text(
            "Ти ще не відстежуєш жодного товару. Додай через /track <назва товару>."
        )
        return

    lines = ["📋 Твої відстежувані товари:\n"]
    for item in items:
        lines.append(
            f"ID {item['id']}: {item['title']}\n"
            f"Ціна: {item['last_price']}\n"
            f"🔗 {item['url']}\n"
        )
    lines.append("Щоб прибрати товар, напиши /untrack <ID>")
    await update.message.reply_text("\n".join(lines))


async def untrack_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Напиши ID товару, наприклад:\n/untrack 3")
        return

    item_id = int(context.args[0])
    deleted = delete_tracked_item(item_id, update.effective_chat.id)

    if deleted:
        await update.message.reply_text("✅ Товар прибрано з відстеження.")
    else:
        await update.message.reply_text(
            "Не знайшов товар з таким ID у твоєму списку. Перевір /mytracked."
        )
