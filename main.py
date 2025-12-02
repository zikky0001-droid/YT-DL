import os
import re
import asyncio
import time
import tempfile
import logging
import threading
from contextlib import suppress
from typing import Optional

from flask import Flask, request, jsonify
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler
from telegram.error import TelegramError

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "https://yt-dl-01v8.onrender.com")
WEBHOOK_PORT = int(os.getenv("PORT", 10000))
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")

# Regex for YouTube links
YOUTUBE_URL_RE = re.compile(
    r"^(https?://)?(www\.)?"
    r"(youtube\.com/(watch\?v=[\w-]+|shorts/[\w-]+|live/[\w-]+)|youtu\.be/[\w-]+)"
    r"([&?][^\s]+)?$",
    re.IGNORECASE,
)

DEFAULT_YTDLP_OPTS = {
    "format": "best[ext=mp4][height<=360]/best[height<=360]",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "restrictfilenames": True,
    "outtmpl": "%(title).80s.%(ext)s",
}

# Flask app
app = Flask(__name__)

# Global bot application instance
bot_application: Optional[ApplicationBuilder] = None
webhook_info_cache = {"url": None, "pending_updates": 0, "last_checked": 0}

# ==================== FLASK ROUTES ====================
@app.route("/")
def index():
    return "Telegram YTDL Bot ✅ is running smoothly 🎉🎉🎉!"

@app.route("/health")
def health():
    """Health check endpoint - SYNC VERSION"""
    if not bot_application or not bot_application.bot:
        return jsonify({"status": "initializing", "bot": "not_ready"}), 202
    
    # Use cached webhook info to avoid async issues
    return jsonify({
        "status": "healthy",
        "bot": "connected",
        "webhook_set": webhook_info_cache["url"] is not None,
        "webhook_url": webhook_info_cache["url"],
        "pending_updates": webhook_info_cache["pending_updates"],
        "last_checked": webhook_info_cache["last_checked"]
    })

@app.route("/setwebhook", methods=["GET"])
def set_webhook():
    """Manually set webhook - called from main thread"""
    if not bot_application:
        return jsonify({"error": "Bot not initialized"}), 500
    
    # Schedule webhook setup in the bot's event loop
    asyncio.run_coroutine_threadsafe(setup_webhook_async(), bot_application._event_loop)
    
    return jsonify({
        "message": "Webhook setup scheduled. Check logs for completion.",
        "scheduled": True
    })

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle incoming updates from Telegram - SYNC wrapper"""
    if not bot_application:
        logger.error("Bot application not initialized")
        return jsonify({"error": "Bot not initialized"}), 500
    
    # Verify secret token if set
    if WEBHOOK_SECRET:
        secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
        if secret_header != WEBHOOK_SECRET:
            logger.warning(f"Invalid secret token: {secret_header}")
            return jsonify({"error": "Invalid secret token"}), 403
    
    try:
        # Process update asynchronously
        update = Update.de_json(request.get_json(), bot_application.bot)
        
        # Run in bot's event loop
        asyncio.run_coroutine_threadsafe(
            bot_application.process_update(update),
            bot_application._event_loop
        )
        
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Error processing webhook: {e}")
        return jsonify({"error": str(e)}), 500

# ==================== ASYNC FUNCTIONS ====================
async def setup_webhook_async():
    """Async function to set up webhook"""
    try:
        logger.info("Setting up webhook...")
        
        # Remove existing webhook first
        await bot_application.bot.delete_webhook()
        
        webhook_url = f"{RENDER_EXTERNAL_URL}/webhook"
        
        # Set new webhook
        await bot_application.bot.set_webhook(
            webhook_url,
            secret_token=WEBHOOK_SECRET if WEBHOOK_SECRET else None,
            max_connections=40,
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
        # Update cache
        webhook_info = await bot_application.bot.get_webhook_info()
        webhook_info_cache.update({
            "url": webhook_info.url,
            "pending_updates": webhook_info.pending_update_count,
            "last_checked": time.time()
        })
        
        logger.info(f"✅ Webhook set to: {webhook_url}")
        logger.info(f"Webhook info: {webhook_info}")
        
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")

async def update_webhook_cache():
    """Periodically update webhook info cache"""
    while True:
        try:
            if bot_application and bot_application.bot:
                webhook_info = await bot_application.bot.get_webhook_info()
                webhook_info_cache.update({
                    "url": webhook_info.url,
                    "pending_updates": webhook_info.pending_update_count,
                    "last_checked": time.time()
                })
        except Exception as e:
            logger.error(f"Error updating webhook cache: {e}")
        
        await asyncio.sleep(60)  # Update every 60 seconds

# ==================== BOT UTILITIES ====================
def human_bytes(n: float) -> str:
    """Convert bytes to human readable format"""
    if n is None:
        return "unknown"
    units = ["B", "KB", "MB", "GB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}"

class ProgressNotifier:
    """Utility class for sending progress updates"""
    def __init__(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
        self.context = context
        self.chat_id = chat_id
        self.message_id = message_id
        self.last_edit = 0
        self.last_text = None

    async def update(self, text: str, min_interval: float = 0.8):
        """Update progress message with rate limiting"""
        now = time.time()
        if self.last_text == text and (now - self.last_edit) < min_interval:
            return
        if (now - self.last_edit) < min_interval:
            return
        with suppress(Exception):
            await self.context.bot.edit_message_text(
                chat_id=self.chat_id,
                message_id=self.message_id,
                text=text,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
            self.last_edit = now
            self.last_text = text

# ==================== BOT COMMANDS ====================
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    logger.info("Received /start from user %s", update.effective_user.id)
    await update.message.reply_text(
        "👋 Wassup 😁, Dear User!!! I'm your newly crafted YouTube downloader bot.\n\n"
        "*To Use Me, below are some of my fresh commands:*\n"
        "• /help — See commands\n"
        "• /profile — Your info\n"
        "• /ytdl <YouTube link> — Download video (360p MP4)"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    logger.info("Received /help from user %s", update.effective_user.id)
    keyboard = [[InlineKeyboardButton("⬅️ Back to Start", callback_data="go_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    help_text = (
        "📖 *Available Commands:*\n\n"
        "• /start — Welcome message 💬\n"
        "• /help — Show this help menu ⚡\n"
        "• /profile — Your Telegram details 🚀\n"
        "• /ytdl <YouTube link> — Download YouTube video 🥂\n\n"
        "Tap the button below to return to the start message."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /profile command"""
    user = update.effective_user
    logger.info("Received /profile from user %s", user.id)
    lines = [
        f"Name: {user.full_name}",
        f"Username: @{user.username}" if user.username else "Username: (none)",
        f"ID: {user.id}",
        f"Language: {user.language_code or 'unknown'}",
        f"Is bot: {user.is_bot}",
    ]
    await update.message.reply_text("\n".join(lines))

