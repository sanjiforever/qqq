import logging
import asyncio
import sqlite3
import threading
from datetime import datetime, timedelta
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, LabeledPrice)
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                           MessageHandler, PreCheckoutQueryHandler,
                           ContextTypes, filters)

# CONFIG
BOT_TOKEN  = "8257704799:AAHKz6r02oL8SKhdehg6niT3IflvzeUFqJY"
CHANNEL_ID = -3915777311
ADMIN_IDS  = [7514690928]
DB_PATH    = "channel_bot.db"

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

# DATABASE
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)""")
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
        joined_at TEXT, expires_at TEXT, is_active INTEGER DEFAULT 0)""")
    c.execute("""CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER,
        stars INTEGER, days INTEGER, paid_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('stars_price', '100')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('days', '30')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('channel_name', 'Yopiq Kanal')")
    c.execute("INSERT OR IGNORE INTO settings VALUES ('welcome_msg', 'Xush kelibsiz! Obuna uchun pastdagi tugmani bosing.')")
    conn.commit()
    conn.close()

def get_setting(key):
    conn = sqlite3.connect(DB_PATH)
    r = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    conn.close()
    return r[0] if r else None

def set_setting(key, value):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT OR REPLACE INTO settings VALUES (?,?)", (key, value))
    conn.commit()
    conn.close()

def get_all_settings():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    conn.close()
    return dict(rows)

def upsert_user(user_id, username, full_name):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""INSERT INTO users (user_id, username, full_name) VALUES (?,?,?)
        ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name""",
        (user_id, username or "", full_name or ""))
    conn.commit()
    conn.close()

def activate_user(user_id, days):
    expires = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET is_active=1, joined_at=?, expires_at=? WHERE user_id=?",
        (datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"), expires, user_id))
    conn.commit()
    conn.close()

def deactivate_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("UPDATE users SET is_active=0 WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return dict(r) if r else None

def get_expired_users():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM users WHERE is_active=1 AND expires_at < datetime('now')").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM users ORDER BY joined_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def log_payment(user_id, stars, days):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("INSERT INTO payments (user_id, stars, days) VALUES (?,?,?)", (user_id, stars, days))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    total   = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    active  = conn.execute("SELECT COUNT(*) FROM users WHERE is_active=1 AND expires_at > datetime('now')").fetchone()[0]
    revenue = conn.execute("SELECT COALESCE(SUM(stars),0) FROM payments").fetchone()[0]
    today   = conn.execute("SELECT COUNT(*) FROM payments WHERE paid_at >= date('now')").fetchone()[0]
    conn.close()
    return {"total": total, "active": active, "revenue": revenue, "today": today}

# KEYBOARDS
def main_kb(user_id):
    rows = [
        [InlineKeyboardButton("Obuna bolish", callback_data="subscribe")],
        [InlineKeyboardButton("Mening obuna", callback_data="my_sub")],
        [InlineKeyboardButton("Yordam",       callback_data="help")],
    ]
    if user_id in ADMIN_IDS:
        rows.append([InlineKeyboardButton("Admin Panel", callback_data="admin")])
    return InlineKeyboardMarkup(rows)

def admin_kb():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Narx va muddat",    callback_data="admin_settings")],
        [InlineKeyboardButton("Foydalanuvchilar",  callback_data="admin_users")],
        [InlineKeyboardButton("Statistika",        callback_data="admin_stats")],
        [InlineKeyboardButton("Xabar yuborish",    callback_data="admin_broadcast")],
        [InlineKeyboardButton("Orqaga",            callback_data="main")],
    ])

def back_kb(target="main"):
    return InlineKeyboardMarkup([[InlineKeyboardButton("Orqaga", callback_data=target)]])

