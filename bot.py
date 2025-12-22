"""Telegram Bot - Data Visualization with Gemini"""
from telegram import BotCommand, MenuButtonCommands, Update
from telegram.ext import Application

from config import TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, GEMINI_MODEL, UPLOAD_DIR, WEB_SERVER_PORT, RAILWAY_PUBLIC_URL
from core import session_manager
from services import start_server, get_public_url
from handlers import setup_handlers


async def post_init(app: Application):
    """Set up bot commands"""
    commands = [
        BotCommand("start", "🚀 Start bot & see current status"),
        BotCommand("datasets", "📂 View all uploaded CSV files"),
        BotCommand("preview", "👀 Preview data inside your CSV"),
        BotCommand("clear", "🗑️ Delete all data & start fresh"),
        BotCommand("help", "❓ How to use this bot"),
    ]
    await app.bot.set_my_commands(commands)
    await app.bot.set_chat_menu_button(menu_button=MenuButtonCommands())


def main():
    # Startup banner
    print("\n" + "="*50)
    print("  DATA VISUALIZATION BOT")
    print("="*50)
    
    # Check credentials
    if not TELEGRAM_BOT_TOKEN:
        print("❌ TELEGRAM_BOT_TOKEN not set")
        return
    if not GEMINI_API_KEY:
        print("❌ GEMINI_API_KEY not set")
        return
    
    print(f"✓ Telegram token: ...{TELEGRAM_BOT_TOKEN[-8:]}")
    print(f"✓ Gemini API: ...{GEMINI_API_KEY[-8:]}")
    print(f"✓ Model: {GEMINI_MODEL}")
    
    # Start web server
    print("\n[Web Server]")
    if start_server(session_manager, WEB_SERVER_PORT, RAILWAY_PUBLIC_URL or None):
        print(f"✓ Public URL: {get_public_url()}")
    else:
        print("✗ Web server failed - interactive charts disabled")
    
    # Build bot
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    app.bot_data['gemini_api_key'] = GEMINI_API_KEY
    app.bot_data['gemini_model'] = GEMINI_MODEL
    app.bot_data['upload_dir'] = UPLOAD_DIR
    setup_handlers(app)
    
    print("\n[Bot]")
    print("✓ Handlers registered")
    print("✓ Bot running - Ctrl+C to stop")
    print("="*50 + "\n")
    
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
