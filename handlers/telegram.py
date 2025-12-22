"""Telegram bot handlers"""
import os
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from core import session_manager, process_dataset, validate_file, generate_chart
from services import generate_code, generate_insights, get_chart_url, get_preview_url


def _chart_actions_keyboard(chart_id: str, include_insights: bool = True) -> InlineKeyboardMarkup:
    """Single-column layout to make buttons as wide as Telegram allows."""
    url = get_chart_url(chart_id)
    rows = []
    if url:
        rows.append([InlineKeyboardButton("🔍 Open Interactive Chart", web_app=WebAppInfo(url=url))])
    if include_insights:
        rows.append([InlineKeyboardButton("📌 Generate Insights (5)", callback_data=f"insights:{chart_id}")])
    return InlineKeyboardMarkup(rows)


def _limit_insights_to_5(text: str) -> str:
    """Enforce a hard cap of 5 bullets even if the model returns more."""
    if not text:
        return text
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    bullets = [ln for ln in lines if ln.lstrip().startswith('-')]
    if bullets:
        return "\n".join(bullets[:5])
    # Fallback: just cap to 5 non-empty lines
    return "\n".join(lines[:5])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /start"""
    datasets = session_manager.get_all_datasets()
    ds_info = f"📁 Your datasets ({len(datasets)}/5): {', '.join(datasets.keys())}" if datasets else "📁 No datasets uploaded yet"
    
    await update.message.reply_text(f"""🤖 **Welcome to Data Visualization Bot!**

I turn your CSV data into beautiful interactive charts using AI.

{ds_info}

**Getting Started:**
1️⃣ Send me a CSV file
2️⃣ Describe what chart you want
   Example: "Show sales by region as a bar chart"
3️⃣ Get your visualization instantly!

**Commands:** /help for full guide""", parse_mode='Markdown')


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /help"""
    await update.message.reply_text("""📚 **How to Use This Bot**

**Step 1: Upload Your Data**
Send a CSV file (spreadsheet data). You can upload up to 5 files.

**Step 2: Request a Visualization**
Just describe what you want in plain English:
• "Bar chart of sales by region"
• "Compare revenue vs expenses over time"
• "Pie chart showing category distribution"
• "Scatter plot of price vs quantity"

**Step 3: Interact**
Tap "Interactive" button to zoom, pan, and explore your chart!

**Commands:**
/start - Check bot status & your datasets
/datasets - See details of uploaded files
/preview - View the actual data in your CSV
/clear - Remove all files & start over
/help - Show this guide

**Tips:**
💡 Be specific with column names for best results
💡 You can ask follow-up questions to refine charts
💡 Upload multiple CSVs to compare different datasets""", parse_mode='Markdown')


