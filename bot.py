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
    if not hasattr(_thread, "conn") or _thread.conn.closed:
        _thread.conn = psycopg2.connect(DATABASE_URL, sslmode="require")
        _thread.conn.autocommit = True
    return _thread.conn

def run_query(query, params=(), fetchone=False, fetchall=False):
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
# 🔹 Telegram Bot Handlers
# -----------------------------
@bot.message_handler(commands=["start"])
def start(message):
    user_id = str(message.from_user.id)
    username = message.from_user.username or message.from_user.first_name
    user = get_user(user_id, username=username)

    # referral system
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
                    f"🎉 <b>Referral joined!</b> +10 coins\nTotal referrals: {ref_user['referrals'] + 1}",
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
        "Tap to earn coins 🚀",
        reply_markup=markup,
    )

@bot.message_handler(func=lambda m: m.text == "💰 Earn")
def earn(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id, username=message.from_user.username or message.from_user.first_name)
    now = datetime.now(timezone.utc)

    if user["last_earn_at"]:
        last = datetime.fromisoformat(user["last_earn_at"]).replace(tzinfo=timezone.utc)
        if (now - last).total_seconds() < 2:
            bot.send_message(message.chat.id, "⏳ Wait 2 sec cooldown!")
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

    markup = types.InlineKeyboardMarkup()
    markup.add(
        types.InlineKeyboardButton("👆 Upgrade Click", callback_data="upgrade_click"),
        types.InlineKeyboardButton("🤖 Upgrade Auto", callback_data="upgrade_auto")
    )
    bot.send_message(message.chat.id, "Choose upgrade option:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data in ["upgrade_click", "upgrade_auto"])
def upgrade_callback(call):
    user_id = str(call.from_user.id)
    user = get_user(user_id)

    if call.data == "upgrade_click":
        cost = user["per_click"] * 50
        if user["balance"] < cost:
            bot.answer_callback_query(call.id, "❌ Not enough coins!")
            return
        update_user(user_id, balance=user["balance"] - cost, per_click=user["per_click"] + 1)
        bot.answer_callback_query(call.id, f"💪 Finger stronger! New per click: {user['per_click'] + 1}")

    elif call.data == "upgrade_auto":
        cost = (user["auto_clicker_level"] + 1) * 100
        if user["balance"] < cost:
            bot.answer_callback_query(call.id, "❌ Not enough coins!")
            return
        new_level = user["auto_clicker_level"] + 1
        update_user(user_id, balance=user["balance"] - cost, auto_clicker_level=new_level)

        boost_msgs = {
            1: "🚀 Auto-farm started! Coins every 10s!",
            2: "⚡ Clicker stronger! More coins now!",
            3: "🔥 Farming like a pro! Speed boost!",
            5: "🌟 Ultra boost unlocked! You're on fire!",
            10: "👑 MAX POWER! You are the Coin King!"
        }
        msg = boost_msgs.get(new_level, f"✅ Auto Clicker upgraded to Lv.{new_level}!")
        bot.answer_callback_query(call.id, msg)

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
# 🔹 Auto Clicker Worker
# -----------------------------
AUTO_PERIOD = 10
AUTO_PER_LEVEL = 2

def auto_clicker_worker():
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
# 🔹 Run
# -----------------------------
if __name__ == "__main__":
    threading.Thread(target=lambda: bot.polling(none_stop=True), daemon=True).start()
    threading.Thread(target=auto_clicker_worker, daemon=True).start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
