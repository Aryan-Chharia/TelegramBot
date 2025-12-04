"""Configuration"""
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# =============================================================================
# Logging - Suppress noisy libraries, show only critical app logs
# =============================================================================
logging.basicConfig(
    level=logging.WARNING,  # Default to WARNING for all
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S"
)

# Suppress noisy loggers completely
for noisy in ['httpx', 'httpcore', 'urllib3', 'pyngrok', 'ngrok', 
              'werkzeug', 'google', 'telegram', 'asyncio']:
    logging.getLogger(noisy).setLevel(logging.CRITICAL)

# App logger - INFO level for our code only
app_logger = logging.getLogger('bot')
app_logger.setLevel(logging.INFO)


# API Keys
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-2.5-pro"

# Web Server
WEB_SERVER_PORT = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", "5050")))  # Railway uses PORT
NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")
RAILWAY_PUBLIC_URL = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")  # Auto-set by Railway

# Paths
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
