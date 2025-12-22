"""Telegram bot handlers"""
import os
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters

from core import session_manager, process_dataset, validate_file, generate_chart, bandit, CODE_ARMS, INSIGHTS_ARMS
from services import generate_code, generate_insights, generate_recommendations, get_chart_url, get_preview_url


def _chart_actions_keyboard(chart_id: str, arm_id: str = None, include_insights: bool = True) -> InlineKeyboardMarkup:
    """Single-column layout with chart actions and feedback buttons."""
    url = get_chart_url(chart_id)
    rows = []
    if url:
        rows.append([InlineKeyboardButton("🔍 Open Interactive Chart", web_app=WebAppInfo(url=url))])
    if include_insights:
        rows.append([InlineKeyboardButton("📌 Generate Insights (5)", callback_data=f"insights:{chart_id}")])
    # Add feedback buttons if arm_id provided
    if arm_id:
        rows.append([
            InlineKeyboardButton("👍", callback_data=f"feedback:1:{arm_id}:{chart_id}"),
            InlineKeyboardButton("👎", callback_data=f"feedback:0:{arm_id}:{chart_id}")
        ])
    return InlineKeyboardMarkup(rows)


def _feedback_keyboard(arm_id: str, context_id: str) -> InlineKeyboardMarkup:
    """Feedback buttons for insights or standalone feedback."""
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("👍", callback_data=f"feedback:1:{arm_id}:{context_id}"),
        InlineKeyboardButton("👎", callback_data=f"feedback:0:{arm_id}:{context_id}")
    ]])


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

**Step 2: Get Chart Ideas (Optional)**
Use /recommend to get AI-powered suggestions for visualizations based on your data!

**Step 3: Request a Visualization**
Just describe what you want in plain English:
• "Bar chart of sales by region"
• "Compare revenue vs expenses over time"
• "Pie chart showing category distribution"
• "Scatter plot of price vs quantity"

**Step 4: Interact & Give Feedback**
• Tap "Interactive" button to zoom, pan, and explore
• Use 👍/👎 to rate results - this helps improve the AI!

**Commands:**
/start - Check bot status & your datasets
/datasets - See details of uploaded files
/preview - View the actual data in your CSV
/recommend - Get AI chart recommendations
/bandit - View A/B test statistics
/clear - Remove all files & start over
/help - Show this guide

**Tips:**
💡 Use /recommend 10 for more suggestions (3-15)
💡 Your feedback helps the AI learn which prompts work best
💡 Use /bandit to see how the AI is learning from feedback""", parse_mode='Markdown')


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


async def cmd_recommend(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /recommend - Get AI-powered chart recommendations"""
    datasets = session_manager.get_all_datasets()
    
    if not datasets:
        await update.message.reply_text(
            "📂 **No Datasets Yet**\n\nUpload a CSV file first, then use /recommend to get chart suggestions!",
            parse_mode='Markdown'
        )
        return
    
    # Parse optional argument for number of recommendations (default: 5)
    num_charts = 5
    if ctx.args and len(ctx.args) > 0:
        try:
            num_charts = min(max(int(ctx.args[0]), 3), 15)  # Clamp between 3-15
        except ValueError:
            pass
    
    msg = await update.message.reply_text(
        f"🧠 Analyzing your data and generating {num_charts} chart recommendations..."
    )
    
    try:
        api_key = ctx.bot_data.get('gemini_api_key')
        model = ctx.bot_data.get('gemini_model', 'gemini-3-flash-preview')
        
        if not api_key:
            await msg.edit_text("❌ Gemini API key not configured")
            return
        
        datasets_info = session_manager.get_datasets_for_llm()
        recommendations, error = generate_recommendations(datasets_info, num_charts, api_key, model)
        
        if error:
            await msg.edit_text(f"❌ {error}")
            return
        
        # Delete the "Analyzing..." message
        try:
            await msg.delete()
        except:
            pass
        
        # Send recommendations (split if too long for Telegram)
        header = f"📈 **Chart Recommendations for Your Data**\n\n"
        full_text = header + recommendations
        
        # Telegram message limit is 4096 chars
        if len(full_text) <= 4096:
            await update.message.reply_text(full_text, parse_mode='Markdown')
        else:
            # Split into chunks
            await update.message.reply_text(header + "_(See recommendations below)_", parse_mode='Markdown')
            chunks = _split_recommendations(recommendations)
            for chunk in chunks:
                if chunk.strip():
                    try:
                        await update.message.reply_text(chunk, parse_mode='Markdown')
                    except:
                        # Fallback without markdown if parsing fails
                        await update.message.reply_text(chunk)
        
        # Add tip
        await update.message.reply_text(
            "💡 **Tip:** Copy any command above and send it to me to create that chart!",
            parse_mode='Markdown'
        )
        
    except Exception as e:
        await msg.edit_text(f"❌ Error: {e}")


