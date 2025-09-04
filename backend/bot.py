import os
import json
import threading
import time
from datetime import datetime, timezone, timedelta
import hmac, hashlib, urllib.parse

import psycopg2
from flask import Flask, request, send_from_directory, jsonify
import telebot
from telebot import types

# -----------------------------
# 🔹 Config
# -----------------------------
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN env variable missing")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL env variable missing")

bot = telebot.TeleBot(TOKEN, parse_mode="HTML")

# -----------------------------
# 🔹 Thread-safe DB connection
# -----------------------------
_thread = threading.local()

def get_conn():
    """Per-thread postgres connection (autocommit)."""
    if not hasattr(_thread, "conn") or _thread.conn.closed:
        _thread.conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        _thread.conn.autocommit = True
    return _thread.conn

def run_query(query, params=(), fetchone=False, fetchall=False):
    """Thread-safe DB helper"""
    with get_conn().cursor() as cur:
        cur.execute(query, params)
        if fetchone:
            return cur.fetchone()
        if fetchall:
            return cur.fetchall()

# -----------------------------
# 🔹 Database Setup
# -----------------------------
run_query("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    per_click INTEGER DEFAULT 1,
    referrals INTEGER DEFAULT 0,
    referred_by TEXT,
    auto_clicker_level INTEGER DEFAULT 0,
    daily_claim_at TIMESTAMPTZ,
    last_earn_at TIMESTAMPTZ,
    last_auto_at TIMESTAMPTZ
)
""")

# In case old table exists without new column:
run_query("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_auto_at TIMESTAMPTZ")

def row_to_user(row):
    return {
        "user_id": row[0],
        "username": row[1],
        "balance": row[2],
        "per_click": row[3],
        "referrals": row[4],
        "referred_by": row[5],
        "auto_clicker_level": row[6],
        "daily_claim_at": row[7].isoformat() if row[7] else None,
        "last_earn_at": row[8].isoformat() if row[8] else None,
        "last_auto_at": row[9].isoformat() if row[9] else None,
    }

def get_user(user_id, username=None):
    row = run_query(
        """SELECT user_id, username, balance, per_click, referrals, referred_by,
                  auto_clicker_level, daily_claim_at, last_earn_at, last_auto_at
           FROM users WHERE user_id=%s""",
        (user_id,), fetchone=True,
    )
    if row is None:
        run_query("INSERT INTO users (user_id, username) VALUES (%s, %s)", (user_id, username))
        return {
            "user_id": user_id,
            "username": username,
            "balance": 0,
            "per_click": 1,
            "referrals": 0,
            "referred_by": None,
            "auto_clicker_level": 0,
            "daily_claim_at": None,
            "last_earn_at": None,
            "last_auto_at": None,
        }
    else:
        if username and row[1] != username:
            run_query("UPDATE users SET username=%s WHERE user_id=%s", (username, user_id))
            row = (row[0], username, *row[2:])
        return row_to_user(row)

def update_user(user_id, **fields):
    if not fields:
        return
    cols = [f"{k}=%s" for k in fields.keys()]
    vals = list(fields.values())
    vals.append(user_id)
    q = f"UPDATE users SET {', '.join(cols)} WHERE user_id=%s"
    run_query(q, tuple(vals))

# -----------------------------
# 🔹 Telegram WebApp Security (initData validation)
# -----------------------------
BOT_TOKEN = TOKEN.encode()

def check_telegram_auth(init_data: str, max_age_seconds: int = 86400) -> bool:
    """
    Validates Telegram WebApp initData.
    - Parses querystring (k=v&k2=v2...)
    - Verifies HMAC-SHA256 with secret key = sha256(bot_token)
    - Optionally checks auth_date age
    """
    try:
        if not init_data:
            return False
        pairs = urllib.parse.parse_qsl(init_data, keep_blank_values=True)
        data = dict(pairs)
        received_hash = data.pop("hash", None)
        if not received_hash:
            return False

        # Optional age check
        auth_date = int(data.get("auth_date", "0"))
        if auth_date and (datetime.now(timezone.utc) - datetime.fromtimestamp(auth_date, tz=timezone.utc)).total_seconds() > max_age_seconds:
            return False

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
        secret_key = hashlib.sha256(BOT_TOKEN).digest()
        computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed_hash, received_hash)
    except Exception:
        return False

# -----------------------------
# 🔹 Telegram Bot Handlers
# -----------------------------
@bot.message_handler(commands=["start"])
def start(message):
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name
    user = get_user(user_id, username=username)

    # referral logic
    args = message.text.split()
    if len(args) > 1 and not user["referred_by"]:
        referrer = args[1]
        if referrer != user_id:
            ref_user = get_user(referrer)
            update_user(
                referrer,
                balance=ref_user["balance"] + 10,
                referrals=ref_user["referrals"] + 1,
            )
            update_user(user_id, referred_by=referrer)
            try:
                bot.send_message(
                    referrer,
                    f"🎉 <b>Referral mila!</b> +10 coins\nTotal referrals: {ref_user['referrals'] + 1}",
                )
            except Exception:
                pass

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💰 Earn", "📊 Balance")
    markup.add("⚡ Upgrade", "🏆 Leaderboard")
    markup.add("👥 Ref Leaderboard", "🔗 Referral Link")
    markup.add("🎮 Play Mini App")

    bot.send_message(
        message.chat.id,
        f"👋 Welcome <b>{username}</b>!\n"
        f"💎 Balance: <b>{user['balance']}</b>\n"
        f"⚡ Per Click: <b>{user['per_click']}</b>\n\n"
        "Tap karo aur coins earn karo 🚀",
        reply_markup=markup,
    )

@bot.message_handler(func=lambda m: m.text == "💰 Earn")
def earn(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id, username=message.from_user.username or message.from_user.first_name)
    now = datetime.now(timezone.utc)

    # cooldown = 2 sec
    if user["last_earn_at"]:
        last = datetime.fromisoformat(user["last_earn_at"]).replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < 2:
            bot.send_message(message.chat.id, "⏳ Thoda ruk jao! (2 sec cooldown)")
            return

    new_balance = user["balance"] + user["per_click"]
    update_user(user_id, balance=new_balance, last_earn_at=now)
    bot.send_message(message.chat.id, f"🎉 +{user['per_click']} Coin!\n💎 Balance: <b>{new_balance}</b>")

@bot.message_handler(func=lambda m: m.text == "📊 Balance")
def balance(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    badge = "🥇" if user["balance"] >= 1000 else "🎖️" if user["balance"] >= 500 else "⭐"
    bot.send_message(
        message.chat.id,
        f"📊 Balance: <b>{user['balance']}</b> {badge}\n"
        f"⚡ Per Click: <b>{user['per_click']}</b>\n"
        f"🤖 Auto Clicker: <b>Lv.{user['auto_clicker_level']}</b>\n"
        f"👥 Referrals: <b>{user['referrals']}</b>",
    )

@bot.message_handler(func=lambda m: m.text == "⚡ Upgrade")
def upgrade(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    cost = user["per_click"] * 50
    if user["balance"] >= cost:
        update_user(user_id, balance=user["balance"] - cost, per_click=user["per_click"] + 1)
        bot.send_message(
            message.chat.id,
            f"✅ Upgrade Successful!\n⚡ New Per Click: <b>{user['per_click'] + 1}</b>\n💸 Remaining: <b>{user['balance'] - cost}</b>",
        )
    else:
        bot.send_message(
            message.chat.id,
            f"❌ Not enough coins!\nCost: <b>{cost}</b>\n💎 Balance: <b>{user['balance']}</b>",
        )

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):
    rows = run_query("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True)
    if not rows:
        bot.send_message(message.chat.id, "❌ No users yet.")
        return
    text = "🏆 <b>Top 10 Users</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = row[0] or "Guest"
        text += f"{i}. {name} → {row[1]} coins\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "👥 Ref Leaderboard")
def ref_leaderboard(message):
    rows = run_query("SELECT username, referrals FROM users ORDER BY referrals DESC LIMIT 10", fetchall=True)
    if not rows:
        bot.send_message(message.chat.id, "❌ No users yet.")
        return
    text = "👥 <b>Top Referrers</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = row[0] or "Guest"
        text += f"{i}. {name} → {row[1]} referrals\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "🔗 Referral Link")
def referral(message):
    user_id = str(message.from_user.id)
    link = f"https://t.me/{bot.get_me().username}?start={user_id}"
    bot.send_message(
        message.chat.id,
        f"🔗 Referral link:\n<code>{link}</code>\n\n👥 1 referral = +10 coins",
    )

@bot.message_handler(func=lambda m: m.text == "🎮 Play Mini App")
def play_mini_app(message):
    markup = types.InlineKeyboardMarkup()
    web_app = types.WebAppInfo(url="https://hamster-miniapp.onrender.com")
    button = types.InlineKeyboardButton(text="Open Mini App", web_app=web_app)
    markup.add(button)
    bot.send_message(message.chat.id, "Play the Mini App:", reply_markup=markup)

# -----------------------------
# 🔹 Flask App
# -----------------------------
app = Flask(__name__)
FRONTEND_FOLDER = os.path.join(os.path.dirname(__file__), "frontend")

@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_FOLDER, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(FRONTEND_FOLDER, path)

@app.route("/health")
def health():
    return {"ok": True, "time": datetime.utcnow().isoformat()}

# -----------------------------
# 🔹 Auto Clicker Helpers
# -----------------------------
AUTO_PERIOD = 10  # seconds
AUTO_PER_LEVEL = 2  # coins per period per level

def apply_auto_sync(user_id, user=None):
    """Lazy-sync auto clicker earnings for a user (used by API)."""
    _user = user or get_user(user_id)
    lvl = _user["auto_clicker_level"]
    if lvl <= 0:
        return _user

    now = datetime.now(timezone.utc)
    last_auto = _user["last_auto_at"]
    last_auto_dt = datetime.fromisoformat(last_auto).replace(tzinfo=timezone.utc) if last_auto else now
    elapsed = (now - last_auto_dt).total_seconds()
    if elapsed >= AUTO_PERIOD:
        cycles = int(elapsed // AUTO_PERIOD)
        earned = lvl * AUTO_PER_LEVEL * cycles
        new_balance = _user["balance"] + earned
        update_user(user_id, balance=new_balance, last_auto_at=now)
        _user["balance"] = new_balance
        _user["last_auto_at"] = now.isoformat()
    return _user

def auto_clicker_worker():
    """Background worker to accrue auto coins even if user doesn't open app."""
    while True:
        rows = run_query(
            "SELECT user_id, auto_clicker_level, balance, last_auto_at FROM users WHERE auto_clicker_level > 0",
            fetchall=True
        ) or []
        now = datetime.now(timezone.utc)
        for uid, lvl, bal, last_auto in rows:
            if lvl <= 0:
                continue
            last_dt = last_auto.replace(tzinfo=timezone.utc) if last_auto else now
            elapsed = (now - last_dt).total_seconds()
            if elapsed >= AUTO_PERIOD:
                cycles = int(elapsed // AUTO_PERIOD)
                earned = lvl * AUTO_PER_LEVEL * cycles
                update_user(uid, balance=bal + earned, last_auto_at=now)
        time.sleep(5)

# -----------------------------
# 🔹 API Routes (secure)
# -----------------------------
def require_auth_from_args():
    initData = request.args.get("initData", "")
    if not check_telegram_auth(initData):
        return None
    return initData

def require_auth_from_json():
    data = request.get_json(silent=True) or {}
    initData = data.get("initData", "")
    if not check_telegram_auth(initData):
        return None, data
    return initData, data

@app.route("/api/user/<user_id>")
def api_user(user_id):
    if not require_auth_from_args():
        return jsonify({"error": "Invalid initData"}), 403
    user = get_user(user_id)
    user = apply_auto_sync(user_id, user)
    return jsonify(user)

@app.route("/api/earn", methods=["POST"])
def api_earn():
    initData, data = require_auth_from_json()
    if not initData:
        return jsonify({"error": "Invalid initData"}), 403

    user_id = str(data.get("user_id"))
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    user = get_user(user_id)
    # lazy sync auto first
    user = apply_auto_sync(user_id, user)

    now = datetime.now(timezone.utc)
    # cooldown 2s
    if user["last_earn_at"]:
        last = datetime.fromisoformat(user["last_earn_at"]).replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < 2:
            return jsonify({"error": "Cooldown active"}), 429

    new_balance = user["balance"] + user["per_click"]
    update_user(user_id, balance=new_balance, last_earn_at=now)
    return jsonify({"balance": new_balance, "per_click": user["per_click"]})

@app.route("/api/buy", methods=["POST"])
def api_buy():
    initData, data = require_auth_from_json()
    if not initData:
        return jsonify({"error": "Invalid initData"}), 403

    user_id = str(data.get("user_id"))
    item = data.get("item")
    if not user_id or not item:
        return jsonify({"error": "user_id and item required"}), 400

    user = get_user(user_id)
    user = apply_auto_sync(user_id, user)

    if item == "click":
        cost = user["per_click"] * 50
        if user["balance"] < cost:
            return jsonify({"error": "Not enough coins"}), 400
        update_user(user_id, balance=user["balance"] - cost, per_click=user["per_click"] + 1)
        return jsonify({"ok": True, "balance": user["balance"] - cost, "per_click": user["per_click"] + 1})

    elif item == "auto":
        cost = (user["auto_clicker_level"] + 1) * 100
        if user["balance"] < cost:
            return jsonify({"error": "Not enough coins"}), 400
        update_user(user_id, balance=user["balance"] - cost, auto_clicker_level=user["auto_clicker_level"] + 1)
        return jsonify({"ok": True, "balance": user["balance"] - cost, "auto_clicker_level": user["auto_clicker_level"] + 1})

    return jsonify({"error": "Invalid item"}), 400

@app.route("/api/daily", methods=["POST"])
def api_daily():
    initData, data = require_auth_from_json()
    if not initData:
        return jsonify({"error": "Invalid initData"}), 403

    user_id = str(data.get("user_id"))
    if not user_id:
        return jsonify({"error": "user_id required"}), 400

    user = get_user(user_id)
    user = apply_auto_sync(user_id, user)

    now = datetime.now(timezone.utc)
    bonus = 50
    if user["daily_claim_at"]:
        last_claim = datetime.fromisoformat(user["daily_claim_at"]).replace(tzinfo=timezone.utc)
        if (now - last_claim).total_seconds() < 24 * 3600:
            return jsonify({"error": "Already claimed"}), 400

    update_user(user_id, balance=user["balance"] + bonus, daily_claim_at=now)
    return jsonify({"ok": True, "balance": user["balance"] + bonus, "bonus": bonus})

@app.route("/api/leaderboard")
def api_leaderboard():
    if not require_auth_from_args():
        return jsonify({"error": "Invalid initData"}), 403

    rows = run_query("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10", fetchall=True) or []
    data = [{"username": r[0], "balance": r[1]} for r in rows]
    return jsonify(data)

@app.route("/api/rank/<user_id>")
def api_rank(user_id):
    if not require_auth_from_args():
        return jsonify({"error": "Invalid initData"}), 403

    user = get_user(user_id)
    rows = run_query("SELECT user_id, username, balance FROM users ORDER BY balance DESC", fetchall=True) or []
    rank = next((i + 1 for i, r in enumerate(rows) if r[0] == user_id), None)
    return jsonify({"username": user["username"], "balance": user["balance"], "rank": rank})

# -----------------------------
# 🔹 Run
# -----------------------------
if __name__ == "__main__":
    threading.Thread(target=lambda: bot.polling(none_stop=True), daemon=True).start()
    threading.Thread(target=auto_clicker_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
