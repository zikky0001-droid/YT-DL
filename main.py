import os
import logging
from flask import Flask, request, jsonify

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Environment Variables
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Flask app
app = Flask(__name__)

# Store bot state
import telegram
from telegram.ext import Application, CommandHandler, MessageHandler, filters
import asyncio
import threading

bot = telegram.Bot(token=BOT_TOKEN)
application = None

# ==================== BOT HANDLERS ====================
async def start(update, context):
    await update.message.reply_text("✅ Bot is working! /help for commands")

async def help_cmd(update, context):
    await update.message.reply_text("Help: /start, /help, /ping")

async def ping(update, context):
    await update.message.reply_text("🏓 Pong!")

async def handle_message(update, context):
    await update.message.reply_text(f"Echo: {update.message.text}")

async def error_handler(update, context):
    logger.error(f"Update {update} caused error {context.error}")

# ==================== FLASK ROUTES ====================
@app.route("/")
def home():
    return "Bot is running! ✅ Use /set_webhook to activate."

@app.route("/health")
def health():
    return jsonify({"status": "healthy", "bot_token_set": bool(BOT_TOKEN)})

@app.route("/set_webhook", methods=["GET"])
def set_webhook_endpoint():
    """Manually set webhook"""
    try:
        webhook_url = f"https://yt-dl-01v8.onrender.com/webhook"
        
        # Delete old webhook first
        bot.delete_webhook()
        
        # Set new webhook
        bot.set_webhook(
            url=webhook_url,
            allowed_updates=["message", "callback_query"]
        )
        
        # Verify
        info = bot.get_webhook_info()
        
        return jsonify({
            "success": True,
            "webhook_url": webhook_url,
            "webhook_info": {
                "url": info.url,
                "pending_updates": info.pending_update_count
            },
            "message": "Webhook set successfully! Test with /start in Telegram."
        })
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    """Handle Telegram updates"""
    try:
        if request.is_json:
            update = telegram.Update.de_json(request.get_json(), bot)
            
            # Initialize application if not done
            global application
            if not application:
                application = Application.builder().token(BOT_TOKEN).build()
                application.add_handler(CommandHandler("start", start))
                application.add_handler(CommandHandler("help", help_cmd))
                application.add_handler(CommandHandler("ping", ping))
                application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
                application.add_error_handler(error_handler)
                application.initialize()
                logger.info("Bot application initialized")
            
            # Process update
            application.process_update(update)
            
            return jsonify({"status": "ok"})
        return jsonify({"error": "Invalid content"}), 400
    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/get_webhook_info", methods=["GET"])
def get_webhook_info():
    """Check webhook status"""
    try:
        info = bot.get_webhook_info()
        return jsonify({
            "url": info.url,
            "pending_updates": info.pending_update_count,
            "has_custom_certificate": info.has_custom_certificate,
            "last_error_date": info.last_error_date,
            "last_error_message": info.last_error_message
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ==================== MAIN ====================
if __name__ == "__main__":
    if not BOT_TOKEN:
        raise ValueError("❌ TELEGRAM_BOT_TOKEN not set!")
    
    logger.info(f"Starting bot with token: {BOT_TOKEN[:10]}...")
    
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Server starting on port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
