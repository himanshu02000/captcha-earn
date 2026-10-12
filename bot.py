
import os
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
from flask_cors import CORS
from supabase import create_client

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)
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

ADSGRAM_CALLBACK_SECRET = os.environ.get(
    "ADSGRAM_CALLBACK_SECRET", ""
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MINI_APP_URL = "https://captcha-earning-bot.onrender.com/"
CHANNEL_URL = "https://t.me/CaptchaEarnIndiaOfficial"

print("Starting Captcha Earn Bot...", flush=True)

supabase = create_client(
    SUPABASE_URL,
    SUPABASE_SECRET_KEY
)

# Temporary CAPTCHA storage
challenges = {}
challenge_lock = threading.Lock()

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "https://himanshu02000.github.io"}})


# =========================================================
# TELEGRAM MINI APP AUTHENTICATION
# =========================================================

def verify_telegram_init_data(init_data):

    if not init_data or not isinstance(init_data, str):
        return None

    try:
        parsed = dict(
            parse_qsl(
                init_data,
                keep_blank_values=True
            )
        )

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
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode("utf-8"),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash
        ):
            return None

        auth_date = int(
            parsed.get("auth_date", "0")
        )

        now = int(time.time())

        if (
            auth_date <= 0
            or now - auth_date > 86400
            or auth_date > now + 60
        ):
            return None

        user_data = json.loads(
            parsed.get("user", "{}")
        )

        if (
            not isinstance(user_data, dict)
            or not user_data.get("id")
        ):
            return None

        return user_data

    except (
        ValueError,
        TypeError,
        json.JSONDecodeError
    ):
        return None


def authenticated_user():

    body = request.get_json(silent=True) or {}

    init_data = body.get("initData", "")

    user_data = verify_telegram_init_data(init_data)

    if not user_data:
        return None, None

    return user_data, int(user_data["id"])


# =========================================================
# DATABASE
# =========================================================

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

        return result.data[0] if result.data else None

    except Exception as exc:
        print("GET USER ERROR:", repr(exc), flush=True)
        return None


def ensure_user(telegram_id, username=None):

    user = get_user(telegram_id)

    if user:

        if username and user.get("username") != username:

            try:
                (
                    supabase
                    .table("users")
                    .update({"username": username})
                    .eq("telegram_id", telegram_id)
                    .execute()
                )

                user["username"] = username

            except Exception as exc:
                print(
                    "USERNAME UPDATE ERROR:",
                    repr(exc),
                    flush=True
                )

        return user

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
            return result.data[0]

    except Exception as exc:
        print("CREATE USER ERROR:", repr(exc), flush=True)

    return get_user(telegram_id)


def create_user(update):

    telegram_user = update.effective_user

    if telegram_user is None:
        return None

    return ensure_user(
        telegram_user.id,
        telegram_user.username
    )


def add_one_coin(telegram_id):

    user = get_user(telegram_id)

    if user is None:
        return None

    try:
        old_balance = float(user.get("balance", 0) or 0)
        new_balance = old_balance + 1

        result = (
            supabase
            .table("users")
            .update({"balance": new_balance})
            .eq("telegram_id", telegram_id)
            .select("telegram_id, balance")
            .execute()
        )

        if not result.data:
            return None

        return result.data[0].get("balance", new_balance)

    except Exception as exc:
        print("BALANCE UPDATE ERROR:", repr(exc), flush=True)
        return None


# =========================================================
# VISUAL CAPTCHA
# =========================================================

CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def make_captcha_text(length=5):

    return "".join(
        secrets.choice(CAPTCHA_CHARS)
        for _ in range(length)
    )


