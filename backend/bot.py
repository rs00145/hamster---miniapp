import os
import telebot
from telebot import types
from flask import Flask, request
import psycopg2

# -----------------------------
# 🔹 Config
# -----------------------------
TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = telebot.TeleBot(TOKEN)

# -----------------------------
# 🔹 Database Setup
# -----------------------------
conn = psycopg2.connect(DATABASE_URL, sslmode="require")
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    balance INTEGER DEFAULT 0,
    per_click INTEGER DEFAULT 1,
    referrals INTEGER DEFAULT 0
)
""")
conn.commit()

# Helper functions
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    row = cursor.fetchone()
    if row is None:
        cursor.execute("INSERT INTO users (user_id) VALUES (%s)", (user_id,))
        conn.commit()
        return {"user_id": user_id, "balance": 0, "per_click": 1, "referrals": 0}
    return {"user_id": row[0], "balance": row[1], "per_click": row[2], "referrals": row[3]}

def update_user(user_id, balance=None, per_click=None, referrals=None):
    user = get_user(user_id)
    if balance is None:
        balance = user["balance"]
    if per_click is None:
        per_click = user["per_click"]
    if referrals is None:
        referrals = user["referrals"]

    cursor.execute("UPDATE users SET balance=%s, per_click=%s, referrals=%s WHERE user_id=%s",
                   (balance, per_click, referrals, user_id))
    conn.commit()

# -----------------------------
# 🔹 Telegram Bot Handlers
# -----------------------------
@bot.message_handler(commands=['start'])
def start(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)

    args = message.text.split()
    if len(args) > 1:
        referrer = args[1]
        if referrer != user_id:
            ref_user = get_user(referrer)
            new_balance = ref_user["balance"] + 10
            new_refs = ref_user["referrals"] + 1
            update_user(referrer, balance=new_balance, referrals=new_refs)
            bot.send_message(referrer, f"🎉 Referral mila! +10 coins\nTotal referrals: {new_refs}")

    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add("💰 Earn", "📊 Balance")
    markup.add("⚡ Upgrade", "🏆 Leaderboard")
    markup.add("🔗 Referral Link")
    markup.add("🎮 Play Mini App")  # new button for Web App

    bot.send_message(
        message.chat.id,
        f"👋 Welcome {message.from_user.first_name}!\n"
        f"💎 Balance: {user['balance']} coins\n"
        f"⚡ Per Click: {user['per_click']} coins\n\n"
        f"Tap karo aur coins earn karo 🚀",
        reply_markup=markup
    )

# Earn
@bot.message_handler(func=lambda m: m.text == "💰 Earn")
def earn(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    new_balance = user["balance"] + user["per_click"]
    update_user(user_id, balance=new_balance)
    bot.send_message(message.chat.id, f"🎉 +{user['per_click']} Coin!\n💎 Balance: {new_balance}")

# Balance
@bot.message_handler(func=lambda m: m.text == "📊 Balance")
def balance(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    bot.send_message(
        message.chat.id,
        f"📊 Balance: {user['balance']} coins\n⚡ Per Click: {user['per_click']}\n👥 Referrals: {user['referrals']}"
    )

# Upgrade
@bot.message_handler(func=lambda m: m.text == "⚡ Upgrade")
def upgrade(message):
    user_id = str(message.from_user.id)
    user = get_user(user_id)
    cost = user["per_click"] * 50
    if user["balance"] >= cost:
        new_balance = user["balance"] - cost
        new_click = user["per_click"] + 1
        update_user(user_id, balance=new_balance, per_click=new_click)
        bot.send_message(message.chat.id, f"✅ Upgrade Successful!\n⚡ New Per Click: {new_click}\n💸 Remaining: {new_balance}")
    else:
        bot.send_message(message.chat.id, f"❌ Not enough coins!\nCost: {cost}\n💎 Balance: {user['balance']}")

# Leaderboard
@bot.message_handler(func=lambda m: m.text == "🏆 Leaderboard")
def leaderboard(message):
    cursor.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cursor.fetchall()
    if not rows:
        bot.send_message(message.chat.id, "❌ No users yet.")
        return
    text = "🏆 Top 10 Users 🏆\n\n"
    for i, row in enumerate(rows, 1):
        text += f"{i}. User {row[0]} → {row[1]} coins\n"
    bot.send_message(message.chat.id, text)

# Referral
@bot.message_handler(func=lambda m: m.text == "🔗 Referral Link")
def referral(message):
    user_id = str(message.from_user.id)
    link = f"https://t.me/{bot.get_me().username}?start={user_id}"
    bot.send_message(message.chat.id, f"🔗 Referral link:\n{link}\n\n👥 1 referral = +10 coins")

# 🎮 Play Mini App (Telegram Web App)
@bot.message_handler(func=lambda m: m.text == "🎮 Play Mini App")
def play_mini_app(message):
    markup = types.InlineKeyboardMarkup()
    web_app = types.WebAppInfo(url="https://hamster-miniapp-1.onrender.com")
    button = types.InlineKeyboardButton(text="Open Mini App", web_app=web_app)
    markup.add(button)
    bot.send_message(message.chat.id, "Play the Mini App:", reply_markup=markup)

# -----------------------------
# 🔹 Flask for Render Health Check
# -----------------------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

if __name__ == "__main__":
    import threading
    t = threading.Thread(target=lambda: bot.polling(none_stop=True))
    t.start()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
