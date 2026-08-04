"""
Конфігурація бота: завантаження змінних оточення та базові константи.
"""
import os
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Модель Gemini, яку використовує бот для всіх AI-запитів.
# "gemini-3.6-flash" - актуальна стабільна модель (баланс якості й швидкості).
# Якщо потрібні вищі безкоштовні ліміти запитів на день - можна
# перемкнутись на "gemini-3.5-flash-lite".
AI_MODEL = "gemini-3.6-flash"

# Шлях до файлу бази даних SQLite (відстеження цін)
DATABASE_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")

# Максимальна довжина тексту документа, що передається в AI за один раз
MAX_DOCUMENT_CHARS = 15000

# Як часто (у годинах) перевіряти ціни відстежуваних товарів
PRICE_CHECK_INTERVAL_HOURS = 6

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError(
        "TELEGRAM_BOT_TOKEN не знайдено. Скопіюйте .env.example у .env "
        "та вкажіть токен, отриманий від @BotFather."
    )

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY не знайдено. Скопіюйте .env.example у .env "
        "та вкажіть ваш безкоштовний ключ, отриманий на "
        "https://aistudio.google.com/apikey"
    )