def make_captcha_svg(text):

    width = 560
    height = 180

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">',
        '<rect width="100%" height="100%" '
        'rx="18" fill="#f7fafc"/>'
    ]

    # Background noise
    for _ in range(90):

        x = secrets.randbelow(width)
        y = secrets.randbelow(height)
        r = 1 + secrets.randbelow(3)
        opacity = 0.15 + secrets.randbelow(45) / 100

        parts.append(
            f'<circle cx="{x}" cy="{y}" '
            f'r="{r}" fill="#334155" '
            f'opacity="{opacity:.2f}"/>'
        )

    # Random lines
    for _ in range(8):

        x1 = secrets.randbelow(width)
        y1 = secrets.randbelow(height)
        x2 = secrets.randbelow(width)
        y2 = secrets.randbelow(height)
        stroke_width = 1 + secrets.randbelow(3)

        parts.append(
            f'<line x1="{x1}" y1="{y1}" '
            f'x2="{x2}" y2="{y2}" '
            f'stroke="#64748b" '
            f'stroke-width="{stroke_width}" '
            f'opacity="0.45"/>'
        )

    # CAPTCHA characters
    start_x = 58
    spacing = 92

    for index, char in enumerate(text):

        x = start_x + index * spacing
        y = 118 + secrets.randbelow(20) - 10
        rotation = secrets.randbelow(31) - 15
        skew = secrets.randbelow(15) - 7
        font_size = 74 + secrets.randbelow(13)

        parts.append(
            f'<text x="{x}" y="{y}" '
            f'font-family="Arial, sans-serif" '
            f'font-size="{font_size}px" '
            f'font-weight="900" '
            f'fill="#111827" '
            f'transform="rotate({rotation} {x} {y}) '
            f'skewX({skew})">'
            f'{html.escape(char)}'
            f'</text>'
        )

    # Foreground curves
    parts.append(
        '<path d="M10 40 C120 100, 190 5, '
        '290 55 S450 125, 550 35" '
        'fill="none" stroke="#1f2937" '
        'stroke-width="3" opacity="0.35"/>'
    )

    parts.append(
        '<path d="M5 145 C110 90, 190 165, '
        '310 120 S450 55, 555 135" '
        'fill="none" stroke="#475569" '
        'stroke-width="2" opacity="0.35"/>'
    )

    parts.append("</svg>")

    return "".join(parts)


# =========================================================
# TELEGRAM BOT HANDLERS
# =========================================================

async def start_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Handle /start command."""

    telegram_user = update.effective_user

    if telegram_user is None or update.message is None:
        return

    user = ensure_user(
        telegram_user.id,
        telegram_user.username
    )

    if user is None:
        await update.message.reply_text(
            "❌ Could not create your account. "
            "Please try again later."
        )
        return

    balance = user.get("balance", 0) or 0

    keyboard = [
        [
            InlineKeyboardButton(
                "🎮 Open App",
                web_app=WebAppInfo(url=MINI_APP_URL)
            )
        ],
        [
            InlineKeyboardButton(
                "📢 Updates",
                url=CHANNEL_URL
            )
        ]
    ]

    reply_markup = InlineKeyboardMarkup(keyboard)

    welcome_text = (
        "💰 Welcome to Captcha Earn India!\n\n"
        "Earn coins in your free time by solving CAPTCHAs "
        "and watching available ads.\n\n"
        "✅ Complete tasks and earn coins\n"
        "⏰ Work at your own pace\n"
        "💸 Submit withdrawal requests through UPI when eligible\n\n"
        "📢 Payment updates and verified withdrawal proofs:\n"
        f"{CHANNEL_URL}\n\n"
        "⏳ The app may take 30–60 seconds to load after inactivity. "
        "Please wait patiently.\n\n"
        "🚀 Tap below to get started!\n\n"
        f"💰 Your balance: {balance} coins\n\n"
        "⚠️ Withdrawals are subject to eligibility and approval."
    )

    await update.message.reply_text(
        welcome_text,
        reply_markup=reply_markup
    )


async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Handle /help command."""

    help_text = (
        "🎯 *Captcha Earn India - Help*\n\n"
        "/start - Open the main menu\n"
        "/balance - Check your balance\n"
        "/help - Show this help message\n\n"
        "*How it works:*\n"
        "1. Tap 🎮 Open App\n"
        "2. Solve CAPTCHAs to earn coins\n"
        "3. Watch ads for extra rewards\n"
        "4. Request withdrawal when eligible\n\n"
        "Minimum withdrawal: 500 coins on your first withdrawal, "
        "then 1,000 coins."
    )

    if update.message:
        await update.message.reply_text(
            help_text,
            parse_mode="Markdown"
        )


async def balance_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    """Handle /balance command."""

    telegram_user = update.effective_user

    if telegram_user is None or update.message is None:
        return

    user = get_user(telegram_user.id)

    if user is None:
        await update.message.reply_text(
            "❌ User not found. Use /start first."
        )
        return

    balance = user.get("balance", 0) or 0

    await update.message.reply_text(
        f"💰 Your balance: *{balance} coins*",
        parse_mode="Markdown"
    )


