
import os
import random
import threading

from flask import Flask, send_from_directory
from supabase import create_client

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print("=================================")
print("Starting Captcha Earn Bot")
print("BOT_TOKEN configured:", bool(BOT_TOKEN))
print("SUPABASE_URL configured:", bool(SUPABASE_URL))
print("SUPABASE_SECRET_KEY configured:", bool(SUPABASE_SECRET_KEY))
print("=================================")


# =========================================================
# SUPABASE
# =========================================================

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)


# =========================================================
# FLASK / MINI APP
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
    )


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

def get_user(telegram_id):
    try:
        result = (
            supabase.table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        print("GET USER ERROR:", repr(e))
        return None


def create_user(update):
    telegram_user = update.effective_user
    if not telegram_user:
        return None

    telegram_id = telegram_user.id
    existing = get_user(telegram_id)

    if existing:
        return existing

    try:
        result = (
            supabase.table("users")
            .insert({
                "telegram_id": telegram_id,
                "username": telegram_user.username,
                "balance": 0,
            })
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        print("CREATE USER ERROR:", repr(e))
        return None


# =========================================================
# /START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user = create_user(update)
    balance = user.get("balance", 0) if user else 0

    keyboard = [[
        InlineKeyboardButton(
            "🎮 Open Captcha Earn",
            url="https://t.me/CaptchaEarnIndiaBot/earncoins",
        )
    ]]

    await update.message.reply_text(
        "🤖 Welcome to Captcha Earn!\n\n"
        "💰 Earn points by completing tasks.\n\n"
        "/task - Complete a verification task\n"
        "/balance - Check your balance\n\n"
        f"💰 Balance: {balance} points",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# /BALANCE
# =========================================================

async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    amount = user.get("balance", 0) if user else 0

    await update.message.reply_text(
        f"💰 Your balance: {amount} points"
    )


# =========================================================
# /TASK
# =========================================================

async def task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    user = get_user(update.effective_user.id)

    if not user:
        user = create_user(update)

    if not user:
        await update.message.reply_text(
            "⚠️ Could not load your account. Please try /start again."
        )
        return

    a = random.randint(1, 20)
    b = random.randint(1, 20)

    context.user_data["answer"] = a + b

    await update.message.reply_text(
        "🧩 Verification Task\n\n"
        f"What is {a} + {b}?\n\n"
        "Reply with the answer."
    )


# =========================================================
# ANSWER
# =========================================================

async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user:
        return

    if not update.message.text:
        return

    expected = context.user_data.get("answer")

    if expected is None:
        await update.message.reply_text("Please use /task first.")
        return

    try:
        user_answer = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("❌ Please enter a number.")
        return

    if user_answer != expected:
        context.user_data["answer"] = None
        await update.message.reply_text(
            "❌ Wrong answer.\nUse /task to try again."
        )
        return

    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if not user:
        user = create_user(update)

    if not user:
        await update.message.reply_text("⚠️ Account error.")
        return

    try:
        old_balance = float(user.get("balance", 0) or 0)
        new_balance = old_balance + 1

        result = (
            supabase.table("users")
            .update({"balance": new_balance})
            .eq("telegram_id", telegram_id)
            .execute()
        )

        if not result.data:
            await update.message.reply_text(
                "⚠️ Balance update could not be confirmed. Please try again later."
            )
            return

    except Exception as e:
        print("BALANCE UPDATE ERROR:", repr(e))
        await update.message.reply_text(
            "⚠️ Could not update your balance."
        )
        return

    context.user_data["answer"] = None

    await update.message.reply_text(
        "✅ Correct!\n\n"
        "🎉 You earned 1 point!\n\n"
        f"💰 Balance: {new_balance:g} points"
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("TELEGRAM ERROR:", repr(context.error))


# =========================================================
# MAIN
# =========================================================

def main():
    # Run Flask in the background.
    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True,
    )
    flask_thread.start()

    # Create Telegram application.
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("task", task))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, answer)
    )

    application.add_error_handler(error_handler)

    print("Bot startup complete; starting Telegram polling.")

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
