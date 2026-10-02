import os
import random
import threading
from flask import Flask
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.environ["BOT_TOKEN"]

app = Flask(__name__)

@app.route("/")
def home():
    return "Captcha earning bot is running!"

users = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"balance": 0, "question": None})

    await update.message.reply_text(
        "🤖 Welcome to the Earning Bot!\n\n"
        "Use /task to complete a verification task.\n"
        "Use /balance to check your balance."
    )

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    balance = users.setdefault(
        user_id, {"balance": 0, "question": None}
    )["balance"]

    await update.message.reply_text(
        f"💰 Your balance: {balance} points"
    )

async def task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users.setdefault(user_id, {"balance": 0, "question": None})

    a = random.randint(1, 20)
    b = random.randint(1, 20)
    answer = a + b

    users[user_id]["question"] = answer

    await update.message.reply_text(
        f"🧩 Verification task\n\n"
        f"What is {a} + {b}?\n\n"
        f"Reply with the answer."
    )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id

    if user_id not in users or users[user_id]["question"] is None:
        return

    try:
        answer = int(update.message.text)
    except ValueError:
        return

    correct = users[user_id]["question"]

    if answer == correct:
        users[user_id]["balance"] += 1
        users[user_id]["question"] = None

        await update.message.reply_text(
            "✅ Correct!\n"
            "You earned 1 point.\n\n"
            "Use /task for another task."
        )
    else:
        await update.message.reply_text("❌ Incorrect. Try again.")

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))

def main():
    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("task", task))

    from telegram.ext import MessageHandler, filters
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    application.run_polling()

if __name__ == "__main__":
    main()