async def ytdl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ytdl command - download YouTube video"""
    try:
        import yt_dlp
    except ImportError:
        await update.message.reply_text("❌ yt-dlp not installed. Please contact admin.")
        return
    
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /ytdl <YouTube link>")
        return
    
    url = args[0].strip()
    if not YOUTUBE_URL_RE.match(url):
        await update.message.reply_text("Invalid YouTube link.")
        return

    logger.info("Starting download for URL: %s (user %s)", url, update.effective_user.id)
    status_msg = await update.message.reply_text("🔍 Preparing download…")
    notifier = ProgressNotifier(context, status_msg.chat_id, status_msg.message_id)
    start_time = time.time()
    tmpdir = tempfile.TemporaryDirectory()

    try:
        await notifier.update("🔍 Fetching video info...")
        
        ydl_opts = dict(DEFAULT_YTDLP_OPTS)
        ydl_opts["paths"] = {"home": tmpdir.name}
        ydl_opts["retries"] = 3
        ydl_opts["socket_timeout"] = 30
        
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Get video info first
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
            title = info.get('title', 'Unknown')
            
            # Check video duration
            duration = info.get('duration', 0)
            if duration > 1800:  # 30 minutes
                await notifier.update("❌ Video too long! Max 30 minutes allowed.")
                return
            
            await notifier.update(f"🎬 Found: {title[:50]}...\n⬇️ Starting download...")
            
            # Download the video
            await loop.run_in_executor(None, lambda: ydl.download([url]))
            
            # Find downloaded file
            filename = None
            for file in os.listdir(tmpdir.name):
                if file.endswith(('.mp4', '.mkv', '.webm')):
                    filename = os.path.join(tmpdir.name, file)
                    break
            
            if not filename or not os.path.exists(filename):
                await notifier.update("❌ Download failed: No video file found")
                return

        await notifier.update("📤 Uploading to Telegram...")
        elapsed = int(time.time() - start_time)
        
        # Create caption
        caption = (
            f"✅ Download Complete!\n"
            f"⏱️ Time: {elapsed}s\n"
            f"🎬 Title: {title[:200]}\n"
            f"📏 Quality: 360p MP4"
        )

        # Check file size
        file_size = os.path.getsize(filename)
        max_size = 50 * 1024 * 1024  # 50MB Telegram limit
        
        if file_size > max_size:
            await notifier.update(f"❌ File too large ({human_bytes(file_size)}). Max 50MB allowed.")
            return
        
        with open(filename, "rb") as f:
            try:
                await update.message.reply_video(
                    video=InputFile(f, filename=os.path.basename(filename)),
                    caption=caption,
                    supports_streaming=True,
                    read_timeout=60,
                    write_timeout=60
                )
                logger.info("✅ Video sent successfully to user %s", update.effective_user.id)
            except Exception as e:
                logger.warning("Video send failed, trying as document. Error: %s", e)
                f.seek(0)
                await update.message.reply_document(
                    document=InputFile(f, filename=os.path.basename(filename)),
                    caption=caption,
                    read_timeout=60,
                    write_timeout=60
                )

    except Exception as e:
        logger.error("Download failed for URL %s: %s", url, e)
        error_msg = str(e)[:200]
        await notifier.update(f"❌ Error: {error_msg}")
        
    finally:
        # Cleanup
        try:
            tmpdir.cleanup()
        except:
            pass

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "go_start":
        await query.edit_message_text(
            "👋 Hey! I'm your YouTube downloader bot.\n\n"
            "Use:\n"
            "• /help — See commands\n"
            "• /profile — Your info\n"
            "• /ytdl <YouTube link> — Download video (360p MP4)"
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler"""
    logger.error("Exception while handling update:", exc_info=context.error)
    
    if update and update.effective_chat:
        try:
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text="❌ Sorry, an error occurred. Please try again later."
            )
        except:
            pass

