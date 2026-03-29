import telebot
from telebot import types
import sqlite3
import requests

# === КОНФИГУРАЦИЯ ===
TOKEN = "8656129697:AAH4g6qI-7aRKH7yYEA_1j_CHUJKHhmb5PI"
CRYPTO_TOKEN = "558894:AATjq3d3xESUI4XFNSMlzL32oDDLigfkxok"
ADMIN_ID = 6498779131

bot = telebot.TeleBot(TOKEN)

# === БАЗА ДАННЫХ ===
def db_query(sql, params=(), fetchone=False, commit=False):
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    res = cursor.fetchone() if fetchone else cursor.fetchall()
    if commit: conn.commit()
    conn.close()
    return res

def init_db():
    db_query('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0, ref_from INTEGER)''', commit=True)
    db_query('''CREATE TABLE IF NOT EXISTS orders 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, cat TEXT, desc TEXT, status TEXT, price REAL)''', commit=True)
    # Новая структура: код, сумма скидки и категория (Сайт/Бот)
    db_query('''CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, discount REAL, cat TEXT)''', commit=True)

init_db()

# === КРИПТО ОПЛАТА ===
def create_invoice(amount, desc):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {"asset": "USDT", "amount": str(round(amount, 2)), "description": desc}
    try:
        r = requests.post(url, headers=headers, json=data).json()
        return r['result']
    except: return None

# === СТАРТ ===
@bot.message_handler(commands=['start'])
def start(m):
    uid = m.from_user.id
    args = m.text.split()
    ref_from = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None
    db_query("INSERT OR IGNORE INTO users (user_id, username, ref_from) VALUES (?, ?, ?)", (uid, m.from_user.username, ref_from), commit=True)
    
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🌐 Заказать сайт ($50)", "🤖 Заказать ТГ Бота ($15)")
    kb.add("💰 Баланс", "📊 Статус")
    if uid == ADMIN_ID: kb.add("🛠 Админ-панель")
    bot.send_message(m.chat.id, "🚀 Добро пожаловать в DEV Studio!", reply_markup=kb)

# === АДМИН-ПАНЕЛЬ ===
@bot.message_handler(func=lambda m: m.text == "🛠 Админ-панель" and m.from_user.id == ADMIN_ID)
def admin_panel(m):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("📢 Рассылка", callback_data="adm_broadcast"))
    kb.add(types.InlineKeyboardButton("🎟 Промо для САЙТА", callback_data="promo_site"),
           types.InlineKeyboardButton("🎟 Промо для БОТА", callback_data="promo_bot"))
    bot.send_message(m.chat.id, "🔧 Управление маркетингом:", reply_markup=kb)

@bot.callback_query_handler(func=lambda c: c.data.startswith("promo_"))
def admin_promo_init(c):
    cat = "Сайт" if "site" in c.data else "ТГ Бот"
    msg = bot.send_message(c.message.chat.id, f"🎟 Создание промо для **{cat}**\nВведите: `КОД СУММА` (например: `WEB50 10`)", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda x: save_promo(x, cat))

def save_promo(m, cat):
    try:
        code, disc = m.text.split()
        db_query("INSERT OR REPLACE INTO promos (code, discount, cat) VALUES (?, ?, ?)", (code.upper(), float(disc), cat), commit=True)
        bot.send_message(m.chat.id, f"✅ Код `{code.upper()}` на ${disc} для **{cat}** создан!", parse_mode="Markdown")
    except:
        bot.send_message(m.chat.id, "❌ Ошибка! Нужно ввести: `КОД СУММА` (через пробел)")

