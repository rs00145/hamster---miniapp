import os
import time
import json
import telebot
from telebot import types
from threading import Thread
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('BOT_TOKEN')
DATABASE_URL = os.getenv('DATABASE_URL')
FRONTEND_URL = os.getenv('FRONTEND_URL')  # e.g. https://your-frontend.example

if not BOT_TOKEN or not DATABASE_URL or not FRONTEND_URL:
    raise RuntimeError('Please set BOT_TOKEN, DATABASE_URL and FRONTEND_URL environment variables')

# Telegram bot
bot = telebot.TeleBot(BOT_TOKEN, threaded=True)

# Flask app for API
app = Flask(__name__, static_folder='frontend', static_url_path='/')
CORS(app)

# PostgreSQL helper
def get_conn():
    return psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

# Initialize DB (run once on start)
def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        balance BIGINT DEFAULT 0,
        per_click INTEGER DEFAULT 1,
        referrals INTEGER DEFAULT 0,
        auto_clicker_level INTEGER DEFAULT 0,
        last_daily BIGINT DEFAULT 0
    )
    """)
    conn.commit()
    cur.close()
    conn.close()

init_db()

# Helper functions
def ensure_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    if not row:
        cur.execute("INSERT INTO users (user_id) VALUES (%s)", (user_id,))
        conn.commit()
        cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
        row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def get_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE user_id=%s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row

def update_user(user_id, **kwargs):
    # allowed keys: balance, per_click, referrals, auto_clicker_level, last_daily
    keys = []
    vals = []
    for k, v in kwargs.items():
        if k in ('balance', 'per_click', 'referrals', 'auto_clicker_level', 'last_daily'):
            keys.append(f"{k}=%s")
            vals.append(v)
    if not keys:
        return
    vals.append(user_id)
    sql = f"UPDATE users SET {', '.join(keys)} WHERE user_id=%s"
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(sql, tuple(vals))
    conn.commit()
    cur.close()
    conn.close()

# Auto-clicker background thread
def auto_clicker_loop():
    while True:
        try:
            conn = get_conn()
            cur = conn.cursor()
            cur.execute("SELECT user_id, auto_clicker_level FROM users WHERE auto_clicker_level>0")
            rows = cur.fetchall()
            for r in rows:
                uid = r['user_id']
                lvl = r['auto_clicker_level'] or 0
                if lvl > 0:
                    cur.execute("UPDATE users SET balance = balance + %s WHERE user_id=%s", (lvl, uid))
            conn.commit()
            cur.close()
            conn.close()
        except Exception as e:
            print('Auto-clicker error:', e)
        time.sleep(30)

Thread(target=auto_clicker_loop, daemon=True).start()

# ========== Telegram bot handlers (basic) ==========
@bot.message_handler(commands=['start'])
def start(message):
    user_id = str(message.from_user.id)
    ensure_user(user_id)

    # referral handling if provided
    args = message.text.split()
    if len(args) > 1:
        ref = args[1]
        if ref != user_id:
            ensure_user(ref)
            u = get_user(ref)
            new_bal = (u['balance'] or 0) + 10
            new_refs = (u['referrals'] or 0) + 1
            update_user(ref, balance=new_bal, referrals=new_refs)
            bot.send_message(ref, f"🎉 Aapko 1 referral mila! +10 coins. Total referrals: {new_refs}")

    # Inline keyboard with Play button (opens mini app URL with user_id)
    markup = types.InlineKeyboardMarkup()
    play_url = f"{FRONTEND_URL}/?user_id={user_id}"
    markup.add(types.InlineKeyboardButton('▶️ Play Hamster', url=play_url))
    markup.add(types.InlineKeyboardButton('📊 Balance', callback_data='balance'))

    bot.send_message(message.chat.id, f"Welcome {message.from_user.first_name}! Play the Hamster mini app.", reply_markup=markup)

@bot.callback_query_handler(func=lambda c: True)
def cb_handler(call):
    user_id = str(call.from_user.id)
    if call.data == 'balance':
        u = get_user(user_id)
        bot.answer_callback_query(call.id, f"Balance: {u['balance']} coins")

# Start bot polling in a separate thread so Flask can run
def start_telegram_polling():
    print('Starting Telegram polling...')
    bot.infinity_polling()

Thread(target=start_telegram_polling, daemon=True).start()

# ========== Flask API endpoints used by frontend ============
@app.route('/api/user/<user_id>', methods=['GET'])
def api_get_user(user_id):
    ensure_user(user_id)
    u = get_user(user_id)
    return jsonify(u)

@app.route('/api/earn', methods=['POST'])
def api_earn():
    data = request.json or {}
    user_id = str(data.get('user_id'))
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    u = ensure_user(user_id)
    per_click = u['per_click'] or 1
    new_bal = (u['balance'] or 0) + per_click
    update_user(user_id, balance=new_bal)
    return jsonify({'balance': new_bal, 'per_click': per_click})

@app.route('/api/buy', methods=['POST'])
def api_buy():
    data = request.json or {}
    user_id = str(data.get('user_id'))
    item = data.get('item')
    if not user_id or not item:
        return jsonify({'error': 'user_id and item required'}), 400
    u = ensure_user(user_id)
    bal = u['balance'] or 0
    response = {'ok': False}
    if item == 'auto':
        cost = 100
        if bal >= cost:
            new_bal = bal - cost
            new_lvl = (u['auto_clicker_level'] or 0) + 1
            update_user(user_id, balance=new_bal, auto_clicker_level=new_lvl)
            response = {'ok': True, 'balance': new_bal, 'auto_clicker_level': new_lvl}
        else:
            response = {'ok': False, 'error': 'Not enough coins'}
    elif item == 'click':
        cost = 50
        if bal >= cost:
            new_bal = bal - cost
            new_click = (u['per_click'] or 1) + 1
            update_user(user_id, balance=new_bal, per_click=new_click)
            response = {'ok': True, 'balance': new_bal, 'per_click': new_click}
        else:
            response = {'ok': False, 'error': 'Not enough coins'}
    else:
        response = {'ok': False, 'error': 'Unknown item'}
    return jsonify(response)

@app.route('/api/daily', methods=['POST'])
def api_daily():
    data = request.json or {}
    user_id = str(data.get('user_id'))
    if not user_id:
        return jsonify({'error': 'user_id required'}), 400
    u = ensure_user(user_id)
    now = int(time.time())
    if now - (u['last_daily'] or 0) >= 86400:
        bonus = 50
        new_bal = (u['balance'] or 0) + bonus
        update_user(user_id, balance=new_bal, last_daily=now)
        return jsonify({'ok': True, 'balance': new_bal, 'bonus': bonus})
    return jsonify({'ok': False, 'error': 'Already claimed'})

@app.route('/api/leaderboard', methods=['GET'])
def api_leaderboard():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify(rows)

# Serve frontend static files
@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/<path:path>')
def static_proxy(path):
    return send_from_directory(app.static_folder, path)

# Run Flask when executed (Render will use gunicorn in Procfile)
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