# =========================================================
# WEBSITE
# =========================================================

@app.route("/")
def home():

    return send_from_directory(
        BASE_DIR,
        "index.html"
    )


@app.route("/health")
def health():

    return jsonify({"status": "ok"}), 200


# =========================================================
# SESSION
# =========================================================

@app.route("/api/session", methods=["POST"])
def mini_app_session():

    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error":
                "Telegram authentication failed. "
                "Reopen the app from Telegram."
        }), 401

    user = ensure_user(
        telegram_id,
        user_data.get("username")
    )

    if user is None:
        return jsonify({
            "ok": False,
            "error": "Could not load your account."
        }), 500

    return jsonify({
        "ok": True,
        "name": user_data.get("first_name", "User"),
        "balance": user.get("balance", 0) or 0
    })


# =========================================================
# VISUAL CAPTCHA CHALLENGE
# =========================================================

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
        user_data.get("username")
    )

    if user is None:
        return jsonify({
            "ok": False,
            "error": "Could not load your account."
        }), 500

    captcha_text = make_captcha_text(5)
    challenge_id = secrets.token_urlsafe(24)

    with challenge_lock:
        # Drop expired challenges so the in-memory store
        # does not grow without bound.
        now = time.time()
        expired = [
            cid for cid, entry in challenges.items()
            if entry.get("expires", 0) <= now
        ]

        for cid in expired:
            challenges.pop(cid, None)

        challenges[challenge_id] = {
            "telegram_id": telegram_id,
            "answer": captcha_text,
            "expires": time.time() + 180,
            "attempts": 0
        }

    return jsonify({
        "ok": True,
        "challenge_id": challenge_id,
        "captcha_svg": make_captcha_svg(captcha_text),
        "instruction":
            "Enter the 5 characters shown in the CAPTCHA.",
        "balance": user.get("balance", 0) or 0
    })


# =========================================================
# CAPTCHA ANSWER
# =========================================================

# Coins earned by manual CAPTCHA solves are held here until the
# rewarded ad shown after the solve completes. Every credited
# manual-solve coin is therefore backed by a shown ad.
pending_lock = threading.Lock()
pending_solve_coins = {}


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
    submitted_answer = body.get("answer", "")

    if not isinstance(challenge_id, str):
        return jsonify({
            "ok": False,
            "error": "Invalid challenge."
        }), 400

    if not isinstance(submitted_answer, str):
        submitted_answer = str(submitted_answer)

    submitted_answer = submitted_answer.strip().upper()

    with challenge_lock:

        challenge = challenges.get(challenge_id)

        if (
            not challenge
            or challenge["telegram_id"] != telegram_id
        ):
            return jsonify({
                "ok": False,
                "error":
                    "Challenge not found. Start a new CAPTCHA."
            }), 400

        if time.time() > challenge["expires"]:

            challenges.pop(challenge_id, None)

            return jsonify({
                "ok": False,
                "error": "CAPTCHA expired. Get a new CAPTCHA."
            }), 400

        challenge["attempts"] += 1

        if challenge["attempts"] > 3:

            challenges.pop(challenge_id, None)

            return jsonify({
                "ok": False,
                "error": "Too many attempts. Get a new CAPTCHA."
            }), 429

        if submitted_answer != challenge["answer"]:

            if challenge["attempts"] >= 3:
                challenges.pop(challenge_id, None)

            return jsonify({
                "ok": False,
                "error": "❌ Incorrect CAPTCHA. Try again."
            }), 400

        # Consume CAPTCHA before awarding the reward.
        challenges.pop(challenge_id, None)

    # Hold the coin as pending: it is only credited when the
    # rewarded ad shown after this solve completes.
    with pending_lock:
        pending = pending_solve_coins.get(telegram_id, 0) + 1
        pending_solve_coins[telegram_id] = pending

    user = get_user(telegram_id)
    balance = (user.get("balance", 0) or 0) if user else 0

    return jsonify({
        "ok": True,
        "correct": True,
        "pending": pending,
        "message":
            "✅ Correct! Your coin is waiting — "
            "it lands when the ad finishes.",
        "balance": balance
    })


# =========================================================
# CLAIM SOLVE COIN (releases one pending manual-solve coin)
# =========================================================


