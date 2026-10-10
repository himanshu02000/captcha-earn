
import os
import time
import random
import html
import threading
from urllib.parse import parse_qsl

from flask import Flask, request, jsonify, send_from_directory
from supabase import create_client

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

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


def verify_telegram_init_data(init_data):
    if not init_data or not isinstance(init_data, str):
        return None

    try:
        from urllib.parse import unquote
        import hashlib
        import hmac
        import json

        values = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = values.pop("hash", None)

        if not received_hash:
            return None

        data_check_string = "\n".join(
            f"{key}={value}" for key, value in sorted(values.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            BOT_TOKEN.encode(),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(calculated_hash, received_hash):
            return None

        auth_date = int(values.get("auth_date", "0"))
        now = int(time.time())

        if auth_date <= 0 or now - auth_date > 86400 or auth_date > now + 60:
            return None

        user_json = values.get("user")
        if not user_json:
            return None

        user_data = json.loads(user_json)
        telegram_id = int(user_data["id"])

        return {
            "user": user_data,
            "telegram_id": telegram_id,
        }

    except (ValueError, TypeError, KeyError):
        return None
    except Exception:
        app.logger.exception("Telegram initData verification failed")
        return None


def authenticated_user():
    body = request.get_json(silent=True) or {}
    verified = verify_telegram_init_data(body.get("initData", ""))

    if not verified:
        return None, None, (
            jsonify({"ok": False, "error": "Telegram verification failed. "
                                          "Reopen the Mini App and try again."}),
            401,
        )

    return verified["user"], verified["telegram_id"], None


def get_user(telegram_id):
    result = (
        supabase.table("users")
        .select("*")
        .eq("telegram_id", telegram_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def ensure_user(telegram_id, username=None):
    user = get_user(telegram_id)

    if user is None:
        result = supabase.table("users").insert({
            "telegram_id": telegram_id,
            "username": username,
            "balance": 0,
            "earning_mode": "manual",
        }).execute()

        if result.data:
            return result.data[0]

        return get_user(telegram_id)

    if username and user.get("username") != username:
        supabase.table("users").update({
            "username": username,
        }).eq("telegram_id", telegram_id).execute()
        user["username"] = username

    return user


def add_one_coin(telegram_id):
    # Kept for the existing manual CAPTCHA and Telegram math task.
    user = get_user(telegram_id)

    if user is None:
        raise ValueError("User account not found.")

    current_balance = float(user.get("balance") or 0)
    new_balance = current_balance + 1

    result = (
        supabase.table("users")
        .update({"balance": new_balance})
        .eq("telegram_id", telegram_id)
        .execute()
    )

    if not result.data:
        raise RuntimeError("Could not update the balance.")

    return float(result.data[0].get("balance") or new_balance)


def make_captcha_svg(answer):
    width, height = 360, 130
    pieces = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        f'<rect width="{width}" height="{height}" rx="12" fill="#f7fafc"/>',
    ]

    for _ in range(24):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        color = random.choice(["#d5e1ef", "#c4d5e8", "#e0e9f3"])
        pieces.append(
            f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" '
            f'stroke="{color}" stroke-width="1.5"/>'
        )

    for index, character in enumerate(answer):
        x = 39 + index * 57
        y = random.randint(70, 88)
        rotation = random.randint(-18, 18)
        pieces.append(
            f'<text x="{x}" y="{y}" '
            f'transform="rotate({rotation} {x} {y})" '
            f'font-family="Arial,sans-serif" font-size="38" '
            f'font-weight="bold" fill="#1769d3">'
            f'{html.escape(character)}</text>'
        )

    pieces.append("</svg>")
    return "".join(pieces)


@app.get("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")


@app.get("/health")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/session")
def api_session():
    user_data, telegram_id, error = authenticated_user()
    if error:
        return error

    try:
        user = ensure_user(
            telegram_id,
            user_data.get("username"),
        )

        if user is None:
            raise RuntimeError("Could not create or load your account.")

        return jsonify({
            "ok": True,
            "name": user_data.get("first_name") or user.get("username") or "User",
            "balance": float(user.get("balance") or 0),
            "earning_mode": user.get("earning_mode") or "manual",
        })

    except Exception:
        app.logger.exception("Session request failed")
        return jsonify({
            "ok": False,
            "error": "Could not load your account. Please try again.",
        }), 500


@app.post("/api/mode")
def api_mode():
    user_data, telegram_id, error = authenticated_user()
    if error:
        return error

    body = request.get_json(silent=True) or {}
    mode = body.get("mode")

    if mode not in ("manual", "auto"):
        return jsonify({
            "ok": False,
            "error": "Choose Manual or Auto mode.",
        }), 400

    try:
        ensure_user(telegram_id, user_data.get("username"))

        result = (
            supabase.table("users")
            .update({"earning_mode": mode})
            .eq("telegram_id", telegram_id)
            .execute()
        )

        if not result.data:
            return jsonify({
                "ok": False,
                "error": "Could not save your selected mode.",
            }), 500

        # Invalidate any outstanding manual challenge when changing modes.
        with challenge_lock:
            for challenge_id in list(challenges):
                if challenges[challenge_id]["telegram_id"] == telegram_id:
                    del challenges[challenge_id]

        return jsonify({"ok": True, "mode": mode})

    except Exception:
        app.logger.exception("Mode update failed")
        return jsonify({
            "ok": False,
            "error": "Could not change mode. Please try again.",
        }), 500


@app.post("/api/challenge")
def api_challenge():
    user_data, telegram_id, error = authenticated_user()
    if error:
        return error

    try:
        user = ensure_user(telegram_id, user_data.get("username"))

        if (user.get("earning_mode") or "manual") != "manual":
            return jsonify({
                "ok": False,
                "error": "Switch to Manual mode to solve earning CAPTCHAs.",
            }), 409

        answer = "".join(
            random.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789")
            for _ in range(5)
        )

        # A random challenge ID prevents users from guessing another challenge.
        import secrets
        challenge_id = secrets.token_urlsafe(24)

        with challenge_lock:
            # Expire old challenges and limit stored entries.
            now = time.time()
            for old_id in list(challenges):
                if challenges[old_id]["expires"] < now:
                    del challenges[old_id]

            if len(challenges) > 5000:
                challenges.clear()

            challenges[challenge_id] = {
                "telegram_id": telegram_id,
                "answer": answer,
                "expires": now + 180,
                "attempts": 0,
            }

        return jsonify({
            "ok": True,
            "challenge_id": challenge_id,
            "captcha_svg": make_captcha_svg(answer),
            "instruction": "Enter the five characters shown.",
            "balance": float(user.get("balance") or 0),
        })

    except Exception:
        app.logger.exception("Challenge generation failed")
        return jsonify({
            "ok": False,
            "error": "Could not create a CAPTCHA. Please try again.",
        }), 500


@app.post("/api/answer")
def api_answer():
    user_data, telegram_id, error = authenticated_user()
    if error:
        return error

    body = request.get_json(silent=True) or {}
    challenge_id = body.get("challenge_id")
    answer = str(body.get("answer", "")).strip().upper()

    if not challenge_id or len(answer) != 5:
        return jsonify({
            "ok": False,
            "error": "Enter all five CAPTCHA characters.",
        }), 400

    try:
        user = ensure_user(telegram_id, user_data.get("username"))

        if (user.get("earning_mode") or "manual") != "manual":
            return jsonify({
                "ok": False,
                "error": "Switch to Manual mode before submitting a CAPTCHA.",
            }), 409

        with challenge_lock:
            challenge = challenges.get(challenge_id)

            if not challenge or challenge["telegram_id"] != telegram_id:
                return jsonify({
                    "ok": False,
                    "error": "This CAPTCHA expired or is invalid. Get a new one.",
                }), 400

            if challenge["expires"] < time.time():
                del challenges[challenge_id]
                return jsonify({
                    "ok": False,
                    "error": "This CAPTCHA expired. Get a new one.",
                }), 400

            challenge["attempts"] += 1

            if answer != challenge["answer"]:
                if challenge["attempts"] >= 3:
                    del challenges[challenge_id]
                    error_message = "Too many attempts. Get a new CAPTCHA."
                else:
                    error_message = "Incorrect CAPTCHA. Please try again."

                return jsonify({
                    "ok": False,
                    "error": error_message,
                }), 400

            # Consume the challenge before crediting, preventing replay.
            del challenges[challenge_id]

        new_balance = add_one_coin(telegram_id)

        return jsonify({
            "ok": True,
            "correct": True,
            "message": "Correct! You earned 1 coin.",
            "balance": new_balance,
        })

    except Exception:
        app.logger.exception("CAPTCHA answer processing failed")
        return jsonify({
            "ok": False,
            "error": "Could not process your answer. Please try again.",
        }), 500


@app.post("/api/withdraw")
def api_withdraw():
    user_data, telegram_id, error = authenticated_user()
    if error:
        return error

    body = request.get_json(silent=True) or {}
    coins = body.get("coins")
    upi = str(body.get("upi", "")).strip()

    if isinstance(coins, bool):
        return jsonify({"ok": False, "error": "Enter a valid coin amount."}), 400

    try:
        coins = int(coins)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Enter a valid coin amount."}), 400

    if coins <= 0 or coins > 1_000_000_000 or coins % 50 != 0:
        return jsonify({
            "ok": False,
            "error": "Withdrawal coins must be positive and a multiple of 50.",
        }), 400

    if not upi or len(upi) < 3 or len(upi) > 200 or any(ch.isspace() for ch in upi):
        return jsonify({
            "ok": False,
            "error": "Enter a valid UPI ID without spaces.",
        }), 400

    try:
        ensure_user(telegram_id, user_data.get("username"))

        result = supabase.rpc("create_withdrawal", {
            "p_telegram_id": telegram_id,
            "p_coins": coins,
            "p_upi": upi,
        }).execute()

        data = result.data
        if isinstance(data, list):
            data = data[0] if data else {}
        if not isinstance(data, dict):
            data = {}

        withdrawal_id = (
            data.get("withdrawal_id")
            or data.get("id")
            or data.get("request_id")
        )

        amount_inr = data.get("amount_inr", coins / 50)

        return jsonify({
            "ok": True,
            "withdrawal_id": withdrawal_id or "submitted",
            "amount_inr": float(amount_inr),
        })

    except Exception as exc:
        app.logger.exception("Withdrawal request failed")
        detail = str(exc).lower()

        if "minimum" in detail:
            message = "You have not reached the minimum withdrawal amount."
        elif "insufficient" in detail or "balance" in detail:
            message = "You do not have enough coins."
        elif "upi" in detail:
            message = "Please check your UPI ID."
        elif "user not found" in detail:
            message = "Your account was not found. Reopen the Mini App."
        else:
            message = "Withdrawal could not be submitted. Please try again."

        return jsonify({"ok": False, "error": message}), 400


@app.get("/api/adsgram/reward")
def adsgram_reward_disabled():
    # Do not credit withdrawable coins from an unverified/replayable URL.
    # Enable rewards only after implementing AdsGram's verified reward flow.
    return jsonify({
        "ok": False,
        "error": "Ad rewards are not enabled until secure reward verification is configured.",
    }), 410


# Telegram bot commands


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user = update.effective_user
    if not telegram_user:
        return

    try:
        user = ensure_user(
            telegram_user.id,
            telegram_user.username,
        )
        balance = float(user.get("balance") or 0)

        keyboard = [
            [InlineKeyboardButton(
                "🎮 Open Captcha Earn",
                url=MINI_APP_URL,
            )],
            [InlineKeyboardButton(
                "📢 Official Channel",
                url=CHANNEL_URL,
            )],
        ]

        await update.message.reply_text(
            "Welcome to Captcha Earn India! 🛡️\n\n"
            "Solve CAPTCHAs in Manual mode to earn coins.\n"
            f"Your current balance: {balance:g} coins.\n\n"
            "Open the Mini App below to get started.",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )

    except Exception:
        app.logger.exception("Telegram /start failed")
        await update.message.reply_text(
            "Sorry, your account could not be loaded. Please try again."
        )


async def balance_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    telegram_user = update.effective_user
    if not telegram_user:
        return

    try:
        user = ensure_user(
            telegram_user.id,
            telegram_user.username,
        )
        balance = float(user.get("balance") or 0)
        await update.message.reply_text(
            f"🪙 Your balance: {balance:g} coins"
        )
    except Exception:
        app.logger.exception("Telegram /balance failed")
        await update.message.reply_text(
            "Could not load your balance. Please try again."
        )


async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    first = random.randint(2, 20)
    second = random.randint(2, 20)
    context.user_data["math_answer"] = first + second

    await update.message.reply_text(
        "🧠 Quick math task\n\n"
        f"What is {first} + {second}?\n"
        "Reply with the number to earn 1 coin."
    )


async def answer_task(update: Update, context: ContextTypes.DEFAULT_TYPE):
    expected = context.user_data.get("math_answer")
    if expected is None or not update.message:
        return

    try:
        submitted = int(update.message.text.strip())
    except (ValueError, AttributeError):
        return

    context.user_data.pop("math_answer", None)

    if submitted != expected:
        await update.message.reply_text(
            "That answer is incorrect. Send /task to try another task."
        )
        return

    try:
        telegram_user = update.effective_user
        ensure_user(telegram_user.id, telegram_user.username)
        new_balance = add_one_coin(telegram_user.id)
        await update.message.reply_text(
            f"✅ Correct! You earned 1 coin.\n"
            f"Your balance is now {new_balance:g} coins."
        )
    except Exception:
        app.logger.exception("Telegram math task failed")
        await update.message.reply_text(
            "Could not update your balance. Please try again later."
        )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    app.logger.error(
        "Telegram handler error",
        exc_info=context.error,
    )


def run_flask():
    port = int(os.environ.get("PORT", "10000"))
    app.run(
        host="0.0.0.0",
        port=port,
        threaded=True,
        use_reloader=False,
    )


def main():
    threading.Thread(
        target=run_flask,
        daemon=True,
    ).start()

    telegram_app = Application.builder().token(BOT_TOKEN).build()
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("balance", balance_command))
    telegram_app.add_handler(CommandHandler("task", task_command))
    telegram_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, answer_task)
    )
    telegram_app.add_error_handler(error_handler)

    # Keep only one running instance of this bot to avoid Telegram polling conflicts.
    telegram_app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
