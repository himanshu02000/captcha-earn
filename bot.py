import os
import random
import asyncio
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


# =========================================================
# ENVIRONMENT VARIABLES
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

print("=================================")
print("Starting Captcha Earn Bot")
print("BOT_TOKEN:", bool(BOT_TOKEN))
print("SUPABASE_URL:", bool(SUPABASE_URL))
print("SUPABASE_SECRET_KEY:", bool(SUPABASE_SECRET_KEY))
print("=================================")


# =========================================================
# SUPABASE
# =========================================================

try:

    supabase = create_client(
        SUPABASE_URL,
        SUPABASE_SECRET_KEY
    )

    print("Supabase client created successfully.")

except Exception as e:

    print("=================================")
    print("SUPABASE CLIENT ERROR:")
    print(repr(e))
    print("=================================")

    raise


# =========================================================
# FLASK
# =========================================================

app = Flask(__name__)


@app.route("/")
def home():
    return "Captcha earning bot is running!"


def run_flask():

    print("Starting Flask...")

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False
    )


# =========================================================
# DATABASE FUNCTIONS
# =========================================================

def get_user(telegram_id):

    print("=================================")
    print("GET USER")
    print("Telegram ID:", telegram_id)

    try:

        result = (
            supabase
            .table("users")
            .select("*")
            .eq("telegram_id", telegram_id)
            .limit(1)
            .execute()
        )

        print("GET USER RESULT:", result)

        if result.data:

            print("USER FOUND:", result.data[0])

            return result.data[0]

        print("USER NOT FOUND")

    except Exception as e:

        print("=================================")
        print("GET USER ERROR:")
        print(repr(e))
        print("=================================")

    return None


def create_user(update):

    print("=================================")
    print("CREATE USER")
    print("=================================")

    if not update.effective_user:

        print("CREATE USER ERROR: No Telegram user")

        return None

    telegram_id = update.effective_user.id
    username = update.effective_user.username

    print("Telegram ID:", telegram_id)
    print("Username:", username)

    # Check if user already exists
    existing = get_user(telegram_id)

    if existing:

        print("User already exists.")

        return existing

    try:

        data = {
            "telegram_id": telegram_id,
            "username": username,
            "balance": 0
        }

        print("INSERT DATA:", data)

        result = (
            supabase
            .table("users")
            .insert(data)
            .execute()
        )

        print("CREATE USER RESULT:", result)

        if result.data:

            print("=================================")
            print("NEW USER CREATED")
            print("Telegram ID:", telegram_id)
            print("=================================")

            return result.data[0]

    except Exception as e:

        print("=================================")
        print("CREATE USER ERROR:")
        print(repr(e))
        print("=================================")

    return None


# =========================================================
# /START
# =========================================================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    print("RECEIVED /START")

    if not update.message:
        return

    user = create_user(update)

    balance = 0

    if user:

        balance = user.get("balance", 0) or 0

    await update.message.reply_text(
        "🤖 Welcome to Captcha Earn!\n\n"
        "💰 Earn points by completing tasks.\n\n"
        "Commands:\n"
        "/task - Complete a task\n"
        "/balance - Check balance\n\n"
        f"💰 Balance: {balance} points"
    )


# =========================================================
# /BALANCE
# =========================================================

