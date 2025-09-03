import os
import json
import threading
import psycopg2
from datetime import datetime, timezone, date, timedelta

import telebot
from telebot import types
from flask import Flask, request, send_from_directory, jsonify

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
# 🔹 Database Setup
# -----------------------------
conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cursor = conn.cursor()

# users: add username + auto_clicker + daily_claim_at
cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    username TEXT,
    balance INTEGER DEFAULT 0,
    per_click INTEGER DEFAULT 1,
    referrals INTEGER DEFAULT 0,
    auto_clicker_level INTEGER DEFAULT 0,
    daily_claim_at TIMESTAMPTZ
)
""")
conn.commit()

def row_to_user(row):
    # order must match SELECT columns
    return {
        "user_id": row[0],
        "username": row[1],
        "balance": row[2],
        "per_click": row[3],
        "referrals": row[4],
        "auto_clicker_level": row[5],
        "daily_claim_at": row[6].isoformat() if row[6] else None
    }

# Helper: create/get + keep username fresh
def get_user(user_id, username=None):
    cursor.execute("SELECT user_id, username, balance, per_click, referrals, auto_clicker_level, daily_claim_at FROM users WHERE user_id=%s", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute(
            "INSERT INTO users (user_id, username) VALUES (%s, %s)",
            (user_id, username)
        )
        conn.commit()
        return {
            "user_id": user_id, "username": username,
            "balance": 0, "per_click": 1, "referrals": 0,
            "auto_clicker_level": 0, "daily_claim_at": None
        }
    else:
        # auto-update username if changed
        if username and row[1] != username:
            cursor.execute("UPDATE users SET username=%s WHERE user_id=%s", (username, user_id))
            conn.commit()
            row = (row[0], username, row[2], row[3], row[4], row[5], row[6])
        return row_to_user(row)

def update_user(user_id, **fields):
    if not fields:
        return
    cols = []
    vals = []
    for k, v in fields.items():
        cols.append(f"{k}=%s")
        vals.append(v)
    vals.append(user_id)
    q = f"UPDATE users SET {', '.join(cols)} WHERE user_id=%s"
    cursor.execute(q, tuple(vals))
    conn.commit()

# -----------------------------
# 🔹 Telegram Bot Handlers
# -----------------------------
@bot.message_handler(commands=['start'])
def start(message):
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name
    user = get_user(user_id, username=username)

    # Referral logic
    args = message.text.split()
    if len(args) > 1:
        referrer = args[1]
        if referrer != user_id:
            ref_user = get_user(referrer)
            update_user(referrer,
                        balance=ref_user["balance"] + 10,
                        referrals=ref_user["referrals"] + 1)
            try:
                bot.send_message(referrer, f"🎉 <b>Referral mila!</b> +10 coins\nTotal referrals: {ref_user['referrals'] + 1}")
            except Exception:
                pass

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💰 Earn", "📊 Balance")
    markup.add("⚡ Upgrade", "🏆 Leaderboard")
    markup.add("🔗 Referral Link", "🎮 Play Mini App")

    bot.send_message(
        message.chat.id,
        f"👋 Welcome <b>{username}</b>!\n"
        f"💎 Balance: <b>{user['balance']}</b>\n"
        f"⚡ Per Click: <b>{user['per_click']}</b>\n\n"
        f"Tap karo aur coins earn karo 🚀",
        reply_markup=markup
    )

@bot.message_handler(func=lambda m: m.text == "💰 Earn")
def earn(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id, username=message.from_user.username or message.from_user.first_name)
    new_balance = user["balance"] + user["per_click"]
    update_user(user_id, balance=new_balance)
    bot.send_message(message.chat.id, f"🎉 +{user['per_click']} Coin!\n💎 Balance: <b>{new_balance}</b>")

@bot.message_handler(func=lambda m: m.text == "📊 Balance")
def balance(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id, username=message.from_user.username or message.from_user.first_name)
    bot.send_message(
        message.chat.id,
        f"📊 Balance: <b>{user['balance']}</b>\n"
        f"⚡ Per Click: <b>{user['per_click']}</b>\n"
        f"🤖 Auto Clicker: <b>Lv.{user['auto_clicker_level']}</b>\n"
        f"👥 Referrals: <b>{user['referrals']}</b>"
    )

@bot.message_handler(func=lambda m: m.text == "⚡ Upgrade")
def upgrade(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    cost = user["per_click"] * 50
    if user["balance"] >= cost:
        update_user(user_id,
                    balance=user["balance"] - cost,
                    per_click=user["per_click"] + 1)
        bot.send_message(message.chat.id, f"✅ Upgrade Successful!\n⚡ New Per Click: <b>{user['per_click'] + 1}</b>\n💸 Remaining: <b>{user['balance'] - cost}</b>")
    else:
        bot.send_message(message.chat.id, f"❌ Not enough coins!\nCost: <b>{cost}</b>\n💎 Balance: <b>{user['balance']}</b>")

@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "❌ No users yet.")
        return
    text = "🏆 <b>Top 10 Users</b>\n\n"
    for i, row in enumerate(rows, 1):
        name = row[0] or "Guest"
        text += f"{i}. {name} → {row[1]} coins\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(func=lambda m: m.text == "🔗 Referral Link")
def referral(message):
    user_id = str(message.from_user.id)
    link = f"https://t.me/{bot.get_me().username}?start={user_id}"
    bot.send_message(message.chat.id, f"🔗 Referral link:\n<code>{link}</code>\n\n👥 1 referral = +10 coins")

@bot.message_handler(func=lambda m: m.text == "🎮 Play Mini App")
def play_mini_app(message):
    markup = types.InlineKeyboardMarkup()
    web_app = types.WebAppInfo(url="https://hamster-miniapp.onrender.com")
    button = types.InlineKeyboardButton(text="Open Mini App", web_app=web_app)
    markup.add(button)
    bot.send_message(message.chat.id, "Play the Mini App:", reply_markup=markup)

# -----------------------------
# 🔹 Flask App (API + Static Frontend)
# -----------------------------
app = Flask(__name__)
FRONTEND_FOLDER = os.path.join(os.path.dirname(__file__), "frontend")  # ✅ same repo, sibling folder "frontend"

# ---- Static files (frontend) ----
@app.route("/")
def serve_index():
    return send_from_directory(FRONTEND_FOLDER, "index.html")

@app.route("/<path:path>")
def serve_static(path):
    return send_from_directory(FRONTEND_FOLDER, path)

# ---- API: user info ----
@app.route("/api/user/<user_id>")
def api_user(user_id):
    user = get_user(user_id)
    return {
        "user_id": user["user_id"],
        "username": user["username"] or "Guest",
        "balance": user["balance"],
        "per_click": user["per_click"],
        "auto_clicker_level": user["auto_clicker_level"]
    }

# ---- API: earn ----
@app.route("/api/earn", methods=["POST"])
def api_earn():
    data = request.get_json(force=True)
    user_id = str(data.get("user_id"))
    if not user_id:
        return {"error": "user_id required"}, 400
    user = get_user(user_id)
    new_balance = user["balance"] + user["per_click"]
    update_user(user_id, balance=new_balance)
    return {"ok": True, "balance": new_balance, "per_click": user["per_click"]}

# ---- API: buy (click/auto) ----
@app.route("/api/buy", methods=["POST"])
def api_buy():
    data = request.get_json(force=True)
    user_id = str(data.get("user_id"))
    item = data.get("item")
    if not user_id or not item:
        return {"error": "user_id and item required"}, 400
    user = get_user(user_id)

    if item == "click":
        cost = user["per_click"] * 50
        if user["balance"] < cost:
            return {"ok": False, "error": f"Need {cost} coins"}, 200
        update_user(user_id, balance=user["balance"] - cost, per_click=user["per_click"] + 1)
        return {"ok": True, "balance": user["balance"] - cost, "per_click": user["per_click"] + 1}

    elif item == "auto":
        # cost grows by level (100, 200, 300, ...)
        next_level = user["auto_clicker_level"] + 1
        cost = 100 * next_level
        if user["balance"] < cost:
            return {"ok": False, "error": f"Need {cost} coins"}, 200
        update_user(user_id,
                    balance=user["balance"] - cost,
                    auto_clicker_level=next_level)
        return {"ok": True, "balance": user["balance"] - cost, "auto_clicker_level": next_level}

    return {"error": "invalid item"}, 400

# ---- API: daily bonus (once per day UTC) ----
@app.route("/api/daily", methods=["POST"])
def api_daily():
    data = request.get_json(force=True)
    user_id = str(data.get("user_id"))
    if not user_id:
        return {"error": "user_id required"}, 400
    user = get_user(user_id)

    now = datetime.now(timezone.utc)
    today = now.date()
    last = None
    if user["daily_claim_at"]:
        try:
            last = datetime.fromisoformat(user["daily_claim_at"])
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
        except Exception:
            last = None

    if last and last.date() == today:
        return {"ok": False, "error": "Already claimed today"}, 200

    bonus = 50
    update_user(user_id, balance=user["balance"] + bonus, daily_claim_at=now)
    return {"ok": True, "bonus": bonus, "balance": user["balance"] + bonus}

# ---- API: leaderboard (top 10) ----
@app.route("/api/leaderboard")
def api_leaderboard():
    cursor.execute("SELECT username, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    return [{"username": (r[0] or "Guest"), "balance": r[1]} for r in rows]

# ---- API: exact rank for a user ----
@app.route("/api/rank/<user_id>")
def api_rank(user_id):
    # Use window function to compute rank by balance
    cursor.execute("""
        SELECT username, balance, rnk FROM (
            SELECT user_id, username, balance, RANK() OVER (ORDER BY balance DESC) AS rnk
            FROM users
        ) t
        WHERE user_id = %s
    """, (user_id,))
    row = cursor.fetchone()
    if not row:
        return {"error": "User not found"}, 404
    return {"username": row[0] or "Guest", "balance": row[1], "rank": int(row[2])}

# -----------------------------
# 🔹 Run
# -----------------------------
if __name__ == "__main__":
    t = threading.Thread(target=lambda: bot.polling(none_stop=True))
    t.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