@app.route("/api/claim-solve", methods=["POST"])
def mini_app_claim_solve():

    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed."
        }), 401

    with pending_lock:

        pending = pending_solve_coins.get(telegram_id, 0)

        if pending <= 0:
            return jsonify({
                "ok": False,
                "error":
                    "No pending coin to claim. "
                    "Solve a CAPTCHA first."
            }), 400

        pending_solve_coins[telegram_id] = pending - 1

    balance = add_one_coin(telegram_id)

    if balance is None:

        # Refund the pending coin if the credit failed.
        with pending_lock:
            pending_solve_coins[telegram_id] = \
                pending_solve_coins.get(telegram_id, 0) + 1

        return jsonify({
            "ok": False,
            "error":
                "Could not save your reward. "
                "Please check your balance."
        }), 500

    return jsonify({
        "ok": True,
        "message": "🎬 Ad completed! +1 coin earned.",
        "pending": pending - 1,
        "balance": balance
    })


# =========================================================
# AD REWARD (1 coin per fully watched rewarded ad)
# =========================================================

ad_reward_lock = threading.Lock()
last_ad_reward_at = {}


@app.route("/api/ad-reward", methods=["POST"])
def mini_app_ad_reward():

    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed."
        }), 401

    # One rewarded ad per user per 60 seconds, to slow down
    # anyone calling this endpoint without watching an ad.
    now = time.time()

    with ad_reward_lock:

        last = last_ad_reward_at.get(telegram_id, 0)

        if now - last < 60:
            return jsonify({
                "ok": False,
                "error":
                    "You just claimed an ad reward. "
                    "Please wait a little before the next one."
            }), 429

        last_ad_reward_at[telegram_id] = now

    balance = add_one_coin(telegram_id)

    if balance is None:
        return jsonify({
            "ok": False,
            "error":
                "Could not save your reward. "
                "Please check your balance."
        }), 500

    return jsonify({
        "ok": True,
        "message": "🎬 Ad reward: 1 coin earned.",
        "balance": balance
    })


# =========================================================
# AUTO-BOT SOLVE (bot auto-solves a real challenge)
# =========================================================

auto_solve_lock = threading.Lock()
last_auto_solve_at = {}


