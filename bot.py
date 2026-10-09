
import os
import asyncio
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
# CONFIGURATION
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MINI_APP_URL = "https://captcha-earning-bot.onrender.com"

print("Starting Captcha Earn Bot...")
print("Bot token configured:", bool(BOT_TOKEN))
print("Supabase URL configured:", bool(SUPABASE_URL))
print("Supabase key configured:", bool(SUPABASE_SECRET_KEY))


# =========================================================
# SUPABASE
# =========================================================

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY,
)

print("Supabase client initialized.")


# =========================================================
# FLASK WEBSITE
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/health")
def health():
    return {"status": "ok"}, 200


def run_flask():
    port = int(os.environ.get("PORT", "10000"))

    print("Starting Flask on port", port)

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
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

        if result.data:
            return result.data[0]

        return None

    except Exception as exc:
        print("GET USER ERROR:", repr(exc))
        return None


def create_user(update):
    telegram_user = update.effective_user

    if telegram_user is None:
        return None

    telegram_id = telegram_user.id

    existing_user = get_user(telegram_id)

    if existing_user:
        return existing_user

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

        if result.data:
            return result.data[0]

        # A concurrent request may have created this account.
        return get_user(telegram_id)

    except Exception as exc:
        print("CREATE USER ERROR:", repr(exc))

        # Handle a possible duplicate-account race.
        return get_user(telegram_id)


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message is None or update.effective_user is None:
        return

    user = create_user(update)

    if user is None:
        await update.message.reply_text(
            "Sorry, your account could not be loaded. Please try /start again."
        )
        return

    amount = user.get("balance", 0) or 0

    keyboard = [[
        InlineKeyboardButton(
            "🎮 Open Captcha Earn",
            url="https://t.me/CaptchaEarnIndiaBot/earncoins",
        )
    ]]

    await update.message.reply_text(
        "🤖 Welcome to Captcha Earn!\n\n"
        "Complete verification tasks to earn points.\n\n"
        "/task - Start a task\n"
        "/balance - Check your balance\n\n"
        f"💰 Your balance: {amount} points",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


# =========================================================
# /BALANCE
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message is None or update.effective_user is None:
        return

    user = get_user(update.effective_user.id)

    if user is None:
        user = create_user(update)

    if user is None:
        await update.message.reply_text(
            "Your account could not be loaded. Please try /start."
        )
        return

    amount = user.get("balance", 0) or 0

    await update.message.reply_text(
        f"💰 Your balance: {amount} points"
    )


# =========================================================
# /TASK
# =========================================================

async def task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message is None or update.effective_user is None:
        return

    user = get_user(update.effective_user.id)

    if user is None:
        user = create_user(update)

    if user is None:
        await update.message.reply_text(
            "Account error. Please try /start again."
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
# ANSWER AND REWARD
# =========================================================

async def answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    if update.message is None or update.effective_user is None:
        return

    if not update.message.text:
        return

    expected = context.user_data.get("answer")

    if expected is None:
        await update.message.reply_text(
            "Please use /task first."
        )
        return

    try:
        submitted_answer = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text(
            "Please enter a number."
        )
        return

    if submitted_answer != expected:
        context.user_data.pop("answer", None)

        await update.message.reply_text(
            "❌ Incorrect answer.\nUse /task to try again."
        )
        return

    telegram_id = update.effective_user.id
    user = get_user(telegram_id)

    if user is None:
        user = create_user(update)

    if user is None:
        await update.message.reply_text(
            "Account error. Please try /start again."
        )
        return

    try:
        old_balance = float(user.get("balance", 0) or 0)
        new_balance = old_balance + 1

        result = (
            supabase.table("users")
            .update({"balance": new_balance})
            .eq("telegram_id", telegram_id)
            .select("telegram_id", "balance")
            .execute()
        )

        if not result.data:
            await update.message.reply_text(
                "The balance update could not be confirmed. "
                "Please check /balance before trying again."
            )
            return

        saved_balance = result.data[0].get("balance", new_balance)

    except Exception as exc:
        print("BALANCE UPDATE ERROR:", repr(exc))

        await update.message.reply_text(
            "Could not update your balance. Please try again later."
        )
        return

    context.user_data.pop("answer", None)

    await update.message.reply_text(
        "✅ Correct answer!\n\n"
        "🎉 You earned 1 point!\n\n"
        f"💰 Balance: {saved_balance} points"
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    print("TELEGRAM ERROR:", repr(context.error))


# =========================================================
# MAIN
# =========================================================

def main():
    # Start Flask once, in a background thread.
    flask_thread = threading.Thread(
        target=run_flask,
        name="flask-server",
        daemon=True,
    )
    flask_thread.start()

    # Configure Telegram handlers.
    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("task", task))

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            answer,
        )
    )

    application.add_error_handler(error_handler)

    # Python 3.14 compatibility:
    # Explicitly create and install the event loop before polling.
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    print("Event loop initialized.")
    print("Starting Telegram polling...")

    try:
        application.run_polling(
            drop_pending_updates=True,
        )
    finally:
        if not loop.is_closed():
            loop.close()

        asyncio.set_event_loop(None)
        print("Telegram polling stopped.")


if __name__ == "__main__":
    main()
