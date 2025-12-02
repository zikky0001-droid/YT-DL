import os, tempfile, subprocess, sys, json, time, re
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN")

yt_regex = re.compile(r'(?:https?:\/\/)?(?:www\.)?(youtube\.com\/watch\?v=|youtu\.be\/)([A-Za-z0-9\-_]+)')

# /start command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Welcome to the YouTube Downloader Bot!\n\n"
        "Use the command:\n\n"
        "<code>/ytdl [YouTube link]</code>\n\n"
        "to download YouTube videos directly here.\n\n"
        "⚠️ Limits:\n• Max duration: 5 minutes\n• Max size: 50 MB",
        parse_mode="HTML"
    )

# /ytdl command
async def ytdl(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args
    if not args:
        await update.message.reply_text("❌ Please provide a YouTube link.\nExample: /ytdl https://youtu.be/dQw4w9WgXcQ")
        return

    url = args[0]
    if not yt_regex.search(url):
        await update.message.reply_text("❌ Invalid YouTube URL.")
        return

    quality = "18"  # default 360p
    await update.message.reply_text("⏳ Downloading... Please wait.")

    try:
        # Step 1: Metadata check
        result = subprocess.run(
            ["yt-dlp", "--print-json", "-f", quality, url],
            capture_output=True, text=True, check=True
        )
        info = json.loads(result.stdout.splitlines()[0])
        duration = info.get("duration", 0)
        filesize = info.get("filesize", 0) or info.get("filesize_approx", 0)

        print(f"[YT-DL] Duration: {duration}s, Size: {filesize} bytes", flush=True)

        if duration > 300 or (filesize and filesize > 50 * 1024 * 1024):
            await update.message.reply_text("❌ File too long for the bot to execute.")
            return

    except Exception as e:
        print(f"[YT-DL] Metadata check failed: {e}", flush=True)
        time.sleep(20)
        await update.message.reply_text("❌ Unable to process URL.")
        return

    # Step 2: Download
    tmpdir = tempfile.mkdtemp()
    output_template = os.path.join(tmpdir, "%(title)s.%(ext)s")
    cmd = ["yt-dlp", "-o", output_template, "-f", quality, url]

    print(f"[YT-DL] Starting download...", flush=True)
    try:
        subprocess.check_call(cmd)
    except subprocess.CalledProcessError as e:
        print(f"[YT-DL] Download failed: {e}", flush=True)
        time.sleep(20)
        await update.message.reply_text("❌ Download failed.")
        return

    files = [os.path.join(tmpdir, f) for f in os.listdir(tmpdir)]
    if not files:
        await update.message.reply_text("❌ No output file found.")
        return

    output_path = files[0]
    print(f"[YT-DL] Download complete: {output_path}", flush=True)

    # Step 3: Send file to Telegram
    try:
        await update.message.reply_document(document=open(output_path, "rb"))
        await update.message.reply_text("✅ Download complete! Your video is ready 🎬")
    except Exception as e:
        print(f"[YT-DL] Sending file failed: {e}", flush=True)
        await update.message.reply_text("❌ Failed to send file.")

def main():
    if not BOT_TOKEN:
        print("BOT_TOKEN not set in environment", flush=True)
        return

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ytdl", ytdl))

    print("[YT-DL] Bot is running...", flush=True)
    app.run_polling()

if __name__ == "__main__":
    main()
