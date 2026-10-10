
import os
import sys
import asyncio
import hmac
import hashlib
import json
import time
import secrets
import threading
import random
import html
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

# Fix the missing event loop on Python 3.14+
if sys.version_info >= (3, 14):
    asyncio.set_event_loop(asyncio.new_event_loop())


# =========================================================
# CONFIGURATION
# =========================================================

BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MINI_APP_URL = "https://t.me/CaptchaEarnIndiaBot/earncoins"
CHANNEL_URL = "https://t.me/CaptchaEarnIndiaOfficial"

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
app = Flask(__name__)

challenges = {}
challenge_lock = threading.Lock()


# =========================================================
# TELEGRAM MINI APP AUTHENTICATION
# =========================================================

def verify_telegram_init_data(init_data):
    if not isinstance(init_data, str) or not init_data:
        return None

    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(parsed.items())
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
    user_data = verify_telegram_init_data(body.get("initData", ""))

    if not user_data:
        return None, None

    return user_data, int(user_data["id"])


# =========================================================
# DATABASE HELPERS
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
        if username and user.get("username") != username:
            try:
                (
                    supabase.table("users")
                    .update({"username": username})
                    .eq("telegram_id", telegram_id)
                    .execute()
                )
                user["username"] = username
            except Exception as exc:
                print("USERNAME UPDATE ERROR:", repr(exc))

        return user

    try:
        result = (
            supabase.table("users")
            .insert({
                "telegram_id": telegram_id,
                "username": username,
                "balance": 0,
                "earning_mode": "manual",
            })
            .execute()
        )

        if result.data:
            return result.data[0]

    except Exception as exc:
        print("CREATE USER ERROR:", repr(exc))

    return get_user(telegram_id)


def create_user(update):
    telegram_user = update.effective_user

    if telegram_user is None:
        return None

    return ensure_user(telegram_user.id, telegram_user.username)


def add_one_coin(telegram_id):
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


def set_earning_mode(telegram_id, mode):
    try:
        result = (
            supabase.table("users")
            .update({"earning_mode": mode})
            .eq("telegram_id", telegram_id)
            .execute()
        )
        return bool(result.data)

    except Exception as exc:
        print("MODE UPDATE ERROR:", repr(exc))
        return False


# =========================================================
# CAPTCHA GENERATION
# =========================================================

CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_captcha_text(length=5):
    return "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(length))


def make_captcha_svg(text):
    width, height = 560, 180

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">',
        '<rect width="100%" height="100%" rx="18" fill="#f7fafc"/>',
    ]

    for _ in range(90):
        x = secrets.randbelow(width)
        y = secrets.randbelow(height)
        r = 1 + secrets.randbelow(3)
        opacity = 0.15 + secrets.randbelow(45) / 100

        parts.append(
            f'<circle cx="{x}" cy="{y}" r="{r}" '
            f'fill="#334155" opacity="{opacity:.2f}"/>'
        )

    for _ in range(8):
        x1, y1 = secrets.randbelow(width), secrets.randbelow(height)
        x2, y2 = secrets.randbelow(width), secrets.randbelow(height)
        stroke_width = 1 + secrets.randbelow(3)

        parts.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="#64748b" stroke-width="{stroke_width}" opacity="0.45"/>'
        )

    for index, char in enumerate(text):
        x = 58 + index * 92
        y = 118 + secrets.randbelow(20) - 10
        rotation = secrets.randbelow(31) - 15
        skew = secrets.randbelow(15) - 7
        font_size = 74 + secrets.randbelow(13)

        parts.append(
            f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" '
            f'font-size="{font_size}px" font-weight="900" fill="#111827" '
            f'transform="rotate({rotation} {x} {y}) skewX({skew})">'
            f'{html.escape(char)}</text>'
        )

    parts.extend([
        '<path d="M10 40 C120 100,190 5,290 55 S450 125,550 35" '
        'fill="none" stroke="#1f2937" stroke-width="3" opacity="0.35"/>',
        '<path d="M5 145 C110 90,190 165,310 120 S450 55,555 135" '
        'fill="none" stroke="#475569" stroke-width="2" opacity="0.35"/>',
        "</svg>",
    ])

    return "".join(parts)


# =========================================================
# WEBSITE AND HEALTH CHECK
# =========================================================

@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200


# =========================================================
# MINI APP SESSION
# =========================================================

@app.route("/api/session", methods=["POST"])
def mini_app_session():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed. Reopen the app from Telegram.",
        }), 401

    user = ensure_user(telegram_id, user_data.get("username"))

    if user is None:
        return jsonify({"ok": False, "error": "Could not load your account."}), 500

    return jsonify({
        "ok": True,
        "name": user_data.get("first_name", "User"),
        "balance": user.get("balance", 0) or 0,
        "earning_mode": user.get("earning_mode", "manual") or "manual",
    })


# =========================================================
# MANUAL / AUTO MODE
# =========================================================

