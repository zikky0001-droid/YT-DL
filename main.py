import os
import re
import time
import tempfile
import logging
from contextlib import suppress

from flask import Flask, request, jsonify
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, TypeHandler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://yt-dl-01v8.onrender.com")

# Flask app
app = Flask(__name__)

# Initialize bot application ONCE
application = Application.builder().token(BOT_TOKEN).build()

# ==================== BOT COMMANDS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Wassup 😁, Dear User!!! I'm your YouTube downloader bot.\n\n"
        "*Commands:*\n"
        "• /help — See commands\n"
        "• /profile — Your info\n"
        "• /ytdl <YouTube link> — Download video (360p MP4)"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("⬅️ Back to Start", callback_data="go_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📖 *Commands:*\n• /start — Welcome\n• /help — This menu\n• /profile — Your info\n• /ytdl <link> — Download",
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=reply_markup
    )

async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await update.message.reply_text(
        f"👤 *Your Profile:*\n"
        f"Name: {user.full_name}\n"
        f"Username: @{user.username if user.username else 'N/A'}\n"
        f"ID: {user.id}",
        parse_mode=ParseMode.MARKDOWN
    )

# YouTube URL regex
YOUTUBE_REGEX = re.compile(
    r'(https?://)?(www\.)?(youtube|youtu|youtube-nocookie)\.(com|be)/'
    r'(watch\?v=|embed/|v/|.+\?v=)?([^&=%\?]{11})'
)

async def ytdl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        import yt_dlp
    except ImportError:
        await update.message.reply_text("❌ yt-dlp not available")
        return
    
    if not context.args:
        await update.message.reply_text("Usage: /ytdl <YouTube URL>")
        return
    
    url = context.args[0]
    if not YOUTUBE_REGEX.search(url):
        await update.message.reply_text("❌ Invalid YouTube URL")
        return
    
    msg = await update.message.reply_text("⏳ Starting download...")
    
    try:
        # Simple download with yt-dlp
        ydl_opts = {
            'format': 'best[height<=360]/worst',
            'outtmpl': '%(title)s.%(ext)s',
            'quiet': True,
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            ydl_opts['outtmpl'] = os.path.join(tmpdir, '%(title)s.%(ext)s')
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                
                # Update status
                await msg.edit_text("📤 Uploading to Telegram...")
                
                # Send video
                with open(filename, 'rb') as video_file:
                    await update.message.reply_video(
                        video=InputFile(video_file),
                        caption=f"✅ {info.get('title', 'Video')}",
                        supports_streaming=True
                    )
                    
                await msg.edit_text("✅ Download complete!")
                
    except Exception as e:
        logger.error(f"Download error: {e}")
        await msg.edit_text(f"❌ Error: {str(e)[:100]}")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "go_start":
        await query.edit_message_text("Back to start! Use /help for commands")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Update {update} caused error {context.error}")

# ==================== FLASK ROUTES ====================
@app.route("/")
def home():
    return "Telegram Bot is running! ✅"

@app.route("/health")
def health():
    return jsonify({
        "status": "healthy",
        "bot": "ready",
        "timestamp": time.time()
    })

@app.route("/set_webhook", methods=["GET"])
def set_webhook():
    """Set webhook manually - Render Free Tier compatible"""
    try:
        # Set webhook synchronously
        application.bot.set_webhook(
            url=f"{RENDER_EXTERNAL_URL}/webhook",
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
        return jsonify({
            "success": True,
            "webhook_url": f"{RENDER_EXTERNAL_URL}/webhook",
            "message": "Webhook set successfully"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle Telegram updates"""
    try:
        # Process update
        update = Update.de_json(request.get_json(), application.bot)
        application.update_queue.put_nowait(update)
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/delete_webhook", methods=["GET"])
def delete_webhook():
    """Delete webhook"""
    try:
        application.bot.delete_webhook()
        return jsonify({"success": True, "message": "Webhook deleted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== MAIN ====================
def main():
    """Initialize bot handlers"""
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_cmd))
    application.add_handler(CommandHandler("profile", profile))
    application.add_handler(CommandHandler("ytdl", ytdl))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_error_handler(error_handler)
    
    # Initialize (but don't start polling)
    application.initialize()
    
    logger.info("✅ Bot initialized successfully")
    logger.info(f"🌐 Webhook URL: {RENDER_EXTERNAL_URL}/webhook")
    logger.info(f"🔗 Set webhook: {RENDER_EXTERNAL_URL}/set_webhook")

# Run initialization
if __name__ == "__main__":
    # Validate token
    if not BOT_TOKEN:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")
    
    # Initialize bot
    main()
    
    # Run Flask
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"🚀 Starting Flask on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