async def balance(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    print("RECEIVED /BALANCE")

    if not update.message or not update.effective_user:
        return

    telegram_id = update.effective_user.id

    user = get_user(telegram_id)

    if not user:

        user = create_user(update)

    if user:

        amount = user.get("balance", 0) or 0

    else:

        amount = 0

    await update.message.reply_text(
        f"💰 Your balance: {amount} points"
    )


# =========================================================
# /TASK
# =========================================================

async def task(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    print("=================================")
    print("RECEIVED /TASK")
    print("=================================")

    if not update.message or not update.effective_user:
        return

    telegram_id = update.effective_user.id

    print("TASK TELEGRAM ID:", telegram_id)

    user = get_user(telegram_id)

    if not user:

        print("TASK: User not found. Trying to create user.")

        user = create_user(update)

    if not user:

        print("=================================")
        print("TASK ERROR: USER ACCOUNT COULD NOT BE FOUND OR CREATED")
        print("Telegram ID:", telegram_id)
        print("=================================")

        await update.message.reply_text(
            "⚠️ Account error.\n"
            "Please use /start first."
        )

        return

    print("TASK: User account OK")

    # Generate simple verification question
    a = random.randint(1, 20)
    b = random.randint(1, 20)

    correct_answer = a + b

    # Store answer for this Telegram user
    context.user_data["answer"] = correct_answer

    print(
        "TASK CREATED:",
        a,
        "+",
        b,
        "=",
        correct_answer
    )

    await update.message.reply_text(
        "🧩 Verification Task\n\n"
        f"What is {a} + {b}?\n\n"
        "Reply with the answer."
    )


# =========================================================
# ANSWER
# =========================================================

async def answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    print("RECEIVED ANSWER")

    if not update.message:
        return

    if not update.effective_user:
        return

    if not update.message.text:
        return

    expected = context.user_data.get("answer")

    if expected is None:

        await update.message.reply_text(
            "Please use /task first."
        )

        return

    # Convert user's answer to integer
    try:

        user_answer = int(
            update.message.text.strip()
        )

    except ValueError:

        await update.message.reply_text(
            "❌ Please enter a number."
        )

        return

    # Wrong answer
    if user_answer != expected:

        context.user_data["answer"] = None

        await update.message.reply_text(
            "❌ Wrong answer.\n\n"
            "Use /task to try again."
        )

        return

    telegram_id = update.effective_user.id

    print("CORRECT ANSWER FROM:", telegram_id)

    user = get_user(telegram_id)

    if not user:

        print("ANSWER: User not found. Trying to create user.")

        user = create_user(update)

    if not user:

        print("ANSWER ERROR: Could not find/create account.")

        await update.message.reply_text(
            "⚠️ Account error."
        )

        return

    old_balance = user.get("balance", 0) or 0

    try:

        old_balance = float(old_balance)

    except (ValueError, TypeError):

        old_balance = 0

    new_balance = old_balance + 1

    print(
        "OLD BALANCE:",
        old_balance,
        "NEW BALANCE:",
        new_balance
    )

    # Update Supabase balance
    try:

        result = (
            supabase
            .table("users")
            .update({
                "balance": new_balance
            })
            .eq("telegram_id", telegram_id)
            .execute()
        )

        print("BALANCE UPDATE RESULT:", result)

        print(
            "BALANCE UPDATED:",
            telegram_id,
            new_balance
        )

    except Exception as e:

        print("=================================")
        print("BALANCE UPDATE ERROR:")
        print(repr(e))
        print("=================================")

        await update.message.reply_text(
            "⚠️ Could not update balance."
        )

        return

    # Clear task
    context.user_data["answer"] = None

    await update.message.reply_text(
        "✅ Correct!\n\n"
        "🎉 You earned 1 point!\n\n"
        f"💰 Balance: {new_balance} points"
    )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update: object,
    context: ContextTypes.DEFAULT_TYPE
):

    print("=================================")
    print("TELEGRAM ERROR:")
    print(repr(context.error))
    print("=================================")


# =========================================================
# MAIN
# =========================================================

def main():

    print("=================================")
    print("STARTING MAIN")
    print("=================================")

    # -----------------------------------------------------
    # Start Flask in background
    # -----------------------------------------------------

    print("Starting Flask thread...")

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    print("Flask thread started.")

    # -----------------------------------------------------
    # Python asyncio event loop
    # -----------------------------------------------------

    print("Creating asyncio event loop...")

    loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)

    print("Asyncio event loop created.")

    # -----------------------------------------------------
    # Create Telegram application
    # -----------------------------------------------------

    print("STEP 1: Creating Telegram application...")

    builder = Application.builder()

    print("STEP 2: Builder created.")

    builder = builder.token(BOT_TOKEN)

    print("STEP 3: Token added.")

    application = builder.build()

    print("STEP 4: Telegram application created.")

    # -----------------------------------------------------
    # Add handlers
    # -----------------------------------------------------

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

    application.add_error_handler(
        error_handler
    )

    print("=================================")
    print("ALL HANDLERS ADDED SUCCESSFULLY")
    print("=================================")

    # -----------------------------------------------------
    # Start Telegram polling
    # -----------------------------------------------------

    print("STEP 10: Starting Telegram polling...")

    try:

        application.run_polling(
            drop_pending_updates=True
        )

    except Exception as e:

        print("=================================")
        print("POLLING ERROR:")
        print(repr(e))
        print("=================================")

        raise

    finally:

        print("Telegram polling stopped.")


# =========================================================
# RUN PROGRAM
# =========================================================

if __name__ == "__main__":

    main()