# === ЛОГИКА ЗАКАЗА ===
@bot.message_handler(func=lambda m: "Заказать" in m.text)
def order_step1(m):
    cat = "Сайт" if "сайт" in m.text.lower() else "ТГ Бот"
    price = 50.0 if cat == "Сайт" else 15.0
    msg = bot.send_message(m.chat.id, f"📝 Опишите ТЗ для вашего проекта (**{cat}**):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda x: ask_promo(x, cat, price))

def ask_promo(m, cat, price):
    tz_text = m.text
    msg = bot.send_message(m.chat.id, f"🎟 У вас есть промокод для **{cat}**?\nЕсли нет, напишите `нет`", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda x: apply_promo(x, cat, price, tz_text))

def apply_promo(m, cat, price, tz):
    code = m.text.upper()
    final_price = price
    
    # Ищем промо в базе по коду И категории
    promo = db_query("SELECT discount, cat FROM promos WHERE code = ?", (code,), fetchone=True)
    
    if promo:
        p_discount, p_cat = promo
        if p_cat == cat: # Проверка: подходит ли промокод к этой услуге
            final_price = max(0.0, price - p_discount)
            bot.send_message(m.chat.id, f"🔥 Промокод применен! Скидка: ${p_discount}")
        else:
            bot.send_message(m.chat.id, f"⚠️ Этот промокод только для категории: **{p_cat}**", parse_mode="Markdown")
    elif code not in ["НЕТ", "-", "NO", "НЕТУ"]:
        bot.send_message(m.chat.id, "❌ Промокод не найден.")

    # Если цена стала 0
    if final_price <= 0:
        db_query("INSERT INTO orders (user_id, cat, desc, status, price) VALUES (?, ?, ?, ?, ?)", 
                 (m.from_user.id, cat, tz, "Оплачено (Промо)", 0), commit=True)
        bot.send_message(m.chat.id, "✅ Заказ оформлен БЕСПЛАТНО по промокоду!")
        bot.send_message(ADMIN_ID, f"🎁 Бесплатный заказ: {cat} от @{m.from_user.username}")
    else:
        # Создаем инвойс CryptoBot
        inv = create_invoice(final_price, f"Оплата {cat}")
        if not inv: return bot.send_message(m.chat.id, "Ошибка API.")
        
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 Оплатить", url=inv['pay_url']))
        kb.add(types.InlineKeyboardButton("✅ Проверить оплату", callback_data=f"chk_{inv['invoice_id']}_{cat}_{final_price}"))
        
        db_query("INSERT INTO orders (user_id, cat, desc, status, price) VALUES (?, ?, ?, ?, ?)", 
                 (m.from_user.id, cat, tz, "Ожидает оплаты", final_price), commit=True)
        bot.send_message(m.chat.id, f"Счет на **${final_price}** готов:", reply_markup=kb, parse_mode="Markdown")

# === ПРОВЕРКА ОПЛАТЫ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("chk_"))
def check_payment(c):
    _, inv_id, cat, price = c.data.split("_")
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    res = requests.get(f"https://pay.crypt.bot/api/getInvoices?invoice_ids={inv_id}", headers=headers).json()
    
    if res['result']['items'][0]['status'] == "paid":
        uid = c.from_user.id
        db_query("UPDATE orders SET status = 'Оплачено' WHERE user_id = ? AND status = 'Ожидает оплаты'", (uid,), commit=True)
        
        # Реф-бонус 5% пригласившему
        ref = db_query("SELECT ref_from FROM users WHERE user_id = ?", (uid,), fetchone=True)[0]
        if ref:
            bonus = float(price) * 0.05
            db_query("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, ref), commit=True)
            try: bot.send_message(ref, f"💰 Бонус! Ваш реферал купил {cat}, вам начислено ${bonus}")
            except: pass

        bot.edit_message_text("✅ Оплата прошла! Мы начали разработку.", c.message.chat.id, c.message.message_id)
        
        # Реферальный маркетинг после покупки
        bot_user = bot.get_me().username
        link = f"https://t.me/{bot_user}?start={uid}"
        bot.send_message(uid, f"🎁 Теперь ты наш клиент! Зарабатывай с нами: `{link}`", parse_mode="Markdown")
    else:
        bot.answer_callback_query(c.id, "❌ Оплата не найдена.", show_alert=True)

# Остальные функции (Баланс, Статус, Рассылка) остаются без изменений...
bot.infinity_polling()
