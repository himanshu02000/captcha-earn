import os
import random
import threading

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

# =========================
# SUPABASE
# =========================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

# =========================
# FLASK SERVER
# =========================

app = Flask(__name__)


@app.route("/")
def home():
    return "Captcha earning bot is running!"


def run_flask():
    print("Starting Flask server...")

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False,
        use_reloader=False
    )


# =========================
# DATABASE FUNCTIONS
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
        print("Database get_user error:", e)

    return None


def create_user(update: Update):
    if update.effective_user is None:
        return None

    telegram_user = update.effective_user

    telegram_id = telegram_user.id
    username = telegram_user.username

    # Check if user already exists
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
            print("New user created:", telegram_id)
            return response.data[0]

    except Exception as e:
        print("Database create_user error:", e)

    return None


# =========================
# /START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("=================================")
    print("RECEIVED /START")
    print("Telegram ID:", update.effective_user.id)
    print("Username:", update.effective_user.username)
    print("=================================")

    user = create_user(update)

    if user:
        balance = user.get("balance", 0)
    else:
        balance = 0

    await update.message.reply_text(
        "🤖 Welcome to Captcha Earn!\n\n"
        "💰 Earn points by completing tasks.\n\n"
        "🧩 /task - Complete a task\n"
        "💰 /balance - Check your balance\n\n"
        f"Your balance: {balance} points"
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

    if not user:
        await update.message.reply_text(
            "⚠️ Could not create your account.\n"
            "Please try /start again."
        )
        return

    # Generate simple verification task
    a = random.randint(1, 20)
    b = random.randint(1, 20)

    correct_answer = a + b

    # Save answer for this Telegram user
    context.user_data["correct_answer"] = correct_answer

    await update.message.reply_text(
        "🧩 Verification Task\n\n"
        f"What is {a} + {b}?\n\n"
        "Reply with the answer."
    )


# =========================
# TEXT ANSWER
# =========================

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("RECEIVED TEXT MESSAGE")

    if update.effective_user is None:
        return

    if update.message is None:
        return

    telegram_id = update.effective_user.id

    correct_answer = context.user_data.get("correct_answer")

    # No active task
    if correct_answer is None:
        await update.message.reply_text(
            "Please use /task first."
        )
        return

    try:
        user_answer = int(update.message.text.strip())

    except (ValueError, AttributeError):

        await update.message.reply_text(
            "❌ Please enter only the number."
        )

        return

    # Wrong answer
    if user_answer != correct_answer:

        await update.message.reply_text(
            "❌ Incorrect answer.\n\n"
            "Use /task to get a new task."
        )

        context.user_data["correct_answer"] = None

        return

    # =========================
    # CORRECT ANSWER
    # =========================

    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    if not user:

        await update.message.reply_text(
            "⚠️ Something went wrong.\n"
            "Please try /start again."
        )

        return

    current_balance = user.get("balance", 0)

    if current_balance is None:
        current_balance = 0

    # Convert safely to number
    try:
        current_balance = float(current_balance)
    except:
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

        print(
            "Balance updated:",
            telegram_id,
            "=>",
            new_balance
        )

    except Exception as e:

        print(
            "Database balance update error:",
            e
        )

        await update.message.reply_text(
            "⚠️ Could not update your balance.\n"
            "Please try again."
        )

        return

    # Clear task
    context.user_data["correct_answer"] = None

    await update.message.reply_text(
        "✅ Correct!\n\n"
        "🎉 You earned 1 point.\n\n"
        f"💰 New balance: {new_balance} points\n\n"
        "Use /task for another task."
    )


# =========================
# ERROR HANDLER
# =========================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print("=================================")
    print("TELEGRAM ERROR")
    print(context.error)
    print("=================================")


# =========================
# MAIN BOT
# =========================

def main():

    # Start Flask in background
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print("Flask server started.")
    print("Building Telegram application...")

    # Build Telegram application
    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )

    print("Telegram application created.")

    # =========================
    # HANDLERS
    # =========================

    print("Adding /start handler...")

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    print("Adding /balance handler...")

    application.add_handler(
        CommandHandler(
            "balance",
            balance
        )
    )

    print("Adding /task handler...")

    application.add_handler(
        CommandHandler(
            "task",
            task
        )
    )

    print("Adding text message handler...")

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_answer
        )
    )

    print("Adding error handler...")

    application.add_error_handler(
        error_handler
    )

    print("=================================")
    print("ALL TELEGRAM HANDLERS ADDED")
    print("=================================")

    print("Telegram bot is starting...")
    print("Polling for Telegram updates...")

    # Start Telegram polling
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )


# =========================
# START PROGRAM
# =========================

if __name__ == "__main__":
    main()