async def cmd_datasets(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /datasets"""
    datasets = session_manager.get_all_datasets()
    
    if not datasets:
        await update.message.reply_text("📂 **No Datasets Yet**\n\nSend me a CSV file to get started!")
        return
    
    msg = f"📂 **Your Uploaded Datasets ({len(datasets)}/5):**\n\n"
    for name, info in datasets.items():
        cols = ', '.join(info.columns[:4])
        if len(info.columns) > 4:
            cols += f" (+{len(info.columns)-4} more)"
        msg += f"📊 **{name}**\n   Rows: {info.row_count} | Columns: {info.col_count}\n   Fields: {cols}\n\n"
    
    msg += "💡 _Use /preview to see the actual data inside_"
    await update.message.reply_text(msg, parse_mode='Markdown')


async def cmd_preview(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /preview - Show dataset selection buttons"""
    datasets = session_manager.get_all_datasets()
    
    if not datasets:
        await update.message.reply_text("📂 **No Datasets Yet**\n\nUpload a CSV file first, then use /preview to see its contents!")
        return
    
    # Build buttons for each dataset
    buttons = []
    for name, info in datasets.items():
        preview_url = get_preview_url(name)
        if preview_url:
            buttons.append([
                InlineKeyboardButton(
                    f"📊 {name} ({info.row_count} rows)",
                    web_app=WebAppInfo(url=preview_url)
                )
            ])
    
    if not buttons:
        await update.message.reply_text("❌ Preview unavailable - web server not running")
        return
    
    keyboard = InlineKeyboardMarkup(buttons)
    await update.message.reply_text("👀 **Preview Your Data**\n\nTap a dataset to view its contents:", reply_markup=keyboard, parse_mode='Markdown')


async def cmd_clear(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /clear - Fresh restart"""
    session_manager.clear()
    await update.message.reply_text("""🗑️ **Everything Cleared!**

✓ All uploaded CSV files deleted
✓ Conversation history reset
✓ Saved charts removed

You're starting fresh. Send a CSV file to begin!

_Note: Chat messages stay visible in Telegram. To clear those too, long-press this chat → Delete Chat._""", parse_mode='Markdown')


async def handle_document(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle file uploads"""
    doc = update.message.document
    filename = doc.file_name
    
    if not validate_file(filename):
        await update.message.reply_text("❌ Invalid type! Only CSV files allowed.")
        return
    
    msg = await update.message.reply_text("📥 Processing...")
    
    try:
        # Download
        upload_dir = ctx.bot_data.get('upload_dir', 'uploads')
        file = await ctx.bot.get_file(doc.file_id)
        path = os.path.join(upload_dir, filename)
        await file.download_to_drive(path)
        
        # Process
        info, error = process_dataset(path, filename)
        if error:
            await msg.edit_text(f"❌ {error}")
            os.remove(path) if os.path.exists(path) else None
            return
        
        removed = session_manager.add_dataset(info)
        cols = ', '.join(info.columns[:5]) + ('...' if len(info.columns) > 5 else '')
        removed_msg = f"\n⚠️ Removed: {removed}" if removed else ""
        
        await msg.edit_text(f"""✅ **{info.name}**
• {info.row_count}×{info.col_count}
• Columns: {cols}{removed_msg}

Now ask for a visualization!""", parse_mode='Markdown')
        
        # Process caption as request
        if update.message.caption:
            await process_request(update, ctx, update.message.caption)
            
    except Exception as e:
        await msg.edit_text(f"❌ {e}")


async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle text messages"""
    if not session_manager.get_all_datasets():
        await update.message.reply_text("📂 Upload a dataset first!")
        return
    await process_request(update, ctx, update.message.text)


async def process_request(update: Update, ctx: ContextTypes.DEFAULT_TYPE, text: str):
    """Process visualization request"""
    session_manager.add_message("user", text)
    msg = await update.message.reply_text("🔄 Generating...")
    
    try:
        # Get config from bot_data
        api_key = ctx.bot_data.get('gemini_api_key')
        model = ctx.bot_data.get('gemini_model', 'gemini-3-flash-preview')
        
        # Generate code
        datasets_info = session_manager.get_datasets_for_llm()
        history = session_manager.get_history()[:-1]
        
        code, error = generate_code(text, datasets_info, history, api_key, model)
        if error:
            await msg.edit_text(f"❌ {error}")
            session_manager.add_message("bot", f"Error: {error}")
            return
        
        # Check if LLM rejected the request
        if code.strip().startswith("REJECT:"):
            rejection_msg = code.strip()[7:].strip()  # Remove "REJECT:" prefix
            await msg.edit_text(f"⚠️ {rejection_msg}")
            session_manager.add_message("bot", rejection_msg)
            return
        
        # Generate chart
        await msg.edit_text("📊 Creating chart...")
        paths = session_manager.get_dataset_paths()
        success, output, png, fig_json, chart_id, insights_payload = generate_chart(code, paths)
        
        if not success:
            await msg.edit_text(f"❌ {output}")
            session_manager.add_message("bot", f"Error: {output}")
            return
        
        try:
            await msg.delete()
        except:
            pass  # Message might already be deleted
        
        # Build bot response with code for history
        bot_response = f"{output}\n\n```python\n{code}\n```"
        
        # Send results
        await update.message.reply_text(output, parse_mode='Markdown')
        
        if png:
            await update.message.reply_photo(photo=BytesIO(png))
        
        if fig_json and chart_id:
            session_manager.store_chart(chart_id, fig_json)
            if insights_payload:
                session_manager.store_insights_payload(chart_id, insights_payload)
            session_manager.add_message("bot", bot_response)

            # Provide action buttons without any visible label.
            # Telegram doesn't allow a truly empty message, so use a zero-width space.
            try:
                await update.message.reply_text("\u200b", reply_markup=_chart_actions_keyboard(chart_id, include_insights=True))
            except Exception:
                await update.message.reply_text("⚠️ Buttons unavailable. Please ensure the Web App domain is allowed in BotFather and try again.")
        else:
            session_manager.add_message("bot", bot_response)
            
    except Exception as e:
        await msg.edit_text(f"❌ {e}")
        session_manager.add_message("bot", str(e))


async def error_handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    if update and update.effective_message:
        await update.effective_message.reply_text("❌ Error occurred. Try /start")


async def handle_insights_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Generate insights only when user taps the Insights button."""
    query = update.callback_query
    if not query or not query.data:
        return

    await query.answer()

    if not query.data.startswith("insights:"):
        return

    chart_id = query.data.split(':', 1)[1].strip()
    if not chart_id:
        await query.answer()
        await query.message.reply_text("❌ Invalid chart reference")
        return

    # One-time generation: if already generated (persisted), don't regenerate.
    cached = session_manager.get_insights_text(chart_id)
    if cached:
        # Remove insights button if it still exists (older messages / failed edit)
        try:
            await query.edit_message_reply_markup(reply_markup=_chart_actions_keyboard(chart_id, include_insights=False))
        except:
            pass
        await query.message.reply_text("⚠️ Insights already generated for this chart. Redraw the graph to generate again.")
        return

    payload = session_manager.get_insights_payload(chart_id)
    if not payload:
        await query.message.reply_text("⚠️ Insights unavailable for this chart. Please regenerate the chart.")
        return

    api_key = ctx.bot_data.get('gemini_api_key')
    model = ctx.bot_data.get('gemini_model', 'gemini-3-flash-preview')
    if not api_key:
        await query.message.reply_text("❌ Gemini API key not configured")
        return

    status = await query.message.reply_text("🔄 Generating insights...")
    insights_text, insights_err = generate_insights(payload, api_key, model)
    try:
        await status.delete()
    except:
        pass

    if insights_err or not insights_text:
        await query.message.reply_text("❌ Failed to generate insights. Please try again.")
        return

    insights_text = _limit_insights_to_5(insights_text)

    session_manager.set_insights_text(chart_id, insights_text)
    session_manager.add_message("bot", f"Business insights:\n{insights_text}")
    await query.message.reply_text(f"📌 Business insights\n\n{insights_text}")

    # Hide Insights button after first successful generation
    try:
        await query.edit_message_reply_markup(reply_markup=_chart_actions_keyboard(chart_id, include_insights=False))
    except:
        pass




def setup_handlers(app: Application):
    """Register all handlers"""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("datasets", cmd_datasets))
    app.add_handler(CommandHandler("preview", cmd_preview))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CallbackQueryHandler(handle_insights_callback, pattern=r"^insights:"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