@app.route("/api/mode", methods=["POST"])
def mini_app_mode():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({"ok": False, "error": "Telegram authentication failed."}), 401

    body = request.get_json(silent=True) or {}
    mode = body.get("mode")

    if mode not in ("manual", "auto"):
        return jsonify({"ok": False, "error": "Invalid earning mode."}), 400

    user = ensure_user(telegram_id, user_data.get("username"))

    if user is None:
        return jsonify({"ok": False, "error": "Could not load your account."}), 500

    if not set_earning_mode(telegram_id, mode):
        return jsonify({"ok": False, "error": "Could not save your mode."}), 500

    # Invalidate existing CAPTCHA challenges when switching modes.
    with challenge_lock:
        expired_ids = [
            challenge_id
            for challenge_id, challenge in challenges.items()
            if challenge["telegram_id"] == telegram_id
        ]
        for challenge_id in expired_ids:
            challenges.pop(challenge_id, None)

    return jsonify({"ok": True, "earning_mode": mode})


# =========================================================
# CREATE MANUAL CAPTCHA
# =========================================================

@app.route("/api/challenge", methods=["POST"])
def mini_app_challenge():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({"ok": False, "error": "Telegram authentication failed."}), 401

    user = ensure_user(telegram_id, user_data.get("username"))

    if user is None:
        return jsonify({"ok": False, "error": "Could not load your account."}), 500

    if user.get("earning_mode", "manual") != "manual":
        return jsonify({
            "ok": False,
            "error": "Switch to Manual mode to solve CAPTCHAs.",
        }), 403

    captcha_text = make_captcha_text()
    challenge_id = secrets.token_urlsafe(24)

    with challenge_lock:
        challenges[challenge_id] = {
            "telegram_id": telegram_id,
            "answer": captcha_text,
            "expires": time.time() + 180,
            "attempts": 0,
        }

    return jsonify({
        "ok": True,
        "challenge_id": challenge_id,
        "captcha_svg": make_captcha_svg(captcha_text),
        "instruction": "Enter the 5 characters shown in the CAPTCHA.",
        "balance": user.get("balance", 0) or 0,
    })


# =========================================================
# SUBMIT MANUAL CAPTCHA ANSWER
# =========================================================

@app.route("/api/answer", methods=["POST"])
def mini_app_answer():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({"ok": False, "error": "Telegram authentication failed."}), 401

    user = ensure_user(telegram_id, user_data.get("username"))

    if user is None:
        return jsonify({"ok": False, "error": "Could not load your account."}), 500

    if user.get("earning_mode", "manual") != "manual":
        return jsonify({
            "ok": False,
            "error": "Switch to Manual mode to solve CAPTCHAs.",
        }), 403

    body = request.get_json(silent=True) or {}
    challenge_id = body.get("challenge_id")
    submitted_answer = body.get("answer", "")

    if not isinstance(challenge_id, str):
        return jsonify({"ok": False, "error": "Invalid challenge."}), 400

    if not isinstance(submitted_answer, str):
        submitted_answer = str(submitted_answer)

    submitted_answer = submitted_answer.strip().upper()

    with challenge_lock:
        challenge = challenges.get(challenge_id)

        if not challenge or challenge["telegram_id"] != telegram_id:
            return jsonify({
                "ok": False,
                "error": "Challenge not found. Start a new CAPTCHA.",
            }), 400

        if time.time() > challenge["expires"]:
            challenges.pop(challenge_id, None)
            return jsonify({
                "ok": False,
                "error": "CAPTCHA expired. Get a new CAPTCHA.",
            }), 400

        challenge["attempts"] += 1

        if challenge["attempts"] > 3:
            challenges.pop(challenge_id, None)
            return jsonify({
                "ok": False,
                "error": "Too many attempts. Get a new CAPTCHA.",
            }), 429

        if submitted_answer != challenge["answer"]:
            if challenge["attempts"] >= 3:
                challenges.pop(challenge_id, None)

            return jsonify({
                "ok": False,
                "error": "Incorrect CAPTCHA. Try again.",
            }), 400

        # A challenge can only be used once.
        challenges.pop(challenge_id, None)

    balance = add_one_coin(telegram_id)

    if balance is None:
        return jsonify({
            "ok": False,
            "error": "Could not save your reward. Please check your balance.",
        }), 500

    return jsonify({
        "ok": True,
        "correct": True,
        "message": "Correct! 1 coin earned.",
        "balance": balance,
    })


# =========================================================
# WITHDRAWAL API
# =========================================================

