import os
import asyncio
import hmac
import hashlib
import json
import time
import secrets
import threading
from urllib.parse import parse_qsl

from flask import Flask, request, jsonify, send_from_directory
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
MINI_APP_URL = "https://t.me/CaptchaEarnIndiaBot/earncoins"

print("Starting Captcha Earn Bot...")

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)

# Temporary challenge storage. Challenges expire and are
# lost if the server restarts.
challenges = {}
challenge_lock = threading.Lock()

app = Flask(__name__)


# =========================================================
# TELEGRAM MINI APP AUTHENTICATION
# =========================================================

def verify_telegram_init_data(init_data):
    if not init_data or not isinstance(init_data, str):
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))

        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(parsed.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode("utf-8"),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(parsed.get("auth_date", "0"))
        now = int(time.time())

        # Reject expired or implausibly future-dated sessions.
        if auth_date <= 0 or now - auth_date > 86400 or auth_date > now + 60:
            return None

        user_data = json.loads(parsed.get("user", "{}"))

        if not isinstance(user_data, dict) or not user_data.get("id"):
            return None

        return user_data

    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def authenticated_user():
    body = request.get_json(silent=True) or {}
    init_data = body.get("initData", "")
    user_data = verify_telegram_init_data(init_data)

    if not user_data:
        return None, None

    return user_data, int(user_data["id"])


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

    except Exception as exc:
        print("GET USER ERROR:", repr(exc))
        return None


def ensure_user(telegram_id, username=None):
    user = get_user(telegram_id)

    if user:
        # Keep the username current when Telegram provides one.
        if username and user.get("username") != username:
            try:
                supabase.table("users").update(
                    {"username": username}
                ).eq("telegram_id", telegram_id).execute()
            except Exception as exc:
                print("USERNAME UPDATE ERROR:", repr(exc))

            user["username"] = username

        return user

    try:
        result = (
            supabase.table("users")
            .insert({
                "telegram_id": telegram_id,
                "username": username,
                "balance": 0,
            })
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as exc:
        print("CREATE USER ERROR:", repr(exc))

    # Handles an account created by another request at the same time.
    return get_user(telegram_id)


def create_user(update):
    telegram_user = update.effective_user

    if telegram_user is None:
        return None

    return ensure_user(
        telegram_user.id,
        telegram_user.username,
    )


def add_one_coin(telegram_id):
    """
    Basic balance update. For stronger concurrency protection,
    replace this with an atomic PostgreSQL RPC function before
    handling significant reward volume.
    """
    user = get_user(telegram_id)

    if user is None:
        return None

    try:
        old_balance = float(user.get("balance", 0) or 0)
        new_balance = old_balance + 1

        result = (
            supabase.table("users")
            .update({"balance": new_balance})
            .eq("telegram_id", telegram_id)
            .select("telegram_id, balance")
            .execute()
        )

        if not result.data:
            return None

        return result.data[0].get("balance", new_balance)

    except Exception as exc:
        print("BALANCE UPDATE ERROR:", repr(exc))
        return None


# =========================================================
# FLASK WEBSITE
# =========================================================

@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# =========================================================
# MINI APP API
# =========================================================

@app.route("/api/session", methods=["POST"])
def mini_app_session():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed. Reopen the app from Telegram."
        }), 401

    user = ensure_user(
        telegram_id,
        user_data.get("username"),
    )

    if user is None:
        return jsonify({
            "ok": False,
            "error": "Could not load your account."
        }), 500

    return jsonify({
        "ok": True,
        "name": user_data.get("first_name", "User"),
        "balance": user.get("balance", 0) or 0,
    })


@app.route("/api/challenge", methods=["POST"])
def mini_app_challenge():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed."
        }), 401

    user = ensure_user(
        telegram_id,
        user_data.get("username"),
    )

    if user is None:
        return jsonify({
            "ok": False,
            "error": "Could not load your account."
        }), 500

    a = secrets.randbelow(9) + 1
    b = secrets.randbelow(9) + 1
    challenge_id = secrets.token_urlsafe(24)

    with challenge_lock:
        challenges[challenge_id] = {
            "telegram_id": telegram_id,
            "answer": a + b,
            "expires": time.time() + 180,
            "attempts": 0,
        }

    return jsonify({
        "ok": True,
        "challenge_id": challenge_id,
        "question": f"What is {a} + {b}?",
        "balance": user.get("balance", 0) or 0,
    })


@app.route("/api/answer", methods=["POST"])
def mini_app_answer():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed."
        }), 401

    body = request.get_json(silent=True) or {}
    challenge_id = body.get("challenge_id")
    submitted_answer = body.get("answer")

    if not isinstance(challenge_id, str):
        return jsonify({"ok": False, "error": "Invalid challenge."}), 400

    try:
        submitted_answer = int(submitted_answer)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Enter a valid number."}), 400

    with challenge_lock:
        challenge = challenges.get(challenge_id)

        if not challenge or challenge["telegram_id"] != telegram_id:
            return jsonify({
                "ok": False,
                "error": "Challenge not found. Start a new challenge."
            }), 400

        if time.time() > challenge["expires"]:
            challenges.pop(challenge_id, None)
            return jsonify({
                "ok": False,
                "error": "Challenge expired. Start a new one."
            }), 400

        challenge["attempts"] += 1

        if challenge["attempts"] > 3:
            challenges.pop(challenge_id, None)
            return jsonify({
                "ok": False,
                "error": "Too many attempts. Start a new challenge."
            }), 429

        if submitted_answer != challenge["answer"]:
            if challenge["attempts"] >= 3:
                challenges.pop(challenge_id, None)

            return jsonify({
                "ok": False,
                "error": "Incorrect answer. Try again."
            }), 400

        # Consume the challenge before awarding a reward so it
        # cannot be submitted twice.
        challenges.pop(challenge_id, None)

    balance = add_one_coin(telegram_id)

    if balance is None:
        return jsonify({
            "ok": False,
            "error": "Could not save your reward. Please check your balance."
        }), 500

    return jsonify({
        "ok": True,
        "message": "Correct! 1 coin earned.",
        "balance": balance,
    })


# =========================================================
# TELEGRAM BOT COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            url=MINI_APP_URL,
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


async def balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def task(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return

    if not update.message.text:
        return

    expected = context.user_data.get("answer")

    if expected is None:
        await update.message.reply_text("Please use /task first.")
        return

    try:
        submitted_answer = int(update.message.text.strip())
    except ValueError:
        await update.message.reply_text("Please enter a number.")
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

    saved_balance = add_one_coin(telegram_id)

    if saved_balance is None:
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


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("TELEGRAM ERROR:", repr(context.error))


# =========================================================
# MAIN
# =========================================================

def run_flask():
    port = int(os.environ.get("PORT", "10000"))

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False,
        use_reloader=False,
        threaded=True,
    )


def main():
    flask_thread = threading.Thread(
        target=run_flask,
        name="flask-server",
        daemon=True,
    )
    flask_thread.start()

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("balance", balance))
    application.add_handler(CommandHandler("task", task))
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, answer)
    )
    application.add_error_handler(error_handler)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    print("Starting Telegram polling...")

    try:
        application.run_polling(drop_pending_updates=True)
    finally:
        if not loop.is_closed():
            loop.close()
        asyncio.set_event_loop(None)


if __name__ == "__main__":
    main()
