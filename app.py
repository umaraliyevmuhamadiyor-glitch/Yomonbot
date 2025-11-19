import os
import logging
import sqlite3
import asyncio
from concurrent.futures import ThreadPoolExecutor
from flask import Flask, request
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

# Configuration
BOT_TOKEN = "8333425528:AAFsEhVlEyKYuHIbB96opCuH5BJIea1P-UU"
ADMIN_ID = 7439952029
DB_FILE = 'bot_data.db'

# Flask app
app = Flask(__name__)

# Optimized logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Thread pool for blocking operations
thread_pool = ThreadPoolExecutor(max_workers=10)

# Database functions with caching
class Database:
    def __init__(self):
        self._channels_cache = None
        self._tutorial_cache = None
        self._coupon_cache = None
        self._user_count_cache = None
        
    def init_db(self):
        conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                subscribed BOOLEAN DEFAULT FALSE,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_link TEXT UNIQUE,
                added_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tutorial (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                video_file_id TEXT,
                tutorial_text TEXT,
                updated_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        self._clear_cache()
    
    def _clear_cache(self):
        self._channels_cache = None
        self._tutorial_cache = None
        self._coupon_cache = None
        self._user_count_cache = None
    
    def get_connection(self):
        return sqlite3.connect(DB_FILE, check_same_thread=False)
    
    def get_required_channels(self):
        if self._channels_cache is not None:
            return self._channels_cache
            
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT channel_link FROM channels')
        channels = [row[0] for row in cursor.fetchall()]
        conn.close()
        self._channels_cache = channels
        return channels
    
    def get_tutorial(self):
        if self._tutorial_cache is not None:
            return self._tutorial_cache
            
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT video_file_id, tutorial_text FROM tutorial ORDER BY id DESC LIMIT 1')
        result = cursor.fetchone()
        conn.close()
        self._tutorial_cache = result if result else (None, None)
        return self._tutorial_cache
    
    def get_coupon_channel(self):
        if self._coupon_cache is not None:
            return self._coupon_cache
            
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT channel_link FROM coupon_channel LIMIT 1')
        result = cursor.fetchone()
        conn.close()
        self._coupon_cache = result[0] if result else "https://t.me/example_channel"
        return self._coupon_cache
    
    def get_user_count(self):
        if self._user_count_cache is not None:
            return self._user_count_cache
            
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM users')
        count = cursor.fetchone()[0]
        conn.close()
        self._user_count_cache = count
        return count
    
    def add_user(self, user_id, username, first_name):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO users (user_id, username, first_name) 
            VALUES (?, ?, ?)
        ''', (user_id, username, first_name))
        conn.commit()
        conn.close()
    
    def add_channel(self, channel_link):
        conn = self.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute('INSERT OR IGNORE INTO channels (channel_link) VALUES (?)', (channel_link,))
            conn.commit()
            self._clear_cache()
            return True
        except:
            return False
        finally:
            conn.close()
    
    def remove_channel(self, channel_link):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM channels WHERE channel_link = ?', (channel_link,))
        conn.commit()
        conn.close()
        self._clear_cache()
    
    def set_tutorial(self, video_file_id, tutorial_text):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('INSERT INTO tutorial (video_file_id, tutorial_text) VALUES (?, ?)', 
                      (video_file_id, tutorial_text))
        conn.commit()
        conn.close()
        self._clear_cache()
    
    def set_coupon_channel(self, channel_link):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('DELETE FROM coupon_channel')
        cursor.execute('INSERT INTO coupon_channel (channel_link) VALUES (?)', (channel_link,))
        conn.commit()
        conn.close()
        self._clear_cache()
    
    def get_all_users(self):
        conn = self.get_connection()
        cursor = conn.cursor()
        cursor.execute('SELECT user_id FROM users')
        users = [row[0] for row in cursor.fetchall()]
        conn.close()
        return users

# Global database instance
db = Database()

# Fast response functions
async def check_subscription_fast(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Tez obuna tekshirish"""
    required_channels = db.get_required_channels()
    
    if not required_channels:
        return True
    
    # Bir vaqtning o'zida barcha kanallarni tekshirish
    tasks = []
    for channel in required_channels:
        try:
            channel_username = channel.replace('https://t.me/', '@')
            task = context.bot.get_chat_member(channel_username, user_id)
            tasks.append(task)
        except Exception as e:
            logger.error(f"Channel error {channel}: {e}")
            continue
    
    if not tasks:
        return True
    
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in results:
            if not isinstance(result, Exception) and result.status in ['left', 'kicked']:
                return False
        return True
    except Exception as e:
        logger.error(f"Subscription check error: {e}")
        return True

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    
    # Ma'lumotlarni bazaga saqlash (threadda)
    await asyncio.get_event_loop().run_in_executor(
        thread_pool, 
        db.add_user, 
        user.id, user.username, user.first_name
    )
    
    # Tez obuna tekshirish
    is_subscribed = await check_subscription_fast(user.id, context)
    
    if is_subscribed:
        await show_main_menu_fast(update, context)
    else:
        await show_subscription_request_fast(update, context)

async def show_main_menu_fast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = """Men 8 yildan buyon 1xbet blan shartnimam bor va men 1xbet orqali qanday qilib 1 kunda 3-6 milon som topish yollarini topdim ushbu bot 98% aniq javoblarni beradi"""
    
    keyboard = [
        [InlineKeyboardButton("Admin", callback_data="admin")],
        [InlineKeyboardButton("Qo'llanma", callback_data="tutorial")],
        [InlineKeyboardButton("Kupon Kanallar", callback_data="coupon_channels")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    if update.message:
        await update.message.reply_text(message_text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)

async def show_subscription_request_fast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    required_channels = db.get_required_channels()
    
    if not required_channels:
        await show_main_menu_fast(update, context)
        return
    
    channels_text = "Iltimos, quyidagi kanallarga obuna bo'ling:\n\n"
    buttons = []
    
    for channel in required_channels:
        channel_name = channel.replace('https://t.me/', '@')
        channels_text += f"• {channel_name}\n"
        buttons.append([InlineKeyboardButton(f"Obuna bo'lish → {channel_name}", url=channel)])
    
    buttons.append([InlineKeyboardButton("✅ Obuna bo'ldim", callback_data="check_subscription")])
    reply_markup = InlineKeyboardMarkup(buttons)
    
    if update.message:
        await update.message.reply_text(channels_text, reply_markup=reply_markup)
    else:
        await update.callback_query.edit_message_text(channels_text, reply_markup=reply_markup)

# Optimized button handler
async def button_handler_fast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    # Darhol javob berish
    await query.answer()
    
    if data == "check_subscription":
        is_subscribed = await check_subscription_fast(user_id, context)
        
        if is_subscribed:
            await show_main_menu_fast(update, context)
        else:
            await query.answer("Iltimos, barcha kanallarga obuna bo'ling!", show_alert=True)
    
    elif data == "admin":
        await query.edit_message_text("@xbeteuz adminga murojat qiling")
    
    elif data == "tutorial":
        video_file_id, tutorial_text = db.get_tutorial()
        if video_file_id and tutorial_text:
            await query.message.reply_video(video_file_id, caption=tutorial_text)
            await query.message.reply_text("Asosiy menyuga qaytish uchun /start ni bosing")
        else:
            await query.edit_message_text("Qo'llanma hozircha mavjud emas")
    
    elif data == "coupon_channels":
        coupon_channel = db.get_coupon_channel()
        keyboard = [[InlineKeyboardButton("Kupon Kanali", url=coupon_channel)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Kupon kanalimizga obuna bo'ling:", reply_markup=reply_markup)
    
    # Admin panel - tez versiya
    elif data == "admin_panel":
        if user_id == ADMIN_ID:
            keyboard = [
                [InlineKeyboardButton("📹 Qo'llanma", callback_data="admin_tutorial")],
                [InlineKeyboardButton("📢 Kanallar", callback_data="admin_channels")],
                [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
                [InlineKeyboardButton("📢 Reklama", callback_data="admin_broadcast")],
                [InlineKeyboardButton("🎫 Kupon", callback_data="admin_coupon")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text("Admin panel:", reply_markup=reply_markup)
        else:
            await query.answer("Siz admin emassiz!", show_alert=True)
    
    elif data == "admin_tutorial":
        if user_id == ADMIN_ID:
            video_file_id, tutorial_text = db.get_tutorial()
            status_text = f"📹 Qo'llanma holati:\n\n"
            status_text += f"Video: {'✅ Mavjud' if video_file_id else '❌ Yoq'}\n"
            status_text += f"Matn: {'✅ Mavjud' if tutorial_text else '❌ Yoq'}\n\n"
            status_text += "Yangi qo'llanma qo'shish uchun /set_tutorial buyrug'ini yuboring"
            await query.edit_message_text(status_text)
    
    elif data == "admin_channels":
        if user_id == ADMIN_ID:
            channels = db.get_required_channels()
            channels_text = "📢 Majburiy kanallar:\n\n"
            if channels:
                for i, channel in enumerate(channels, 1):
                    channels_text += f"{i}. {channel}\n"
            else:
                channels_text += "Hozircha kanallar yo'q\n"
            
            channels_text += "\n/qoshish - kanal qo'shish\n/ochirish - kanal o'chirish"
            await query.edit_message_text(channels_text)
    
    elif data == "admin_stats":
        if user_id == ADMIN_ID:
            user_count = db.get_user_count()
            channel_count = len(db.get_required_channels())
            stats_text = f"📊 Bot statistikasi:\n\n"
            stats_text += f"👥 Foydalanuvchilar: {user_count}\n"
            stats_text += f"📢 Kanallar: {channel_count}\n"
            stats_text += f"⚡ Status: Faol"
            await query.edit_message_text(stats_text)
    
    elif data == "admin_broadcast":
        if user_id == ADMIN_ID:
            await query.edit_message_text(
                "📢 Reklama xizmati:\n\n"
                "Barcha foydalanuvchilarga xabar yuborish uchun:\n"
                "Matn, rasm yoki video yuboring\n\n"
                "Bekor qilish: /cancel"
            )
            context.user_data['waiting_for_broadcast'] = True
    
    elif data == "admin_coupon":
        if user_id == ADMIN_ID:
            current_coupon = db.get_coupon_channel()
            await query.edit_message_text(
                f"🎫 Kupon kanali:\n\n"
                f"Joriy: {current_coupon}\n\n"
                "Yangilash uchun kanal linkini yuboring:"
            )
            context.user_data['waiting_for_coupon_channel'] = True
    
    elif data == "add_channel":
        if user_id == ADMIN_ID:
            await query.edit_message_text("Kanal linkini yuboring (https://t.me/... formatida):")
            context.user_data['waiting_for_channel_link'] = True
    
    elif data == "remove_channel":
        if user_id == ADMIN_ID:
            channels = db.get_required_channels()
            if channels:
                keyboard = [[InlineKeyboardButton(f"❌ {ch}", callback_data=f"remove_{ch}")] for ch in channels]
                keyboard.append([InlineKeyboardButton("🔙 Orqaga", callback_data="admin_channels")])
                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text("O'chirish uchun kanalni tanlang:", reply_markup=reply_markup)
            else:
                await query.edit_message_text("O'chirish uchun kanal yo'q")
    
    elif data.startswith("remove_"):
        if user_id == ADMIN_ID:
            channel_link = data.replace("remove_", "")
            db.remove_channel(channel_link)
            await query.answer(f"O'chirildi: {channel_link}", show_alert=True)
            await query.edit_message_text(f"✅ Kanal o'chirildi: {channel_link}")

# Tez admin komandalari
async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        keyboard = [
            [InlineKeyboardButton("📹 Qo'llanma", callback_data="admin_tutorial")],
            [InlineKeyboardButton("📢 Kanallar", callback_data="admin_channels")],
            [InlineKeyboardButton("📊 Statistika", callback_data="admin_stats")],
            [InlineKeyboardButton("📢 Reklama", callback_data="admin_broadcast")],
            [InlineKeyboardButton("🎫 Kupon", callback_data="admin_coupon")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Admin panel:", reply_markup=reply_markup)
    else:
        await update.message.reply_text("Siz admin emassiz!")

async def set_tutorial(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("Video qo'llanamani sozlash:\n\nAvval video yuboring:")
        context.user_data['waiting_for_tutorial_video'] = True
    else:
        await update.message.reply_text("Siz admin emassiz!")

async def qoshish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text("Kanal linkini yuboring (https://t.me/...):")
        context.user_data['waiting_for_channel_link'] = True
    else:
        await update.message.reply_text("Siz admin emassiz!")

async def ochirish(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        channels = db.get_required_channels()
        if channels:
            keyboard = [[InlineKeyboardButton(f"❌ {ch}", callback_data=f"remove_{ch}")] for ch in channels]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text("O'chirish uchun kanalni tanlang:", reply_markup=reply_markup)
        else:
            await update.message.reply_text("O'chirish uchun kanal yo'q")
    else:
        await update.message.reply_text("Siz admin emassiz!")

async def kupon(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        current = db.get_coupon_channel()
        await update.message.reply_text(
            f"Joriy kupon kanali: {current}\n\n"
            "Yangilash uchun yangi link yuboring:"
        )
        context.user_data['waiting_for_coupon_channel'] = True
    else:
        await update.message.reply_text("Siz admin emassiz!")

async def reklama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        await update.message.reply_text(
            "📢 Reklama yuborish:\n\n"
            "Xabaringizni yuboring (matn, rasm, video):\n"
            "Bekor qilish: /cancel"
        )
        context.user_data['waiting_for_broadcast'] = True
    else:
        await update.message.reply_text("Siz admin emassiz!")

# Tez message handler
async def handle_message_fast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Admin uchun kanal qo'shish
    if user_id == ADMIN_ID and context.user_data.get('waiting_for_channel_link'):
        channel_link = update.message.text.strip()
        if channel_link.startswith('https://t.me/'):
            success = await asyncio.get_event_loop().run_in_executor(
                thread_pool, db.add_channel, channel_link
            )
            if success:
                await update.message.reply_text(f"✅ Kanal qo'shildi: {channel_link}")
            else:
                await update.message.reply_text("❌ Bu kanal allaqachon mavjud")
        else:
            await update.message.reply_text("❌ Noto'g'ri format. https://t.me/... ko'rinishida bo'lishi kerak")
        context.user_data.pop('waiting_for_channel_link', None)
    
    # Admin uchun video qo'llanma
    elif user_id == ADMIN_ID and context.user_data.get('waiting_for_tutorial_video'):
        if update.message.video:
            context.user_data['tutorial_video'] = update.message.video.file_id
            context.user_data['waiting_for_tutorial_video'] = False
            context.user_data['waiting_for_tutorial_text'] = True
            await update.message.reply_text("✅ Video qabul qilindi. Endi qo'llanma matnini yuboring:")
        else:
            await update.message.reply_text("❌ Iltimos, video yuboring")
    
    elif user_id == ADMIN_ID and context.user_data.get('waiting_for_tutorial_text'):
        tutorial_text = update.message.text
        video_file_id = context.user_data.get('tutorial_video')
        
        if video_file_id and tutorial_text:
            await asyncio.get_event_loop().run_in_executor(
                thread_pool, db.set_tutorial, video_file_id, tutorial_text
            )
            await update.message.reply_text("✅ Qo'llanma muvaffaqiyatli saqlandi!")
            context.user_data.clear()
    
    # Admin uchun reklama xizmati
    elif user_id == ADMIN_ID and context.user_data.get('waiting_for_broadcast'):
        users = db.get_all_users()
        sent_count = 0
        error_count = 0
        
        for user_id in users:
            try:
                if update.message.text:
                    await context.bot.send_message(chat_id=user_id, text=update.message.text)
                elif update.message.photo:
                    await context.bot.send_photo(chat_id=user_id, photo=update.message.photo[-1].file_id, caption=update.message.caption)
                elif update.message.video:
                    await context.bot.send_video(chat_id=user_id, video=update.message.video.file_id, caption=update.message.caption)
                sent_count += 1
                await asyncio.sleep(0.05)  # Rate limit
            except Exception as e:
                error_count += 1
                logger.error(f"Broadcast error: {e}")
        
        await update.message.reply_text(
            f"📢 Reklama natijasi:\n\n"
            f"✅ Yuborildi: {sent_count}\n"
            f"❌ Xatolar: {error_count}\n"
            f"📊 Jami: {len(users)}"
        )
        context.user_data['waiting_for_broadcast'] = False
    
    # Admin uchun kupon kanali
    elif user_id == ADMIN_ID and context.user_data.get('waiting_for_coupon_channel'):
        channel_link = update.message.text.strip()
        if channel_link.startswith('https://t.me/'):
            await asyncio.get_event_loop().run_in_executor(
                thread_pool, db.set_coupon_channel, channel_link
            )
            await update.message.reply_text(f"✅ Kupon kanali yangilandi: {channel_link}")
        else:
            await update.message.reply_text("❌ Noto'g'ri format")
        context.user_data['waiting_for_coupon_channel'] = False

# Bekor qilish
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        context.user_data.clear()
        await update.message.reply_text("❌ Amal bekor qilindi")
    else:
        await update.message.reply_text("Siz admin emassiz!")

# Flask routes
@app.route('/')
def home():
    return "Bot ishlayapti! 🚀"

@app.route('/webhook', methods=['POST'])
async def webhook():
    if request.method == "POST":
        try:
            json_str = request.get_data().decode('UTF-8')
            update = Update.de_json(json_str, application.bot)
            await application.process_update(update)
        except Exception as e:
            logger.error(f"Webhook error: {e}")
        return 'ok'

# Application setup
application = Application.builder().token(BOT_TOKEN).build()

# Handlers
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("admin", admin))
application.add_handler(CommandHandler("set_tutorial", set_tutorial))
application.add_handler(CommandHandler("qoshish", qoshish))
application.add_handler(CommandHandler("ochirish", ochirish))
application.add_handler(CommandHandler("kupon", kupon))
application.add_handler(CommandHandler("reklama", reklama))
application.add_handler(CommandHandler("cancel", cancel))
application.add_handler(CallbackQueryHandler(button_handler_fast))
application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message_fast))

# Initialize
def initialize():
    db.init_db()
    logger.info("Database initialized")
    
    # Webhook setup for Render
    webhook_url = os.environ.get('RENDER_EXTERNAL_URL', '')
    if webhook_url:
        webhook_url += '/webhook'
        application.run_webhook(
            listen="0.0.0.0",
            port=int(os.environ.get('PORT', 5000)),
            webhook_url=webhook_url,
            secret_token='WEBHOOK_SECRET'
        )
        logger.info(f"Webhook mode: {webhook_url}")
    else:
        application.run_polling()
        logger.info("Polling mode")

if __name__ == '__main__':
    initialize()