# HANDLERS
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    upsert_user(u.id, u.username, u.full_name)
    stars = get_setting("stars_price")
    days  = get_setting("days")
    ch    = get_setting("channel_name")
    msg   = get_setting("welcome_msg")
    user  = get_user(u.id)
    is_active = (user and user["is_active"] and user["expires_at"] and
                 datetime.utcnow() < datetime.strptime(user["expires_at"], "%Y-%m-%d %H:%M:%S"))
    if is_active:
        expire = user["expires_at"][:10]
        txt = (
            "Salom, " + u.full_name + "!\n\n"
            "Obunangiz faol!\n"
            "Tugash sanasi: " + expire + "\n\n"
            "Kanal: " + ch
        )
    else:
        txt = (
            "Salom, " + u.full_name + "!\n\n"
            + msg + "\n\n"
            "Kanal: " + ch + "\n"
            "Narxi: " + stars + " Stars\n"
            "Muddat: " + days + " kun\n\n"
            "Stars yoq? @tezstar_bot orqali UZS karta bilan sotib oling!"
        )
    await update.message.reply_text(txt, reply_markup=main_kb(u.id))

async def btn(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    u = update.effective_user
    data = q.data

    if data == "main":
        stars = get_setting("stars_price")
        days  = get_setting("days")
        ch    = get_setting("channel_name")
        txt = (
            "Bosh menyu\n\n"
            "Kanal: " + ch + "\n"
            "Narxi: " + stars + " Stars\n"
            "Muddat: " + days + " kun\n\n"
            "Stars yoq? @tezstar_bot orqali UZS karta bilan sotib oling!"
        )
        await q.edit_message_text(txt, reply_markup=main_kb(u.id))

    elif data == "subscribe":
        stars = get_setting("stars_price")
        days  = get_setting("days")
        txt = (
            "Tolov\n\n"
            "Narxi: " + stars + " Stars\n"
            "Muddat: " + days + " kun\n\n"
            "Stars yoq? @tezstar_bot orqali UZS karta bilan sotib oling!\n\n"
            "Tolash uchun:"
        )
        await q.edit_message_text(txt, reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("Stars bilan tolash", callback_data="pay_now")],
            [InlineKeyboardButton("Orqaga", callback_data="main")]]))

    elif data == "pay_now":
        stars = int(get_setting("stars_price"))
        days  = get_setting("days")
        ch    = get_setting("channel_name")
        await ctx.bot.send_invoice(
            chat_id=u.id,
            title=ch + " - Obuna",
            description=days + " kunlik obuna. Kanal: " + ch,
            payload="sub_" + str(u.id) + "_" + str(days),
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(days + " kunlik obuna", stars)])

    elif data == "my_sub":
        user = get_user(u.id)
        if not user or not user["is_active"]:
            await q.edit_message_text(
                "Sizda faol obuna yoq.\n\nObuna bolish uchun:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Obuna bolish", callback_data="subscribe")],
                    [InlineKeyboardButton("Orqaga", callback_data="main")]]))
            return
        exp_dt = datetime.strptime(user["expires_at"], "%Y-%m-%d %H:%M:%S")
        if datetime.utcnow() >= exp_dt:
            await q.edit_message_text(
                "Obunangiz muddati tugagan.\n\nYangilash uchun:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("Yangilash", callback_data="subscribe")],
                    [InlineKeyboardButton("Orqaga", callback_data="main")]]))
            return
        days_left = (exp_dt - datetime.utcnow()).days
        txt = (
            "Obunangiz faol!\n\n"
            "Tugash sanasi: " + user["expires_at"][:10] + "\n"
            "Qolgan kunlar: " + str(days_left) + " kun"
        )
        await q.edit_message_text(txt, reply_markup=back_kb("main"))

    elif data == "help":
        txt = (
            "Yordam\n\n"
            "1. Obuna bolish tugmasini bosing\n"
            "2. Stars yoq? @tezstar_bot dan sotib oling\n"
            "3. Stars bilan tolov qiling\n"
            "4. Kanalga avtomatik qoshilasiz\n\n"
            "Obuna tugaganda avtomatik chiqarilasiz\n\n"
            "Muammo bolsa adminga yozing"
        )
        await q.edit_message_text(txt, reply_markup=back_kb("main"))

    elif data == "admin" and u.id in ADMIN_IDS:
        s = get_all_settings()
        txt = (
            "Admin Panel\n\n"
            "Stars narxi: " + s.get("stars_price") + "\n"
            "Obuna muddati: " + s.get("days") + " kun\n"
            "Kanal nomi: " + s.get("channel_name")
        )
        await q.edit_message_text(txt, reply_markup=admin_kb())

    elif data == "admin_settings" and u.id in ADMIN_IDS:
        s = get_all_settings()
        txt = (
            "Sozlamalar\n\n"
            "Stars narxi: " + s.get("stars_price") + "\n"
            "Obuna muddati: " + s.get("days") + " kun\n"
            "Kanal nomi: " + s.get("channel_name") + "\n\n"
            "Ozgartirish uchun:\n"
            "/setprice 150 - Stars narxi\n"
            "/setdays 30 - Muddat (kun)\n"
            "/setname Kanal nomi - Kanal nomi\n"
            "/setmsg Xabar matni - Xush kelibsiz xabari"
        )
        await q.edit_message_text(txt, reply_markup=back_kb("admin"))

    elif data == "admin_stats" and u.id in ADMIN_IDS:
        s = get_stats()
        txt = (
            "Statistika\n\n"
            "Jami foydalanuvchilar: " + str(s["total"]) + "\n"
            "Faol obunalar: " + str(s["active"]) + "\n"
            "Jami Stars: " + str(s["revenue"]) + "\n"
            "Bugun tolovlar: " + str(s["today"])
        )
        await q.edit_message_text(txt, reply_markup=back_kb("admin"))

    elif data == "admin_users" and u.id in ADMIN_IDS:
        users = get_all_users()[:15]
        all_u = get_all_users()
        txt = "Foydalanuvchilar (" + str(len(all_u)) + " ta)\n\n"
        for uu in users:
            icon = "+" if uu["is_active"] else "-"
            name = uu["full_name"] or uu["username"] or str(uu["user_id"])
            exp  = uu["expires_at"][:10] if uu["expires_at"] else "-"
            txt += icon + " " + name[:15] + " - " + exp + "\n"
        await q.edit_message_text(txt, reply_markup=back_kb("admin"))

    elif data == "admin_broadcast" and u.id in ADMIN_IDS:
        ctx.user_data["broadcast_mode"] = True
        await q.edit_message_text(
            "Xabar yuborish\n\nBarcha foydalanuvchilarga yuboriladigan xabarni yozing:",
            reply_markup=back_kb("admin"))

