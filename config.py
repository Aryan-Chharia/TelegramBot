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
for noisy in ['httpx', 'httpcore', 'urllib3',
              'werkzeug', 'google', 'telegram', 'asyncio']:
    logging.getLogger(noisy).setLevel(logging.CRITICAL)

# App logger - INFO level for our code only
app_logger = logging.getLogger('bot')
app_logger.setLevel(logging.INFO)


# API Keys
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3-flash-preview"

# Web Server
WEB_SERVER_PORT = int(os.getenv("PORT", os.getenv("WEB_SERVER_PORT", "5050")))  # Railway uses PORT


def _running_on_railway() -> bool:
    # Railway typically sets multiple RAILWAY_* vars in the runtime. We gate on those
    # so a locally-stored RAILWAY_PUBLIC_DOMAIN in .env doesn't break local mode.
    return any(
        os.getenv(k)
        for k in (
            "RAILWAY_PROJECT_ID",
            "RAILWAY_SERVICE_ID",
            "RAILWAY_ENVIRONMENT_ID",
            "RAILWAY_ENVIRONMENT_NAME",
            "RAILWAY_REPLICA_ID",
        )
    )


_explicit_public = (
    os.getenv("PUBLIC_URL")
    or os.getenv("RAILWAY_PUBLIC_DOMAIN")
    or os.getenv("RAILWAY_STATIC_URL")
)

# If an explicit public URL is provided, prefer it. Otherwise fall back to Railway-only detection.
if _explicit_public:
    RAILWAY_PUBLIC_URL = _explicit_public
else:
    _railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "")  # Auto-set by Railway
    RAILWAY_PUBLIC_URL = _railway_domain if (_railway_domain and _running_on_railway()) else ""

# Paths
UPLOAD_DIR = "uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)