@app.route("/api/withdraw", methods=["POST"])
def request_withdrawal():
    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed. Reopen the app.",
        }), 401

    body = request.get_json(silent=True) or {}
    raw_coins = body.get("coins")
    upi = body.get("upi")

    if isinstance(raw_coins, bool):
        return jsonify({"ok": False, "error": "Enter a valid coin amount."}), 400

    try:
        coins = int(raw_coins)
    except (TypeError, ValueError, OverflowError):
        return jsonify({"ok": False, "error": "Enter a whole number of coins."}), 400

    if isinstance(raw_coins, float) and not raw_coins.is_integer():
        return jsonify({"ok": False, "error": "Enter a whole number of coins."}), 400

    if isinstance(raw_coins, str) and str(coins) != raw_coins.strip():
        return jsonify({"ok": False, "error": "Enter a valid whole number of coins."}), 400

    if coins <= 0 or coins > 1000000000:
        return jsonify({"ok": False, "error": "Invalid withdrawal amount."}), 400

    if coins % 50 != 0:
        return jsonify({
            "ok": False,
            "error": "The amount must be a multiple of 50 coins.",
        }), 400

    if not isinstance(upi, str):
        return jsonify({"ok": False, "error": "Enter your UPI ID."}), 400

    upi = upi.strip()

    if len(upi) < 3 or len(upi) > 200 or any(ch.isspace() for ch in upi):
        return jsonify({
            "ok": False,
            "error": "Enter a valid UPI ID without spaces.",
        }), 400

    try:
        result = supabase.rpc(
            "create_withdrawal",
            {
                "p_telegram_id": telegram_id,
                "p_coins": coins,
                "p_upi": upi,
            },
        ).execute()

        return jsonify({
            "ok": True,
            "message": "Withdrawal request submitted successfully!",
            "withdrawal_id": result.data,
            "coins": coins,
            "amount_inr": coins / 50,
            "status": "pending",
        }), 200

    except Exception as exc:
        print("WITHDRAWAL ERROR:", repr(exc))
        error_text = str(exc)

        if "Minimum withdrawal is" in error_text:
            message = (
                "Minimum withdrawal is 1,000 coins for your first "
                "five eligible requests, then 2,500 coins."
            )
            status = 400
        elif "Insufficient balance" in error_text:
            message = "You don't have enough coins for this withdrawal."
            status = 400
        elif "multiple of 50" in error_text:
            message = "The amount must be a multiple of 50 coins."
            status = 400
        elif "Invalid UPI details" in error_text:
            message = "Please enter valid UPI details."
            status = 400
        elif "User account not found" in error_text:
            message = "Your account was not found. Reopen the app and try again."
            status = 400
        else:
            message = "We couldn't submit your withdrawal. Please try again later."
            status = 500

        return jsonify({"ok": False, "error": message}), status


# =========================================================
# ADSGRAM REWARDS
# =========================================================

@app.route("/api/adsgram/reward", methods=["GET"])
def adsgram_reward():
    # Do not credit coins from an unverified/replayable browser callback.
    return jsonify({
        "ok": False,
        "error": (
            "Ad rewards are disabled until verified AdsGram reward "
            "confirmation is configured."
        ),
    }), 410


# =========================================================
# TELEGRAM BOT COMMANDS
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message is None or update.effective_user is None:
        return

    user = create_user(update)

    if user is None:
        await update.message.reply_text(
            "Your account could not be loaded. Please try /start again."
        )
        return

    amount = user.get("balance", 0) or 0

    keyboard = [[
        InlineKeyboardButton("🎮 Open Captcha Earn", url=MINI_APP_URL)
    ]]

    await update.message.reply_text(
        "💰 Welcome to Captcha Earn India!\n\n"
        "Complete available tasks and solve CAPTCHAs to earn coins.\n\n"
        f"📢 Official channel: {CHANNEL_URL}\n\n"
        "⏳ The app may take 30–60 seconds to load after inactivity.\n\n"
        f"💰 Your balance: {amount} coins\n\n"
        "⚠️ Withdrawals are subject to eligibility and approval.",
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

    await update.message.reply_text(
        f"💰 Your balance: {user.get('balance', 0) or 0} coins"
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
            "❌ Incorrect answer. Use /task to try again."
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
        "🎉 You earned 1 coin!\n\n"
        f"💰 Balance: {saved_balance} coins"
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print("TELEGRAM ERROR:", repr(context.error))


# =========================================================
# START SERVERS
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

    telegram_app = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("balance", balance))
    telegram_app.add_handler(CommandHandler("task", task))
    telegram_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, answer)
    )
    telegram_app.add_error_handler(error_handler)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    print("Starting Telegram polling...")

    try:
        loop.run_until_complete(telegram_app.initialize())

        if telegram_app.updater is None:
            raise RuntimeError("Telegram updater is unavailable.")

        loop.run_until_complete(
            telegram_app.updater.start_polling(
                drop_pending_updates=True
            )
        )

        loop.run_until_complete(telegram_app.start())

        print("Telegram bot started successfully.")
        loop.run_forever()

    except Exception as exc:
        print("BOT STARTUP/RUNTIME ERROR:", repr(exc))
        raise

    finally:
        if telegram_app.updater and telegram_app.updater.running:
            loop.run_until_complete(telegram_app.updater.stop())

        if telegram_app.running:
            loop.run_until_complete(telegram_app.stop())

        if telegram_app._initialized:
            loop.run_until_complete(telegram_app.shutdown())

        asyncio.set_event_loop(None)
        loop.close()


if __name__ == "__main__":
    main()