def _split_recommendations(text: str, max_len: int = 4000) -> list:
    """Split recommendations into chunks at section boundaries."""
    chunks = []
    current = ""
    
    # Split by ## headers (category sections)
    sections = text.split('\n## ')
    
    for i, section in enumerate(sections):
        if i > 0:
            section = '## ' + section
        
        if len(current) + len(section) + 1 > max_len:
            if current:
                chunks.append(current.strip())
            current = section
        else:
            current += ('\n' if current else '') + section
    
    if current:
        chunks.append(current.strip())
    
    return chunks


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
        
        # Generate code (now returns arm_id for bandit tracking)
        datasets_info = session_manager.get_datasets_for_llm()
        history = session_manager.get_history()[:-1]
        
        code, error, arm_id = generate_code(text, datasets_info, history, api_key, model)
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
            # Store arm_id for feedback tracking
            if arm_id:
                session_manager.store_arm_id(chart_id, arm_id)
            session_manager.add_message("bot", bot_response)

            # Provide action buttons with feedback
            keyboard = _chart_actions_keyboard(chart_id, arm_id=arm_id, include_insights=True)
            try:
                await update.message.reply_text("📊 Chart ready! Rate this result:", reply_markup=keyboard)
            except Exception as btn_err:
                # Log the actual error for debugging
                print(f"[Button Error] {type(btn_err).__name__}: {btn_err}")
                await update.message.reply_text(f"⚠️ Buttons unavailable: {btn_err}")
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
            # Get stored arm_id for the chart to preserve feedback buttons
            stored_arm_id = session_manager.get_arm_id(chart_id)
            await query.edit_message_reply_markup(
                reply_markup=_chart_actions_keyboard(chart_id, arm_id=stored_arm_id, include_insights=False)
            )
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
    insights_text, insights_err, insights_arm_id = generate_insights(payload, api_key, model)
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
    
    # Send insights with feedback buttons
    insights_msg = f"📌 Business insights\n\n{insights_text}"
    if insights_arm_id:
        # Store insights arm_id separately
        session_manager.store_arm_id(f"insights_{chart_id}", insights_arm_id)
        keyboard = _feedback_keyboard(insights_arm_id, f"insights_{chart_id}")
        await query.message.reply_text(insights_msg, reply_markup=keyboard)
    else:
        await query.message.reply_text(insights_msg)

    # Hide Insights button after first successful generation, keep feedback buttons
    try:
        stored_arm_id = session_manager.get_arm_id(chart_id)
        await query.edit_message_reply_markup(
            reply_markup=_chart_actions_keyboard(chart_id, arm_id=stored_arm_id, include_insights=False)
        )
    except:
        pass


