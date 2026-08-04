"""
Сервіс для всіх викликів AI (Google Gemini API) через звичайний HTTP-запит
(бібліотека requests), без важких залежностей google-genai / google-auth /
cryptography — це важливо для сумісності з Termux на Android.

Документація REST API: https://ai.google.dev/api/generate-content
"""
import time

import requests

from config import GEMINI_API_KEY, AI_MODEL

API_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"

DEFAULT_MAX_TOKENS = 3000
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 4
REQUEST_TIMEOUT_SECONDS = 60


class GeminiAPIError(Exception):
    """Помилка звернення до Gemini API (містить код і повідомлення від сервера)."""


def _call_gemini(contents: list[dict], system_prompt: str, max_tokens: int) -> str:
    """
    Виконує POST-запит до Gemini REST API з повторними спробами при
    тимчасовій перевантаженості моделі (503 UNAVAILABLE) — типова ситуація
    на безкоштовному рівні під час пікового навантаження.
    """
    url = f"{API_BASE_URL}/{AI_MODEL}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }
    payload = {
        "contents": contents,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
        "generationConfig": {
            "maxOutputTokens": max_tokens
        },
    }

    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            resp = requests.post(
                url, headers=headers, json=payload, timeout=REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as e:
            last_error = GeminiAPIError(f"Мережева помилка: {e}")
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS * attempt)
                continue
            raise last_error

        if resp.status_code == 200:
            return _extract_text(resp.json())

        if resp.status_code == 503 and attempt < RETRY_ATTEMPTS:
            last_error = GeminiAPIError(f"503 UNAVAILABLE: {resp.text}")
            time.sleep(RETRY_DELAY_SECONDS * attempt)
            continue

        # Будь-яка інша помилка (400, 401, 404, 429 тощо) — одразу піднімаємо
        raise GeminiAPIError(f"{resp.status_code}: {resp.text}")

    raise last_error


def _extract_text(response_json: dict) -> str:
    """Витягує текст відповіді з JSON, який повертає Gemini API."""
    try:
        candidates = response_json["candidates"]
        parts = candidates[0]["content"]["parts"]
        text_parts = [p.get("text", "") for p in parts if "text" in p]
        return "".join(text_parts).strip()
    except (KeyError, IndexError, TypeError):
        raise GeminiAPIError(f"Неочікувана структура відповіді: {response_json}")


def _ask_gemini(system_prompt: str, user_message: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Базова функція для одноразового звернення до Gemini із заданим системним промптом."""
    contents = [{"role": "user", "parts": [{"text": user_message}]}]
    return _call_gemini(contents, system_prompt, max_tokens)


def answer_question(question: str, history: list[dict] | None = None) -> str:
    """Відповідає на довільне запитання користувача, підтримуючи контекст діалогу."""
    system_prompt = (
        "Ти — дружній AI-помічник для навчання у Telegram-боті. "
        "Відповідай українською мовою, чітко і по суті, без зайвої води. "
        "Якщо питання складне — структуруй відповідь пунктами. "
        "Використовуй прості приклади там, де це допомагає зрозуміти тему."
    )

    # Конвертуємо збережену історію (role: user/assistant) у формат Gemini (user/model)
    contents = []
    for msg in (history or []):
        role = "model" if msg["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    contents.append({"role": "user", "parts": [{"text": question}]})

    return _call_gemini(contents, system_prompt, DEFAULT_MAX_TOKENS)


def explain_topic(topic: str) -> str:
    """Пояснює складну тему простими словами."""
    system_prompt = (
        "Ти — терплячий викладач. Поясни задану тему максимально простою мовою, "
        "ніби пояснюєш людині без попередніх знань з предмету. "
        "Використай аналогію або приклад з життя. Відповідай українською. "
        "Структура: 1) проста суть в 1-2 реченнях, 2) детальніше пояснення, "
        "3) приклад, 4) коротке резюме."
    )
    return _ask_gemini(system_prompt, f"Поясни тему: {topic}")


def make_summary(text: str) -> str:
    """Створює структурований конспект із наданого тексту."""
    system_prompt = (
        "Ти створюєш стислі, добре структуровані конспекти українською мовою. "
        "Виділи ключові тези, визначення та важливі факти. "
        "Використовуй заголовки та марковані списки. Уникай зайвих деталей."
    )
    return _ask_gemini(system_prompt, f"Зроби конспект цього тексту:\n\n{text}", max_tokens=3000)


def generate_quiz(topic_or_text: str, num_questions: int = 5) -> str:
    """Генерує тестові завдання з варіантами відповідей за темою або текстом."""
    system_prompt = (
        "Ти створюєш навчальні тести українською мовою. "
        f"Створи рівно {num_questions} тестових питань з 4 варіантами відповідей "
        "(A, B, C, D) кожне. Після всіх питань додай розділ 'Правильні відповіді' "
        "з переліком у форматі '1 - B'. Питання мають перевіряти розуміння, "
        "а не просто запам'ятовування."
    )
    return _ask_gemini(
        system_prompt,
        f"Створи тест за цією темою або текстом:\n\n{topic_or_text}",
        max_tokens=3000,
    )


def answer_about_document(document_text: str, question: str) -> str:
    """Відповідає на питання користувача щодо змісту завантаженого документа."""
    system_prompt = (
        "Ти відповідаєш на питання виключно на основі наданого тексту документа. "
        "Якщо відповіді в тексті немає — чесно скажи про це. Відповідай українською."
    )
    user_message = (
        f"Текст документа:\n\n{document_text}\n\n---\n\nПитання: {question}"
    )
    return _ask_gemini(system_prompt, user_message, max_tokens=2500)


def analyze_products(query: str, collected_data: str) -> str:
    """
    Аналізує зібрані з вебу дані про товари (назви, ціни, посилання, характеристики)
    та формує єдину зрозумілу рекомендацію користувачу.
    """
    system_prompt = (
        "Ти — асистент з покупок. Тобі надано сирі дані, зібрані з вебсторінок "
        "за запитом користувача (назви товарів, ціни, посилання, уривки описів). "
        "Проаналізуй їх та дай користувачу ОДНЕ чітке структуроване повідомлення українською:\n"
        "1) Короткий підсумок знайдених варіантів (назва, ціна, магазин/джерело).\n"
        "2) Порівняння за ціною та ключовими характеристиками, якщо вони відомі.\n"
        "3) Конкретна рекомендація — який варіант обрати і чому.\n"
        "4) Якщо дані неповні або суперечливі — чесно зазнач це.\n"
        "Не вигадуй ціни чи характеристики, яких немає у наданих даних."
    )
    user_message = (
        f"Запит користувача: {query}\n\n"
        f"Зібрані дані з вебсторінок:\n\n{collected_data}"
    )
    return _ask_gemini(system_prompt, user_message, max_tokens=3000)
