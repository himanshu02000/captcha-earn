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
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

# =========================================================
# CONFIG
# =========================================================
BOT_TOKEN = os.environ["BOT_TOKEN"]
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_SECRET_KEY = os.environ["SUPABASE_SECRET_KEY"]

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MINI_APP_WEB_URL = "https://captcha-earning-bot.onrender.com"
CHANNEL_URL = "https://t.me/CaptchaEarnIndiaOfficial"

supabase = create_client(SUPABASE_URL, SUPABASE_SECRET_KEY)
app = Flask(__name__)
challenges = {}
challenge_lock = threading.Lock()

# =========================================================
# CORS
# =========================================================
@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response

# =========================================================
# TELEGRAM AUTH
# =========================================================
def verify_telegram_init_data(init_data):
    if not isinstance(init_data, str) or not init_data:
        return None
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None
        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(parsed.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
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
    except Exception:
        return None

def authenticated_user():
    body = request.get_json(silent=True) or {}
    user_data = verify_telegram_init_data(body.get("initData", ""))
    if not user_data:
        return None, None
    return user_data, int(user_data["id"])

# =========================================================
# DATABASE
# =========================================================
def get_user(telegram_id):
    try:
        result = supabase.table("users").select("*").eq("telegram_id", telegram_id).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        print("GET USER ERROR:", repr(e))
        return None

def ensure_user(telegram_id, username=None):
    user = get_user(telegram_id)
    if user:
        if username and user.get("username") != username:
            try:
                supabase.table("users").update({"username": username}).eq("telegram_id", telegram_id).execute()
                user["username"] = username
            except Exception as e:
                print("USERNAME UPDATE ERROR:", repr(e))
        return user
    try:
        # Removed earning_mode so it works even if the column does not exist
        result = supabase.table("users").insert({
            "telegram_id": telegram_id,
            "username": username,
            "balance": 0
        }).execute()
        if result.data:
            return result.data[0]
    except Exception as e:
        print("CREATE USER ERROR:", repr(e))
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
        old = float(user.get("balance", 0) or 0)
        new = old + 1
        result = supabase.table("users").update({"balance": new}).eq("telegram_id", telegram_id).select("telegram_id, balance").execute()
        if not result.data:
            return None
        return result.data[0].get("balance", new)
    except Exception as e:
        print("BALANCE UPDATE ERROR:", repr(e))
        return None

# =========================================================
# CAPTCHA
# =========================================================
CAPTCHA_CHARS = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

def make_captcha_text(length=5):
    return "".join(secrets.choice(CAPTCHA_CHARS) for _ in range(length))

def make_captcha_svg(text):
    width, height = 560, 180
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
        '<rect width="100%" height="100%" rx="18" fill="#f7fafc"/>'
    ]
    for _ in range(90):
        x = secrets.randbelow(width)
        y = secrets.randbelow(height)
        r = 1 + secrets.randbelow(3)
        opacity = 0.15 + secrets.randbelow(45) / 100
        parts.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#334155" opacity="{opacity:.2f}"/>')
    for _ in range(8):
        x1 = secrets.randbelow(width)
        y1 = secrets.randbelow(height)
        x2 = secrets.randbelow(width)
        y2 = secrets.randbelow(height)
        stroke_width = 1 + secrets.randbelow(3)
        parts.append(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="#64748b" stroke-width="{stroke_width}" opacity="0.45"/>')
    for index, char in enumerate(text):
        x = 58 + index * 92
        y = 118 + secrets.randbelow(20) - 10
        rotation = secrets.randbelow(31) - 15
        skew = secrets.randbelow(15) - 7
        font_size = 74 + secrets.randbelow(13)
        parts.append(
            f'<text x="{x}" y="{y}" font-family="Arial, sans-serif" font-size="{font_size}px" '
            f'font-weight="900" fill="#111827" transform="rotate({rotation} {x} {y}) skewX({skew})">'
            f'{html.escape(char)}</text>'
        )
    parts.extend([
        '<path d="M10 40 C120 100,190 5,290 55 S450 125,550 35" fill="none" stroke="#1f2937" stroke-width="3" opacity="0.35"/>',
        '<path d="M5 145 C110 90,190 165,310 120 S450 55,555 135" fill="none" stroke="#475569" stroke-width="2" opacity="0.35"/>',
        "</svg>"
    ])
    return "".join(parts)

# =========================================================
# ROUTES
# =========================================================
@app.route("/")
def home():
    return send_from_directory(BASE_DIR, "index.html")

@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200

@app.route("/api/session", methods=["POST"])
def mini_app_session():
    user_data, telegram_id = authenticated_user()
    if not user_data:
        return jsonify({"ok": False, "error": "Telegram authentication failed. Reopen the app from Telegram."}), 401
    user = ensure_user(telegram_id, user_data.get("username"))
    if user is None:
        return jsonify({"ok": False, "error": "Could not load your account."}), 500
    return jsonify({
        "ok": True,
        "name": user_data.get("first_name", "User"),
        "balance": user.get("balance", 0) or 0
    })

@app.route("/api/challenge", methods=["POST"])
def mini_app_challenge():
    user_data, telegram_id = authenticated_user()
    if not user_data:
        return jsonify({"ok": False, "error": "Telegram authentication failed."}), 401
    user = ensure_user(telegram_id, user_data.get("username"))
    if user is None:
        return jsonify({"ok": False, "error": "Could not load your account."}), 500

    captcha_text = make_captcha_text()
    challenge_id = secrets.token_urlsafe(24)
    with challenge_lock:
        challenges[challenge_id] = {
            "telegram_id": telegram_id,
            "answer": captcha_text,
            "expires": time.time() + 180,
            "attempts": 0
        }
    return jsonify({
        "ok": True,
        "name": user_data.get("first_name", "User"),
        "challenge_id": challenge_id,
        "captcha_svg": make_captcha_svg(captcha_text),
        "instruction": "Enter the 5 characters shown in the CAPTCHA.",
        "balance": user.get("balance", 0) or 0
    })

@app.route("/api/answer", methods=["POST"])