@app.route("/api/auto-solve", methods=["POST"])
def mini_app_auto_solve():

    user_data, telegram_id = authenticated_user()

    if not user_data:
        return jsonify({
            "ok": False,
            "error": "Telegram authentication failed."
        }), 401

    body = request.get_json(silent=True) or {}

    challenge_id = body.get("challenge_id")

    if not isinstance(challenge_id, str):
        return jsonify({
            "ok": False,
            "error": "Invalid challenge."
        }), 400

    now = time.time()

    # Lock ordering is fixed (auto_solve_lock -> challenge_lock)
    # so this cannot deadlock with /api/answer.
    with auto_solve_lock:

        last = last_auto_solve_at.get(telegram_id, 0)

        if now - last < 12:
            return jsonify({
                "ok": False,
                "error":
                    "Auto-bot is solving too fast. "
                    "Please wait a few seconds."
            }), 429

        with challenge_lock:

            challenge = challenges.get(challenge_id)

            if (
                not challenge
                or challenge["telegram_id"] != telegram_id
            ):
                return jsonify({
                    "ok": False,
                    "error":
                        "Challenge not found. "
                        "Start a new auto-bot cycle."
                }), 400

            if time.time() > challenge["expires"]:

                challenges.pop(challenge_id, None)

                return jsonify({
                    "ok": False,
                    "error":
                        "CAPTCHA expired. "
                        "Start a new auto-bot cycle."
                }), 400

            # The bot solves the challenge on the server side:
            # consume it so it cannot be solved twice.
            challenges.pop(challenge_id, None)

        last_auto_solve_at[telegram_id] = now

    balance = add_one_coin(telegram_id)

    if balance is None:
        return jsonify({
            "ok": False,
            "error":
                "Could not save your reward. "
                "Please check your balance."
        }), 500

    return jsonify({
        "ok": True,
        "message": "🤖 Auto-solved! 1 coin earned.",
        "balance": balance
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
            "error":
                "Telegram authentication failed. "
                "Reopen the app from Telegram."
        }), 401

    body = request.get_json(silent=True) or {}

    raw_coins = body.get("coins")
    upi = body.get("upi")

    if isinstance(raw_coins, bool):
        return jsonify({
            "ok": False,
            "error": "Enter a valid coin amount."
        }), 400

    try:
        coins = int(raw_coins)

    except (TypeError, ValueError, OverflowError):
        return jsonify({
            "ok": False,
            "error": "Enter a valid whole number of coins."
        }), 400

    if (
        isinstance(raw_coins, float)
        and not raw_coins.is_integer()
    ):
        return jsonify({
            "ok": False,
            "error": "Enter a whole number of coins."
        }), 400

    if (
        isinstance(raw_coins, str)
        and str(coins) != raw_coins.strip()
    ):
        return jsonify({
            "ok": False,
            "error": "Enter a valid whole number of coins."
        }), 400

    if coins <= 0 or coins > 1000000000:
        return jsonify({
            "ok": False,
            "error": "Invalid withdrawal amount."
        }), 400

    if coins % 50 != 0:
        return jsonify({
            "ok": False,
            "error":
                "The amount must be a multiple of 50 coins."
        }), 400

    if not isinstance(upi, str):
        return jsonify({
            "ok": False,
            "error": "Enter your UPI ID."
        }), 400

    upi = upi.strip()

    if (
        len(upi) < 3
        or len(upi) > 200
        or any(character.isspace() for character in upi)
    ):
        return jsonify({
            "ok": False,
            "error": "Enter a valid UPI ID without spaces."
        }), 400

    try:
        result = supabase.rpc(
            "create_withdrawal",
            {
                "p_telegram_id": telegram_id,
                "p_coins": coins,
                "p_upi": upi
            }
        ).execute()

        withdrawal_id = result.data

        if isinstance(withdrawal_id, list) and withdrawal_id:
            withdrawal_id = withdrawal_id[0]

        return jsonify({
            "ok": True,
            "message": "Withdrawal request submitted successfully!",
            "withdrawal_id": withdrawal_id,
            "coins": coins,
            "amount_inr": coins / 50,
            "status": "pending"
        }), 200

    except Exception as exc:

        print("WITHDRAWAL ERROR:", repr(exc), flush=True)

        error_text = str(exc)

        if "Minimum withdrawal is" in error_text:
            return jsonify({
                "ok": False,
                "error":
                    "Your minimum withdrawal is "
                    "500 coins for your first "
                    "withdrawal, then 1,000 coins."
            }), 400

        if "Insufficient balance" in error_text:
            return jsonify({
                "ok": False,
                "error":
                    "You don't have enough coins "
                    "for this withdrawal."
            }), 400

        if "multiple of 50" in error_text:
            return jsonify({
                "ok": False,
                "error":
                    "The amount must be a multiple "
                    "of 50 coins."
            }), 400

        if "Invalid UPI details" in error_text:
            return jsonify({
                "ok": False,
                "error": "Please enter valid UPI details."
            }), 400

        if "User account not found" in error_text:
            return jsonify({
                "ok": False,
                "error": "User account not found."
            }), 500

        return jsonify({
            "ok": False,
            "error": "Withdrawal failed. Please try again."
        }), 500


# =========================================================
# BOT SETUP & MAIN
# =========================================================

async def setup_telegram_bot():
    """Create the Telegram bot and register its commands."""

    bot_app = Application.builder().token(BOT_TOKEN).build()

    bot_app.add_handler(
        CommandHandler("start", start_command)
    )
    bot_app.add_handler(
        CommandHandler("help", help_command)
    )
    bot_app.add_handler(
        CommandHandler("balance", balance_command)
    )

    return bot_app


async def main():
    """Initialize the bot and start receiving Telegram updates."""

    bot_app = await setup_telegram_bot()

    async with bot_app:

        await bot_app.start()

        if bot_app.updater is None:
            raise RuntimeError(
                "Telegram updater is not available."
            )

        await bot_app.updater.start_polling()

        print(
            "Telegram bot started successfully; "
            "polling for updates.",
            flush=True
        )

        try:
            await asyncio.Event().wait()

        finally:
            if bot_app.updater.running:
                await bot_app.updater.stop()

            if bot_app.running:
                await bot_app.stop()


# =========================================================
# START FLASK AND TELEGRAM
# =========================================================

if __name__ == "__main__":

    def run_flask():
        port = int(os.environ.get("PORT", "10000"))

        app.run(
            host="0.0.0.0",
            port=port,
            debug=False,
            use_reloader=False
        )

    flask_thread = threading.Thread(
        target=run_flask,
        daemon=True
    )

    flask_thread.start()

    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        print("Bot stopped.", flush=True)
