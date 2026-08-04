"""
Сервіс збору інформації з вебсайтів: пошук товарів та витягування цін
та коротких описів зі сторінок для подальшого AI-аналізу.
"""
import logging
import re
import time

import requests
from bs4 import BeautifulSoup
from ddgs import DDGS
from ddgs.exceptions import DDGSException, RatelimitException

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

# Регулярний вираз для пошуку цінових шаблонів (грн, $, €,₴ тощо)
PRICE_PATTERN = re.compile(
    r"(?:₴|грн|\$|USD|€|EUR)\s?\d[\d\s.,]{1,10}|\d[\d\s.,]{1,10}\s?(?:₴|грн|\$|USD|€|EUR)",
    re.IGNORECASE,
)


def search_products(query: str, max_results: int = 5) -> list[dict]:
    """Шукає товари в інтернеті за запитом і повертає список посилань з заголовками."""
    results = []
    attempts = 3

    for attempt in range(1, attempts + 1):
        try:
            with DDGS() as ddgs:
                for r in ddgs.text(f"{query} купити ціна", max_results=max_results):
                    results.append(
                        {
                            "title": r.get("title", ""),
                            "url": r.get("href", ""),
                            "snippet": r.get("body", ""),
                        }
                    )
            return results
        except RatelimitException:
            logger.warning("DuckDuckGo rate-limit, спроба %s з %s", attempt, attempts)
            if attempt < attempts:
                time.sleep(3 * attempt)
            else:
                raise
        except DDGSException as e:
            logger.warning("Помилка пошуку DuckDuckGo: %s", e)
            raise

    return results


def fetch_page_summary(url: str, timeout: int = 8) -> dict:
    """
    Завантажує сторінку товару та витягує заголовок, знайдені ціни
    і невеликий фрагмент тексту для AI-аналізу.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        return {"url": url, "error": str(e)}

    soup = BeautifulSoup(resp.text, "html.parser")

    title_tag = soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else url

    page_text = soup.get_text(separator=" ", strip=True)
    prices_found = list(dict.fromkeys(PRICE_PATTERN.findall(page_text)))[:5]

    # Беремо короткий уривок тексту навколо початку сторінки для контексту
    snippet = page_text[:600]

    return {
        "url": url,
        "title": title,
        "prices": prices_found,
        "snippet": snippet,
    }


def collect_product_data(query: str, max_results: int = 5) -> tuple[str, list[dict]]:
    """
    Повний цикл: шукає товари, відвідує знайдені сторінки та формує
    текстовий блок даних, готовий для передачі в AI-аналіз.
    """
    search_results = search_products(query, max_results=max_results)
    page_summaries = []
    data_blocks = []

    for item in search_results:
        summary = fetch_page_summary(item["url"])
        if "error" in summary:
            continue
        page_summaries.append(summary)
        prices_str = ", ".join(summary["prices"]) if summary["prices"] else "не знайдено"
        data_blocks.append(
            f"Джерело: {summary['title']}\n"
            f"Посилання: {summary['url']}\n"
            f"Знайдені ціни: {prices_str}\n"
            f"Фрагмент сторінки: {summary['snippet']}\n"
        )

    collected_text = "\n---\n".join(data_blocks) if data_blocks else "Дані не знайдено."
    return collected_text, page_summaries