async def handle_feedback_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle thumbs up/down feedback for bandit learning."""
    query = update.callback_query
    if not query or not query.data:
        return

    if not query.data.startswith("feedback:"):
        return

    # Parse callback data: feedback:reward:arm_id:context_id
    parts = query.data.split(':', 3)
    if len(parts) < 4:
        await query.answer("Invalid feedback data")
        return

    _, reward_str, arm_id, context_id = parts
    
    try:
        reward = int(reward_str)
        if reward not in (0, 1):
            raise ValueError("Invalid reward")
    except ValueError:
        await query.answer("Invalid feedback")
        return

    # Update bandit with feedback
    stats = bandit.update(arm_id, reward)
    
    # Show confirmation and remove feedback buttons
    feedback_emoji = "👍" if reward == 1 else "👎"
    await query.answer(f"Thanks for your feedback! {feedback_emoji}")
    
    # Remove the feedback buttons from the message
    try:
        # Get current message text and rebuild without feedback buttons
        current_text = query.message.text or ""
        if "Chart ready" in current_text:
            # This is a chart action message - rebuild with just chart buttons
            chart_id = context_id
            url = get_chart_url(chart_id)
            rows = []
            if url:
                rows.append([InlineKeyboardButton("🔍 Open Interactive Chart", web_app=WebAppInfo(url=url))])
            # Check if insights were already generated
            if not session_manager.get_insights_text(chart_id):
                rows.append([InlineKeyboardButton("📌 Generate Insights (5)", callback_data=f"insights:{chart_id}")])
            rows.append([InlineKeyboardButton(f"✓ Rated {feedback_emoji}", callback_data="noop")])
            await query.edit_message_reply_markup(reply_markup=InlineKeyboardMarkup(rows))
        else:
            # This is an insights message - just show rated confirmation
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(f"✓ Rated {feedback_emoji}", callback_data="noop")
                ]])
            )
    except Exception:
        pass  # Message might not be editable


async def handle_noop_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle no-op callbacks (rated buttons)."""
    query = update.callback_query
    if query:
        await query.answer("Already rated!")


async def cmd_bandit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle /bandit - Show bandit statistics for A/B testing."""
    all_stats = bandit.get_all_stats()
    
    if not all_stats:
        await update.message.reply_text(
            "📊 **Bandit Statistics**\n\nNo data yet. Generate some charts and provide feedback!",
            parse_mode='Markdown'
        )
        return
    
    # Format statistics
    lines = ["📊 **Thompson Bandit A/B Test Results**\n"]
    
    # Group by stage
    code_stats = {k: v for k, v in all_stats.items() if k.startswith('code_')}
    insights_stats = {k: v for k, v in all_stats.items() if k.startswith('insights_')}
    
    if code_stats:
        lines.append("**📈 Code Generation Prompts:**")
        for arm_id, stats in sorted(code_stats.items()):
            version = arm_id.replace('code_', '').upper()
            exp_val = stats.expected_value
            success_pct = (stats.alpha - 1) / max(stats.pulls, 1) * 100 if stats.pulls > 0 else 0
            lines.append(
                f"  • **{version}**: {stats.pulls} pulls | "
                f"👍 {int(stats.alpha - 1)} | 👎 {int(stats.beta - 1)} | "
                f"Win rate: {success_pct:.1f}% | E[p]: {exp_val:.3f}"
            )
        lines.append("")
    
    if insights_stats:
        lines.append("**💡 Insights Prompts:**")
        for arm_id, stats in sorted(insights_stats.items()):
            version = arm_id.replace('insights_', '').upper()
            exp_val = stats.expected_value
            success_pct = (stats.alpha - 1) / max(stats.pulls, 1) * 100 if stats.pulls > 0 else 0
            lines.append(
                f"  • **{version}**: {stats.pulls} pulls | "
                f"👍 {int(stats.alpha - 1)} | 👎 {int(stats.beta - 1)} | "
                f"Win rate: {success_pct:.1f}% | E[p]: {exp_val:.3f}"
            )
        lines.append("")
    
    # Add explanation
    lines.append("_Thompson Sampling automatically favors better-performing prompts over time._")
    lines.append("_E[p] = Expected probability of success (higher = better)_")
    
    await update.message.reply_text("\n".join(lines), parse_mode='Markdown')




def setup_handlers(app: Application):
    """Register all handlers"""
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("datasets", cmd_datasets))
    app.add_handler(CommandHandler("preview", cmd_preview))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("recommend", cmd_recommend))
    app.add_handler(CommandHandler("bandit", cmd_bandit))
    app.add_handler(CallbackQueryHandler(handle_insights_callback, pattern=r"^insights:"))
    app.add_handler(CallbackQueryHandler(handle_feedback_callback, pattern=r"^feedback:"))
    app.add_handler(CallbackQueryHandler(handle_noop_callback, pattern=r"^noop$"))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_error_handler(error_handler)
