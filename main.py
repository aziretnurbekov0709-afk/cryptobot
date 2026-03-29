import telebot
from telebot import types
import sqlite3
import requests

# === КОНФИГУРАЦИЯ ===
TOKEN = "8656129697:AAH4g6qI-7aRKH7yYEA_1j_CHUJKHhmb5PI"
CRYPTO_TOKEN = "558894:AATjq3d3xESUI4XFNSMlzL32oDDLigfkxok"
ADMIN_ID = 6498779131

bot = telebot.TeleBot(TOKEN)

# === РАБОТА С БД (SQLite) ===
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

# === МЕНЮ И СТАРТ ===
@bot.message_handler(commands=['start'])
def start(m):
    uid, uname = m.from_user.id, m.from_user.username
    args = m.text.split()
    ref_from = int(args[1]) if len(args) > 1 and args[1].isdigit() and int(args[1]) != uid else None

    db_query("INSERT OR IGNORE INTO users (user_id, username, ref_from) VALUES (?, ?, ?)", 
             (uid, uname, ref_from), commit=True)

    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🌐 Заказать сайт ($50)", "🤖 Заказать ТГ Бота ($15)")
    kb.add("💰 Баланс", "📊 Статус")
    if uid == ADMIN_ID: kb.add("📊 Админ-панель", "📢 Рассылка")
    
    bot.send_message(m.chat.id, "👑 **DEV STUDIO**\nВыберите нужную услугу ниже:", reply_markup=kb, parse_mode="Markdown")

# === ЛОГИКА ЗАКАЗА И БОНУСОВ ===
@bot.message_handler(func=lambda m: "Заказать" in m.text)
def order_init(m):
    cat = "Сайт" if "сайт" in m.text.lower() else "ТГ Бот"
    base_price = 50.0 if cat == "Сайт" else 15.0
    
    user_data = db_query("SELECT balance FROM users WHERE user_id = ?", (m.from_user.id,), fetchone=True)
    balance = user_data[0] if user_data else 0
    
    if balance > 0:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"✅ Списать ${balance}", callback_data=f"pay_yes_{cat}_{base_price}"))
        kb.add(types.InlineKeyboardButton(f"❌ Нет, полная цена", callback_data=f"pay_no_{cat}_{base_price}"))
        bot.send_message(m.chat.id, f"💳 У вас есть ${balance} бонусов. Использовать их?", reply_markup=kb)
    else:
        start_payment(m.chat.id, cat, base_price, 0)

@bot.callback_query_handler(func=lambda c: c.data.startswith("pay_"))
def handle_pay_choice(c):
    _, choice, cat, price = c.data.split("_")
    price = float(price)
    discount = 0
    if choice == "yes":
        user_data = db_query("SELECT balance FROM users WHERE user_id = ?", (c.from_user.id,), fetchone=True)
        discount = user_data[0]
        price = max(1.0, price - discount) # Минимум 1$ к оплате
    
    bot.delete_message(c.message.chat.id, c.message.message_id)
    start_payment(c.message.chat.id, cat, price, discount if choice == "yes" else 0)

