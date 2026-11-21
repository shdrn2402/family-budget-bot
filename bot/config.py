import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    TELEGRAM_TOKEN: str | None = os.getenv("TELEGRAM_TOKEN")
    
    # Telegram IDs allowed to use the bot (users not yet in the `users` table are registered on first use).
    _allowed_users: str = os.getenv("ALLOWED_USER_IDS", "")
    ALLOWED_USER_IDS: list[int] = [int(uid.strip()) for uid in _allowed_users.split(",") if uid.strip()]

    # Database connection parameters
    DB_NAME: str | None = os.getenv("DB_NAME")
    DB_USER: str | None = os.getenv("DB_USER")
    DB_PASSWORD: str | None = os.getenv("DB_PASSWORD")
    DB_HOST: str = os.getenv("DB_HOST", "localhost")
    DB_PORT: str = os.getenv("DB_PORT", "5432")

    # Timezone Configuration
    BOT_TIMEZONE: str = os.getenv("BOT_TIMEZONE", "UTC")

