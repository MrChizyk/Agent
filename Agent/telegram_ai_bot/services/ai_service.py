"""
Сервіс для всіх викликів AI (Google Gemini API, новий unified SDK
google-genai): відповіді на питання, пояснення, конспекти, тести
та аналіз зібраних з вебу даних про товари.
"""
import time

from google import genai
from google.genai import types
from google.genai.errors import ServerError

from config import GEMINI_API_KEY, AI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)

DEFAULT_MAX_TOKENS = 3000
RETRY_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 4


def _generate_with_retry(**kwargs):
    """
    Виконує звернення до Gemini з повторними спробами при тимчасовій
    перевантаженості моделі (503 UNAVAILABLE) — типова ситуація на
    безкоштовному рівні під час пікового навантаження.
    """
    last_error = None
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            return client.models.generate_content(**kwargs)
        except ServerError as e:
            last_error = e
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY_SECONDS * attempt)
            else:
                raise
    raise last_error


def _ask_gemini(system_prompt: str, user_message: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> str:
    """Базова функція для звернення до Gemini із заданим системним промптом."""
    response = _generate_with_retry(
        model=AI_MODEL,
        contents=user_message,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=max_tokens,
            # Для наших задач глибокі "роздуми" моделі не потрібні, а вони
            # з'їдають частину ліміту токенів і обрізають фактичну відповідь.
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )
    return (response.text or "").strip()


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
        contents.append(types.Content(role=role, parts=[types.Part(text=msg["content"])]))
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))

    response = _generate_with_retry(
        model=AI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system_prompt,
            max_output_tokens=DEFAULT_MAX_TOKENS,
            thinking_config=types.ThinkingConfig(thinking_level="low"),
        ),
    )
    return (response.text or "").strip()


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