async def post_init(application):
    """Initialize after bot is ready"""
    logger.info("Bot initialized, setting up webhook...")
    
    # Schedule webhook setup
    asyncio.create_task(setup_webhook_async())
    
    # Start cache updater
    asyncio.create_task(update_webhook_cache())
    
    logger.info("✅ Bot ready to receive commands")

def run_flask():
    """Run Flask in a separate thread"""
    logger.info(f"Starting Flask server on port {WEBHOOK_PORT}")
    app.run(host="0.0.0.0", port=WEBHOOK_PORT, debug=False, use_reloader=False)

def main():
    """Main entry point"""
    global bot_application
    
    # Validate environment variables
    if not BOT_TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN environment variable is not set!")
        logger.error("Please set it in Render dashboard → Environment")
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    
    logger.info("🚀 Initializing Telegram Bot...")
    logger.info(f"Bot Token: {BOT_TOKEN[:10]}...")
    logger.info(f"External URL: {RENDER_EXTERNAL_URL}")
    
    try:
        # Create bot application with event loop
        bot_application = (
            ApplicationBuilder()
            .token(BOT_TOKEN)
            .post_init(post_init)
            .concurrent_updates(True)
            .build()
        )
        
        # Add handlers
        bot_application.add_handler(CommandHandler("start", start_cmd))
        bot_application.add_handler(CommandHandler("help", help_cmd))
        bot_application.add_handler(CommandHandler("profile", profile_cmd))
        bot_application.add_handler(CommandHandler("ytdl", ytdl_cmd))
        bot_application.add_handler(CallbackQueryHandler(button_handler))
        
        # Add error handler
        bot_application.add_error_handler(error_handler)
        
        # Initialize bot (starts event loop in background)
        bot_application.initialize()
        
        logger.info("✅ Bot application initialized successfully")
        
        # Start Flask in a separate thread
        flask_thread = threading.Thread(target=run_flask, daemon=True)
        flask_thread.start()
        
        logger.info("✅ Flask server started")
        logger.info("✅ Bot is ready! Webhook will be set up automatically")
        logger.info(f"📡 Health check: {RENDER_EXTERNAL_URL}/health")
        logger.info(f"🔧 Manual webhook: {RENDER_EXTERNAL_URL}/setwebhook")
        
        # Keep main thread alive
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
        finally:
            if bot_application:
                bot_application.shutdown()
                
    except Exception as e:
        logger.error(f"❌ Failed to initialize bot: {e}")
        raise

if __name__ == "__main__":
    main()