# PAYMENT
async def precheckout(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

async def successful_payment(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u     = update.effective_user
    stars = update.message.successful_payment.total_amount
    days  = int(get_setting("days"))
    log_payment(u.id, stars, days)
    activate_user(u.id, days)
    try:
        link = await ctx.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID,
            member_limit=1,
            expire_date=datetime.utcnow() + timedelta(hours=24))
        expires = (datetime.utcnow() + timedelta(days=days)).strftime("%Y-%m-%d")
        await update.message.reply_text(
            "Tolov qabul qilindi!\n\n"
            + str(stars) + " Stars qabul qilindi\n"
            "Obuna: " + str(days) + " kun\n"
            "Tugash: " + expires + "\n\n"
            "Kanalga kirish havolasi:\n" + link.invite_link + "\n\n"
            "Havola 24 soat amal qiladi!")
        for admin_id in ADMIN_IDS:
            try:
                await ctx.bot.send_message(
                    admin_id,
                    "Yangi tolov!\n\n"
                    + (u.full_name or str(u.id)) + "\n"
                    + str(stars) + " Stars | " + str(days) + " kun")
            except Exception:
                pass
    except Exception as e:
        logger.error("invite link error: " + str(e))
        await update.message.reply_text("Tolov qabul qilindi! Admin tez orada havola yuboradi.")

# BROADCAST
async def handle_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    u = update.effective_user
    if u.id not in ADMIN_IDS:
        return
    if ctx.user_data.get("broadcast_mode"):
        ctx.user_data["broadcast_mode"] = False
        msg   = update.message.text
        users = get_all_users()
        sent  = 0
        for uu in users:
            try:
                await ctx.bot.send_message(uu["user_id"], msg)
                sent += 1
            except Exception:
                pass
        await update.message.reply_text(str(sent) + "/" + str(len(users)) + " foydalanuvchiga yuborildi.")

# ADMIN COMMANDS
async def set_price(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        set_setting("stars_price", str(int(ctx.args[0])))
        await update.message.reply_text("Stars narxi " + ctx.args[0] + " ga ozgartirildi!")
    except Exception:
        await update.message.reply_text("Format: /setprice 150")

async def set_days(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        set_setting("days", str(int(ctx.args[0])))
        await update.message.reply_text("Muddat " + ctx.args[0] + " kun ga ozgartirildi!")
    except Exception:
        await update.message.reply_text("Format: /setdays 30")

async def set_name(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    val = " ".join(ctx.args)
    if not val:
        await update.message.reply_text("Format: /setname Kanal nomi"); return
    set_setting("channel_name", val)
    await update.message.reply_text("Kanal nomi " + val + " ga ozgartirildi!")

async def set_msg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    val = " ".join(ctx.args)
    if not val:
        await update.message.reply_text("Format: /setmsg Xabar matni"); return
    set_setting("welcome_msg", val)
    await update.message.reply_text("Xush kelibsiz xabari yangilandi!")

async def add_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid  = int(ctx.args[0])
        days = int(get_setting("days"))
        upsert_user(uid, "", "")
        activate_user(uid, days)
        link = await ctx.bot.create_chat_invite_link(
            chat_id=CHANNEL_ID, member_limit=1,
            expire_date=datetime.utcnow() + timedelta(hours=24))
        await update.message.reply_text(str(uid) + " qoshildi!\nHavola: " + link.invite_link)
    except Exception as e:
        await update.message.reply_text("Format: /adduser USER_ID\n" + str(e))

async def remove_user(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS: return
    try:
        uid = int(ctx.args[0])
        deactivate_user(uid)
        await ctx.bot.ban_chat_member(CHANNEL_ID, uid)
        await asyncio.sleep(1)
        await ctx.bot.unban_chat_member(CHANNEL_ID, uid)
        await update.message.reply_text(str(uid) + " chiqarildi!")
    except Exception as e:
        await update.message.reply_text("Format: /removeuser USER_ID\n" + str(e))

# AUTO EXPIRY
def start_expiry_checker(app):
    async def check():
        while True:
            try:
                for u in get_expired_users():
                    try:
                        await app.bot.ban_chat_member(CHANNEL_ID, u["user_id"])
                        await asyncio.sleep(0.5)
                        await app.bot.unban_chat_member(CHANNEL_ID, u["user_id"])
                        deactivate_user(u["user_id"])
                        await app.bot.send_message(
                            u["user_id"],
                            "Obunangiz muddati tugadi.\n\nDavom etish uchun qayta obuna boling:",
                            reply_markup=InlineKeyboardMarkup([
                                [InlineKeyboardButton("Obuna bolish", callback_data="subscribe")]]))
                        logger.info("User " + str(u["user_id"]) + " chiqarildi")
                    except Exception as e:
                        logger.error("expiry error " + str(u["user_id"]) + ": " + str(e))
                        deactivate_user(u["user_id"])
            except Exception as e:
                logger.error("checker error: " + str(e))
            await asyncio.sleep(3600)

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(check())

    threading.Thread(target=run, daemon=True).start()
    logger.info("Obuna tekshiruvi boshlandi (har soatda)")

# MAIN
def main():
    init_db()
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start",      start))
    app.add_handler(CommandHandler("setprice",   set_price))
    app.add_handler(CommandHandler("setdays",    set_days))
    app.add_handler(CommandHandler("setname",    set_name))
    app.add_handler(CommandHandler("setmsg",     set_msg))
    app.add_handler(CommandHandler("adduser",    add_user))
    app.add_handler(CommandHandler("removeuser", remove_user))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(btn))
    start_expiry_checker(app)
    logger.info("Kanal bot ishga tushdi!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()
