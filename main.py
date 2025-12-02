import os
import re
import asyncio
import time
import tempfile
import threading
import logging
from contextlib import suppress

from flask import Flask
from telegram import Update, InputFile, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Flask app for Render health check
app = Flask(__name__)

@app.route("/")
def index():
    return "Telegram YTDL Bot is running!"

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

# Utility
def human_bytes(n: float) -> str:
    if n is None:
        return "unknown"
    units = ["B", "KB", "MB", "GB"]
    i = 0
    while n >= 1024 and i < len(units) - 1:
        n /= 1024.0
        i += 1
    return f"{n:.1f} {units[i]}"

class ProgressNotifier:
    def __init__(self, context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int):
        self.context = context
        self.chat_id = chat_id
        self.message_id = message_id
        self.last_edit = 0
        self.last_text = None

    async def update(self, text: str, min_interval: float = 0.8):
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

# Commands
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /start from user %s", update.effective_user.id)
    await update.message.reply_text(
        "👋 Hey! I’m your YouTube downloader bot.\n\n"
        "Use:\n"
        "• /help — See commands\n"
        "• /profile — Your info\n"
        "• /ytdl <YouTube link> — Download video (360p MP4)"
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info("Received /help from user %s", update.effective_user.id)
    keyboard = [[InlineKeyboardButton("⬅️ Back to Start", callback_data="go_start")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    help_text = (
        "📖 *Available Commands:*\n\n"
        "• /start — Welcome message\n"
        "• /help — Show this help menu\n"
        "• /profile — Your Telegram details\n"
        "• /ytdl <YouTube link> — Download YouTube video\n\n"
        "Tap the button below to return to the start message."
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN, reply_markup=reply_markup)

async def profile_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    from yt_dlp import YoutubeDL
    args = context.args
    if not args:
        await update.message.reply_text("Usage: /ytdl <YouTube link>")
        return
    url = args[0].strip()
    if not YOUTUBE_URL_RE.match(url):
        await update.message.reply_text("Invalid YouTube link.")
        return

    logger.info("Starting download for URL: %s (user %s)", url, update.effective_user.id)
    status_msg = await update.message.reply_text("Preparing download…")
    notifier = ProgressNotifier(context, status_msg.chat_id, status_msg.message_id)
    start_time = time.time()
    tmpdir = tempfile.TemporaryDirectory()

    progress_state = {"title": None, "filename": None}

    def hook(d):
        if d["status"] == "downloading":
            progress_state["filename"] = d.get("filename")
            asyncio.create_task(notifier.update("Downloading…"))
        elif d["status"] == "finished":
            asyncio.create_task(notifier.update("Finalizing…"))

    ydl_opts = dict(DEFAULT_YTDLP_OPTS)
    ydl_opts["progress_hooks"] = [hook]
    ydl_opts["paths"] = {"home": tmpdir.name}

    try:
        loop = asyncio.get_running_loop()
        with YoutubeDL(ydl_opts) as ydl:
            info = await loop.run_in_executor(None, lambda: ydl.extract_info(url, download=True))
            filename = ydl.prepare_filename(info)
            progress_state["title"] = info.get("title")

        await notifier.update("Upload to Telegram…")
        elapsed = int(time.time() - start_time)
        caption = f"✅ Done in {elapsed}s\nTitle: {progress_state['title']}"

        with open(filename, "rb") as f:
            try:
                await update.message.reply_video(video=InputFile(f), caption=caption, supports_streaming=True)
                logger.info("Video sent successfully to user %s", update.effective_user.id)
            except Exception as e:
                logger.warning("Video send failed, fallback to document. Error: %s", e)
                f.seek(0)
                await update.message.reply_document(document=InputFile(f), caption=caption)

    except Exception as e:
        logger.error("Download failed for URL %s: %s", url, e)
        await notifier.update(f"Error: {str(e)[:200]}")
    finally:
        tmpdir.cleanup()

# Inline button callback
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "go_start":
        await query.edit_message_text(
            "👋 Hey! I’m your YouTube downloader bot.\n\n"
            "Use:\n"
            "• /help — See commands\n"
            "• /profile — Your info\n"
            "• /ytdl <YouTube link> — Download video (360p MP4)"
        )

def run_bot():
    app_builder = ApplicationBuilder().token(BOT_TOKEN).build()
    app_builder.add_handler(CommandHandler("start", start_cmd))
    app_builder.add_handler(CommandHandler("help", help_cmd))
    app_builder.add_handler(CommandHandler("profile", profile_cmd))
    app_builder.add_handler(CommandHandler("ytdl", ytdl_cmd))
    app_builder.add_handler(CallbackQueryHandler(button_handler))
    logger.info("Bot started polling…")
    app_builder.run_polling()

if __name__ == "__main__":
    if not BOT_TOKEN:
        raise RuntimeError("Missing TELEGRAM_BOT_TOKEN env var")
    threading.Thread(target=run_bot, daemon=True).start()
    logger.info("Starting Flask web server for Render health check…")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
