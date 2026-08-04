"""
Логіка періодичної перевірки цін відстежуваних товарів та
формування повідомлень для користувачів у разі зміни ціни.
"""
import logging

from database import get_all_tracked_items, update_tracked_price
from services.web_service import fetch_page_summary

logger = logging.getLogger(__name__)


async def check_all_prices(bot):
    """
    Проходить по всіх відстежуваних товарах, перевіряє поточну ціну
    і надсилає користувачу повідомлення, якщо ціна змінилась.
    """
    items = get_all_tracked_items()
    for item in items:
        summary = fetch_page_summary(item["url"])
        if "error" in summary or not summary.get("prices"):
            continue

        new_price = summary["prices"][0]
        old_price = item["last_price"]

        if new_price != old_price:
            update_tracked_price(item["id"], new_price)
            try:
                await bot.send_message(
                    chat_id=item["chat_id"],
                    text=(
                        f"💰 Зміна ціни для «{item['title']}»!\n\n"
                        f"Було: {old_price}\n"
                        f"Стало: {new_price}\n\n"
                        f"🔗 {item['url']}"
                    ),
                )
            except Exception as e:
                logger.warning("Не вдалося надіслати повідомлення %s: %s", item["chat_id"], e)
