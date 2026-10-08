import os
import random
import threading
import asyncio

from flask import Flask
from supabase import create_client
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# =========================
# ENVIRONMENT VARIABLES
# =========================

BOT_TOKEN = os.environ["BOT_TOKEN"]

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

print("=================================")
print("Starting Captcha Earn Bot...")
print("BOT_TOKEN found:", bool(BOT_TOKEN))
print("SUPABASE_URL found:", bool(SUPABASE_URL))
print("SUPABASE_SECRET_KEY found:", bool(SUPABASE_SECRET_KEY))
print("=================================")

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

# =========================
# FLASK
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Captcha earning bot is running!"


# =========================
# HELPER FUNCTIONS
# =========================

def get_user(telegram_id):
    try:
        response = (
            supabase
            .table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )

        if response.data:
            return response.data[0]

    except Exception as e:
        print("Supabase get_user error:", e)

    return None


def create_user(update: Update):
    telegram_user = update.effective_user

    if telegram_user is None:
        return None

    telegram_id = telegram_user.id
    username = telegram_user.username

    existing_user = get_user(telegram_id)

    if existing_user:
        return existing_user

    try:
        response = (
            supabase
            .table("users")
            .insert({
                "telegram_id": telegram_id,
                "username": username,
                "balance": 0
            })
            .execute()
        )

        if response.data:
            print("Created new user:", telegram_id)
            return response.data[0]

    except Exception as e:
        print("Supabase create_user error:", e)

    return None


# =========================
# /START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("=================================")
    print("RECEIVED /START")
    print("User:", update.effective_user.id)
    print("Username:", update.effective_user.username)
    print("=================================")

    user = create_user(update)

    if user:
        balance = user.get("balance", 0)
    else:
        balance = 0

    await update.message.reply_text(
        "🤖 Welcome to the Earning Bot!\n\n"
        "Use /task to complete a verification task.\n"
        "Use /balance to check your balance.\n\n"
        f"💰 Current balance: {balance} points"
    )


# =========================
# /BALANCE
# =========================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("RECEIVED /BALANCE")

    telegram_id = update.effective_user.id

    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    if user:
        user_balance = user.get("balance", 0)
    else:
        user_balance = 0

    await update.message.reply_text(
        f"💰 Your balance: {user_balance} points"
    )


# =========================
# /TASK
# =========================

async def task(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("RECEIVED /TASK")

    telegram_id = update.effective_user.id

    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    a = random.randint(1, 20)
    b = random.randint(1, 20)

    answer = a + b

    context.user_data["question"] = answer

    await update.message.reply_text(
        f"🧩 Verification task\n\n"
        f"What is {a} + {b}?\n\n"
        f"Reply with the answer."
    )


# =========================
# ANSWER HANDLER
# =========================

async def message_handler(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    print("RECEIVED TEXT MESSAGE")

    if update.effective_user is None:
        return

    if update.message is None:
        return

    telegram_id = update.effective_user.id

    question = context.user_data.get("question")

    if question is None:
        return

    try:
        answer = int(update.message.text.strip())
    except (ValueError, AttributeError):
        return

    if answer != question:
        await update.message.reply_text(
            "❌ Incorrect. Try again."
        )
        return

    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    if not user:
        await update.message.reply_text(
            "⚠️ Something went wrong. Please try /start again."
        )
        return

    current_balance = user.get("balance", 0)

    if current_balance is None:
        current_balance = 0

    new_balance = current_balance + 1

    try:
        (
            supabase
            .table("users")
            .update({
                "balance": new_balance
            })
            .eq("telegram_id", telegram_id)
            .execute()
        )

    except Exception as e:
        print("Supabase balance update error:", e)

        await update.message.reply_text(
            "⚠️ Could not update your balance. Please try again."
        )
        return

    context.user_data["question"] = None

    await update.message.reply_text(
        "✅ Correct!\n"
        "You earned 1 point.\n\n"
        f"💰 New balance: {new_balance} points\n\n"
        "Use /task for another task."
    )


# =========================
# UNKNOWN TEXT
# =========================

async def unknown_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    print("RECEIVED UNKNOWN MESSAGE")

    if update.message:
        await update.message.reply_text(
            "Please use /start, /task or /balance."
        )


# =========================
# ERROR HANDLER
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print("=================================")
    print("TELEGRAM ERROR:")
    print(context.error)
    print("=================================")


# =========================
# FLASK SERVER
# =========================

def run_flask():

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False,
        use_reloader=False
    )


# =========================
# MAIN BOT
# =========================

def main():

    print("Starting Flask server...")

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print("Building Telegram application...")

    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    application.add_handler(
        CommandHandler("start", start)
    )

    application.add_handler(
        CommandHandler("balance", balance)
    )

    application.add_handler(
        CommandHandler("task", task)
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            message_handler
        )
    )

    application.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND & ~filters.TEXT,
            unknown_message
        )
    )

    application.add_error_handler(error_handler)

    print("Telegram bot is starting...")
    print("Polling for Telegram updates...")

    # Start polling
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


# =========================
# START
# =========================

if __name__ == "__main__":
    main()
