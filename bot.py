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
print("Starting Captcha Earn Bot")
print("BOT_TOKEN:", bool(BOT_TOKEN))
print("SUPABASE_URL:", bool(SUPABASE_URL))
print("SUPABASE_SECRET_KEY:", bool(SUPABASE_SECRET_KEY))
print("=================================")

# =========================
# SUPABASE
# =========================

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


def run_flask():
    print("Starting Flask...")

    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        debug=False,
        use_reloader=False
    )


# =========================
# DATABASE
# =========================

def get_user(telegram_id):

    try:
        result = (
            supabase
            .table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as e:
        print("GET USER ERROR:", e)

    return None


def create_user(update):

    if not update.effective_user:
        return None

    telegram_id = update.effective_user.id
    username = update.effective_user.username

    existing = get_user(telegram_id)

    if existing:
        return existing

    try:

        result = (
            supabase
            .table("users")
            .insert({
                "telegram_id": telegram_id,
                "username": username,
                "balance": 0
            })
            .execute()
        )

        if result.data:
            print("NEW USER CREATED:", telegram_id)
            return result.data[0]

    except Exception as e:
        print("CREATE USER ERROR:", e)

    return None


# =========================
# START
# =========================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("RECEIVED /START")

    user = create_user(update)

    balance = 0

    if user:
        balance = user.get("balance", 0)

    await update.message.reply_text(
        "🤖 Welcome to Captcha Earn!\n\n"
        "💰 Earn points by completing tasks.\n\n"
        "/task - Complete a task\n"
        "/balance - Check balance\n\n"
        f"💰 Balance: {balance} points"
    )


# =========================
# BALANCE
# =========================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("RECEIVED /BALANCE")

    telegram_id = update.effective_user.id

    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    if user:
        amount = user.get("balance", 0)
    else:
        amount = 0

    await update.message.reply_text(
        f"💰 Your balance: {amount} points"
    )


# =========================
# TASK
# =========================

async def task(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("RECEIVED /TASK")

    user = get_user(update.effective_user.id)

    if not user:
        user = create_user(update)

    if not user:
        await update.message.reply_text(
            "⚠️ Account error. Please use /start first."
        )
        return

    a = random.randint(1, 20)
    b = random.randint(1, 20)

    correct_answer = a + b

    context.user_data["answer"] = correct_answer

    await update.message.reply_text(
        "🧩 Verification Task\n\n"
        f"What is {a} + {b}?\n\n"
        "Reply with the answer."
    )


# =========================
# ANSWER
# =========================

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("RECEIVED ANSWER")

    if not update.message:
        return

    expected = context.user_data.get("answer")

    if expected is None:
        await update.message.reply_text(
            "Please use /task first."
        )
        return

    try:
        user_answer = int(
            update.message.text.strip()
        )
    except:
        await update.message.reply_text(
            "❌ Please enter a number."
        )
        return

    if user_answer != expected:

        context.user_data["answer"] = None

        await update.message.reply_text(
            "❌ Wrong answer.\n\n"
            "Use /task to try again."
        )

        return

    telegram_id = update.effective_user.id

    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    if not user:
        await update.message.reply_text(
            "⚠️ Account error."
        )
        return

    old_balance = user.get("balance", 0) or 0

    new_balance = float(old_balance) + 1

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

        print("BALANCE UPDATE ERROR:", e)

        await update.message.reply_text(
            "⚠️ Could not update balance."
        )

        return

    context.user_data["answer"] = None

    await update.message.reply_text(
        "✅ Correct!\n\n"
        "🎉 You earned 1 point!\n\n"
        f"💰 Balance: {new_balance} points"
    )


# =========================
# ERROR
# =========================

async def error(update, context):

    print("=================================")
    print("TELEGRAM ERROR:")
    print(context.error)
    print("=================================")


# =========================
# MAIN
# =========================

def main():

    print("Starting Flask thread...")

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print("Flask thread started.")

    # IMPORTANT:
    # Create Telegram application
    print("STEP 1: Creating Telegram application...")

    builder = Application.builder()

    print("STEP 2: Builder created.")

    builder = builder.token(BOT_TOKEN)

    print("STEP 3: Token added.")

    application = builder.build()

    print("STEP 4: Telegram application created.")

    # =========================
    # HANDLERS
    # =========================

    print("STEP 5: Adding /start...")

    application.add_handler(
        CommandHandler("start", start)
    )

    print("STEP 6: Adding /balance...")

    application.add_handler(
        CommandHandler("balance", balance)
    )

    print("STEP 7: Adding /task...")

    application.add_handler(
        CommandHandler("task", task)
    )

    print("STEP 8: Adding text handler...")

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            answer
        )
    )

    print("STEP 9: Adding error handler...")

    application.add_error_handler(error)

    print("=================================")
    print("ALL HANDLERS ADDED SUCCESSFULLY")
    print("=================================")

    print("STEP 10: Starting Telegram polling...")

    application.run_polling(
        drop_pending_updates=True
    )


# =========================
# RUN
# =========================

if __name__ == "__main__":
    main()
