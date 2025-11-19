import os
import logging
import sqlite3
from flask import Flask, request
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, CallbackQueryHandler, MessageHandler, filters, Application, ContextTypes

# Configuration
BOT_TOKEN = "8333425528:AAFsEhVlEyKYuHIbB96opCuH5BJIea1P-UU"
ADMIN_ID = 7439952029
DB_FILE = 'bot_data.db'

app = Flask(__name__)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Database
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_link TEXT UNIQUE
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS tutorial (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_file_id TEXT,
            tutorial_text TEXT
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS coupon_channel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_link TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def get_connection():
    return sqlite3.connect(DB_FILE)

def get_required_channels():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT channel_link FROM channels')
    channels = [row[0] for row in cursor.fetchall()]
    conn.close()
    return channels

def get_tutorial():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT video_file_id, tutorial_text FROM tutorial ORDER BY id DESC LIMIT 1')
    result = cursor.fetchone()
    conn.close()
    return result if result else (None, None)

def get_coupon_channel():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT channel_link FROM coupon_channel LIMIT 1')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else "https://t.me/example_channel"

def get_user_count():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def add_user(user_id, username, first_name):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT OR REPLACE INTO users (user_id, username, first_name) VALUES (?, ?, ?)', 
                  (user_id, username, first_name))
    conn.commit()
    conn.close()

def add_channel(channel_link):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('INSERT OR IGNORE INTO channels (channel_link) VALUES (?)', (channel_link,))
        conn.commit()
        return True
    except:
        return False
    finally:
        conn.close()

def remove_channel(channel_link):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM channels WHERE channel_link = ?', (channel_link,))
    conn.commit()
    conn.close()

def set_tutorial(video_file_id, tutorial_text):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('INSERT INTO tutorial (video_file_id, tutorial_text) VALUES (?, ?)', 
                  (video_file_id, tutorial_text))
    conn.commit()
    conn.close()

def set_coupon_channel(channel_link):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM coupon_channel')
    cursor.execute('INSERT INTO coupon_channel (channel_link) VALUES (?)', (channel_link,))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = [row[0] for row in cursor.fetchall()]
    conn.close()
    return users

# Bot functions
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name)
    
    await update.message.reply_text(
        "Men 8 yildan buyon 1xbet blan shartnimam bor va men 1xbet orqali qanday qilib 1 kunda 3-6 milon som topish yollarini topdim ushbu bot 98% aniq javoblarni beradi",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Admin", callback_data="admin")],
            [InlineKeyboardButton("Qo'llanma", callback_data="tutorial")],
            [InlineKeyboardButton("Kupon Kanallar", callback_data="coupon_channels")]
        ])
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "admin":
        await query.edit_message_text("@xbeteuz adminga murojat qiling")
    
    elif data == "tutorial":
        video_file_id, tutorial_text = get_tutorial()
        if video_file_id and tutorial_text:
            await query.message.reply_video(video_file_id, caption=tutorial_text)
        else:
            await query.edit_message_text("Qo'llanma hozircha mavjud emas")
    
    elif data == "coupon_channels":
        coupon_channel = get_coupon_channel()
        await query.edit_message_text(
            f"Kupon kanalimizga obuna bo'ling: {coupon_channel}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Kupon Kanali", url=coupon_channel)]
            ])
        )

async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(
            "Admin panel:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📊 Statistika", callback_data="stats")],
                [InlineKeyboardButton("📢 Reklama", callback_data="broadcast")],
                [InlineKeyboardButton("🎫 Kupon", callback_data="set_coupon")]
            ])
        )

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        user_count = get_user_count()
        await update.message.reply_text(f"Foydalanuvchilar: {user_count}")

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("Reklama xabarini yuboring:")
        context.user_data['broadcasting'] = True

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID and context.user_data.get('broadcasting'):
        users = get_all_users()
        success = 0
        
        for user_id in users:
            try:
                await context.bot.send_message(user_id, update.message.text)
                success += 1
            except:
                pass
        
        await update.message.reply_text(f"Xabar {success} foydalanuvchiga yuborildi")
        context.user_data['broadcasting'] = False

# Flask routes
@app.route('/')
def home():
    return "Bot ishlayapti! ✅"

@app.route('/webhook', methods=['POST'])
def webhook():
    update = Update.de_json(request.get_json(), bot)
    application.process_update(update)
    return 'ok'

# Initialize
init_db()
bot = Bot(token=BOT_TOKEN)
application = Application.builder().token(BOT_TOKEN).build()

# Handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin_command))
application.add_handler(CommandHandler("stats", admin_stats))
application.add_handler(CommandHandler("reklama", broadcast_command))
application.add_handler(CallbackQueryHandler(button_handler))
application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

if __name__ == '__main__':
    application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get('PORT', 5000)),
        webhook_url=os.environ.get('RENDER_EXTERNAL_URL', '') + '/webhook',
        secret_token='WEBHOOK_SECRET'
    )
