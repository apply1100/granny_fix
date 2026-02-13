import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong ✅")

async def chatid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"chat_id: {update.effective_chat.id}")

def main():
    print("Bot starting...")
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is missing")

    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("chatid", chatid))

    app.run_polling()

if __name__ == "__main__":
    main()