def start_payment(chat_id, cat, price, discount_used):
    msg = bot.send_message(chat_id, f"📝 Опишите ваше ТЗ для: **{cat}**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda x: final_invoice(x, cat, price, discount_used))

def final_invoice(m, cat, price, discount):
    inv = create_invoice(price, f"Оплата {cat}")
    if not inv: return bot.send_message(m.chat.id, "❌ Ошибка платежной системы.")

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🔗 Оплатить в CryptoBot", url=inv['pay_url']))
    kb.add(types.InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_{inv['invoice_id']}_{cat}_{price}_{discount}"))
    
    db_query("INSERT INTO orders (user_id, cat, desc, status, price) VALUES (?, ?, ?, ?, ?)", 
             (m.from_user.id, cat, m.text, "Ожидает оплаты", price), commit=True)
    bot.send_message(m.chat.id, f"💰 Сумма к оплате: **${price}**\nПосле перевода нажмите кнопку ниже:", reply_markup=kb, parse_mode="Markdown")

# === ПРОВЕРКА И МАРКЕТИНГ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("check_"))
def verify_payment(c):
    _, inv_id, cat, price, discount = c.data.split("_")
    res = requests.get(f"https://pay.crypt.bot/api/getInvoices?invoice_ids={inv_id}", 
                       headers={"Crypto-Pay-API-Token": CRYPTO_TOKEN}).json()
    
    if res['result']['items'][0]['status'] == "paid":
        uid = c.from_user.id
        # Если была скидка — вычитаем бонусы
        if float(discount) > 0:
            db_query("UPDATE users SET balance = 0 WHERE user_id = ?", (uid,), commit=True)
        
        db_query("UPDATE orders SET status = 'Оплачено' WHERE user_id = ? AND status = 'Ожидает оплаты'", (uid,), commit=True)
        
        # Рефералка пригласившему
        ref_data = db_query("SELECT ref_from FROM users WHERE user_id = ?", (uid,), fetchone=True)
        if ref_data and ref_data[0]:
            bonus = float(price) * 0.05
            db_query("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, ref_data[0]), commit=True)
            try: bot.send_message(ref_data[0], f"🔥 +${bonus} на ваш баланс! Ваш реферал купил {cat}.")
            except: pass

        bot.edit_message_text("✅ Оплата получена! Мы начали работу.", c.message.chat.id, c.message.message_id)
        
        # МАРКЕТИНГ: Даем реф-ссылку сразу после покупки
        bot_name = bot.get_me().username
        ref_link = f"https://t.me/{bot_name}?start={uid}"
        bot.send_message(uid, f"🎁 Хотите этот заказ бесплатно? \nПриглашайте друзей по ссылке и получайте 5% от их оплат на свой баланс!\n\nВаша ссылка: `{ref_link}`", parse_mode="Markdown")
        bot.send_message(ADMIN_ID, f"🆕 ЗАКАЗ ОПЛАЧЕН: {cat} (${price}) от @{c.from_user.username}")
    else:
        bot.answer_callback_query(c.id, "❌ Оплата не найдена.", show_alert=True)

# === АДМИНКА И АНАЛИТИКА ===
@bot.message_handler(func=lambda m: m.text == "📊 Админ-панель" and m.from_user.id == ADMIN_ID)
def admin_stats(m):
    users_cnt = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    total_cash = db_query("SELECT SUM(price) FROM orders WHERE status='Оплачено'", fetchone=True)[0] or 0
    
    bot.send_message(m.chat.id, f"📈 **СТАТИСТИКА:**\n\n👤 Всего юзеров: {users_cnt}\n💰 Оплачено на сумму: ${total_cash}", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📢 Рассылка" and m.from_user.id == ADMIN_ID)
def start_broadcast(m):
    msg = bot.send_message(m.chat.id, "Введите текст рекламного сообщения:")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(m):
    users = db_query("SELECT user_id FROM users")
    count = 0
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🚀 Заказать проект", callback_data="start_order"))
    
    for u in users:
        try:
            bot.send_message(u[0], m.text, reply_markup=kb, parse_mode="Markdown")
            count += 1
        except: pass
    bot.send_message(ADMIN_ID, f"✅ Рассылка завершена. Доставлено: {count} чел.")

# === ДОП КНОПКИ ===
@bot.message_handler(func=lambda m: m.text == "💰 Баланс")
def show_bal(m):
    bal = db_query("SELECT balance FROM users WHERE user_id = ?", (m.from_user.id,), fetchone=True)[0]
    bot.send_message(m.chat.id, f"💵 Ваш бонусный баланс: **${bal}**\n\nВы можете списать эти деньги при следующем заказе.", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📊 Статус")
def show_status(m):
    res = db_query("SELECT cat, status FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 1", (m.from_user.id,), fetchone=True)
    if res:
        bot.send_message(m.chat.id, f"🔎 Последний заказ: **{res[0]}**\nСтатус: `{res[1]}`", parse_mode="Markdown")
    else:
        bot.send_message(m.chat.id, "У вас пока нет заказов.")

bot.infinity_polling()
