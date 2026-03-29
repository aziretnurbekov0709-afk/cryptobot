import telebot
from telebot import types
import sqlite3
import requests

# === КОНФИГУРАЦИЯ (Замени на свои данные) ===
TOKEN = "8656129697:AAH4g6qI-7aRKH7yYEA_1j_CHUJKHhmb5PI"
CRYPTO_TOKEN = "558894:AATjq3d3xESUI4XFNSMlzL32oDDLigfkxok"
ADMIN_ID = 6498779131

bot = telebot.TeleBot(TOKEN)

# === РАБОТА С БАЗОЙ ДАННЫХ ===
def db_query(sql, params=(), fetchone=False, commit=False):
    conn = sqlite3.connect('bot.db', check_same_thread=False)
    cursor = conn.cursor()
    cursor.execute(sql, params)
    res = cursor.fetchone() if fetchone else cursor.fetchall()
    if commit: conn.commit()
    conn.close()
    return res

def init_db():
    # Таблица пользователей
    db_query('''CREATE TABLE IF NOT EXISTS users 
                 (user_id INTEGER PRIMARY KEY, username TEXT, balance REAL DEFAULT 0, ref_from INTEGER)''', commit=True)
    # Таблица заказов
    db_query('''CREATE TABLE IF NOT EXISTS orders 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, cat TEXT, desc TEXT, status TEXT, price REAL)''', commit=True)
    # Таблица промокодов
    db_query('''CREATE TABLE IF NOT EXISTS promos (code TEXT PRIMARY KEY, discount REAL, cat TEXT)''', commit=True)

init_db()

# === КРИПТО API ===
def create_invoice(amount, desc):
    url = "https://pay.crypt.bot/api/createInvoice"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {"asset": "USDT", "amount": str(round(amount, 2)), "description": desc}
    try:
        r = requests.post(url, headers=headers, json=data).json()
        return r['result']
    except: return None

# === ГЛАВНОЕ МЕНЮ ===
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
    if uid == ADMIN_ID: kb.add("🛠 Админ-панель")
    
    bot.send_message(m.chat.id, "💎 **DEV STUDIO v2.0**\nВыберите услугу для заказа:", reply_markup=kb, parse_mode="Markdown")

# === ЛОГИКА ЗАКАЗА (Бонусы -> ТЗ -> Промо) ===
@bot.message_handler(func=lambda m: "Заказать" in m.text)
def order_start(m):
    cat = "Сайт" if "сайт" in m.text.lower() else "ТГ Бот"
    base_price = 50.0 if cat == "Сайт" else 15.0
    
    user_data = db_query("SELECT balance FROM users WHERE user_id = ?", (m.from_user.id,), fetchone=True)
    balance = user_data[0] if user_data else 0
    
    if balance > 0:
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton(f"✅ Списать ${balance}", callback_data=f"bonus_yes_{cat}_{base_price}"))
        kb.add(types.InlineKeyboardButton(f"❌ Нет, полная цена", callback_data=f"bonus_no_{cat}_{base_price}"))
        bot.send_message(m.chat.id, f"💳 У вас есть **${balance}** на балансе. Использовать их?", reply_markup=kb, parse_mode="Markdown")
    else:
        ask_tz(m.chat.id, cat, base_price, 0)

@bot.callback_query_handler(func=lambda c: c.data.startswith("bonus_"))
def handle_bonus(c):
    _, choice, cat, price = c.data.split("_")
    price = float(price)
    discount = 0
    if choice == "yes":
        discount = db_query("SELECT balance FROM users WHERE user_id = ?", (c.from_user.id,), fetchone=True)[0]
    bot.delete_message(c.message.chat.id, c.message.message_id)
    ask_tz(c.message.chat.id, cat, price, discount)

def ask_tz(chat_id, cat, price, used_bonus):
    msg = bot.send_message(chat_id, f"📝 Опишите ваше ТЗ для: **{cat}**", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda x: ask_promo(x, cat, price, used_bonus))

def ask_promo(m, cat, price, used_bonus):
    tz_text = m.text
    msg = bot.send_message(m.chat.id, f"🎟 Введите промокод для **{cat}** (если нет, напишите `нет`):", parse_mode="Markdown")
    bot.register_next_step_handler(msg, lambda x: final_price_calc(x, cat, price, used_bonus, tz_text))

def final_price_calc(m, cat, price, used_bonus, tz):
    code = m.text.upper()
    current_price = price - used_bonus
    
    promo = db_query("SELECT discount, cat FROM promos WHERE code = ?", (code,), fetchone=True)
    if promo:
        p_disc, p_cat = promo
        if p_cat == cat:
            current_price -= p_disc
            bot.send_message(m.chat.id, f"🔥 Промокод `{code}` применен! Скидка: ${p_disc}")
        else:
            bot.send_message(m.chat.id, f"⚠️ Код `{code}` только для категории **{p_cat}**.")
    
    final_price = max(0.0, current_price)

    # Оформление
    if final_price <= 0:
        db_query("INSERT INTO orders (user_id, cat, desc, status, price) VALUES (?, ?, ?, ?, ?)", 
                 (m.from_user.id, cat, tz, "Оплачено (Промо)", 0), commit=True)
        db_query("UPDATE users SET balance = 0 WHERE user_id = ?", (m.from_user.id,), commit=True) # Обнуляем бонусы если юзались
        bot.send_message(m.chat.id, "✅ Заказ оформлен БЕСПЛАТНО! Мы начали работу.")
        bot.send_message(ADMIN_ID, f"🎁 Бесплатный заказ: {cat} от @{m.from_user.username}")
    else:
        inv = create_invoice(final_price, f"Оплата {cat}")
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("💳 Оплатить", url=inv['pay_url']))
        kb.add(types.InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_{inv['invoice_id']}_{cat}_{final_price}_{used_bonus}"))
        db_query("INSERT INTO orders (user_id, cat, desc, status, price) VALUES (?, ?, ?, ?, ?)", 
                 (m.from_user.id, cat, tz, "Ожидает оплаты", final_price), commit=True)
        bot.send_message(m.chat.id, f"💰 К оплате: **${final_price}**", reply_markup=kb, parse_mode="Markdown")

# === ПРОВЕРКА ОПЛАТЫ ===
@bot.callback_query_handler(func=lambda c: c.data.startswith("check_"))
def verify_payment(c):
    _, inv_id, cat, price, bonus_used = c.data.split("_")
    res = requests.get(f"https://pay.crypt.bot/api/getInvoices?invoice_ids={inv_id}", 
                       headers={"Crypto-Pay-API-Token": CRYPTO_TOKEN}).json()
    
    if res['result']['items'][0]['status'] == "paid":
        uid = c.from_user.id
        if float(bonus_used) > 0: db_query("UPDATE users SET balance = 0 WHERE user_id = ?", (uid,), commit=True)
        db_query("UPDATE orders SET status = 'Оплачено' WHERE user_id = ? AND status = 'Ожидает оплаты'", (uid,), commit=True)
        
        # Реф-бонус 5%
        ref = db_query("SELECT ref_from FROM users WHERE user_id = ?", (uid,), fetchone=True)[0]
        if ref:
            reward = float(price) * 0.05
            db_query("UPDATE users SET balance = balance + ? WHERE user_id = ?", (reward, ref), commit=True)
            try: bot.send_message(ref, f"💰 +${reward} бонусов! Ваш реферал купил {cat}.")
            except: pass

        bot.edit_message_text("✅ Оплата прошла! Заказ принят.", c.message.chat.id, c.message.message_id)
        
        # Маркетинг: выдача реф-ссылки
        bot_user = bot.get_me().username
        link = f"https://t.me/{bot_user}?start={uid}"
        bot.send_message(uid, f"🎁 Хотите скидку на следующий заказ?\nПриглашайте друзей: `{link}`\nПолучайте 5% от всех их трат!", parse_mode="Markdown")
        bot.send_message(ADMIN_ID, f"🆕 ОПЛАТА: {cat} (${price}) от @{c.from_user.username}")
    else:
        bot.answer_callback_query(c.id, "❌ Оплата не найдена.", show_alert=True)

# === АДМИН-ПАНЕЛЬ С АНАЛИТИКОЙ ===
@bot.message_handler(func=lambda m: m.text == "🛠 Админ-панель" and m.from_user.id == ADMIN_ID)
def admin_panel(m):
    t_users = db_query("SELECT COUNT(*) FROM users", fetchone=True)[0]
    buyers = db_query("SELECT COUNT(DISTINCT user_id) FROM orders WHERE status LIKE 'Оплачено%'", fetchone=True)[0]
    money = db_query("SELECT SUM(price) FROM orders WHERE status LIKE 'Оплачено%'", fetchone=True)[0] or 0
    
    kb = types.InlineKeyboardMarkup(row_width=1)
    kb.add(types.InlineKeyboardButton("📢 Рассылка всем", callback_data="adm_broadcast"),
           types.InlineKeyboardButton("🎟 Промо для САЙТА", callback_data="promo_S"),
           types.InlineKeyboardButton("🎟 Промо для БОТА", callback_data="promo_B"))
    
    stats = f"📊 **АНАЛИТИКА**\n\n👥 Юзеров всего: {t_users}\n🛒 Купили: {buyers}\n⏳ Не купили: {t_users-buyers}\n💰 Выручка: **${money}**"
    bot.send_message(m.chat.id, stats, reply_markup=kb, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda c: c.data.startswith("promo_"))
def adm_promo_init(c):
    cat = "Сайт" if "S" in c.data else "ТГ Бот"
    msg = bot.send_message(c.message.chat.id, f"Введите: `КОД СУММА` для **{cat}** (напр: `SALE10 10`)")
    bot.register_next_step_handler(msg, lambda x: save_promo(x, cat))

def save_promo(m, cat):
    try:
        code, disc = m.text.split()
        db_query("INSERT OR REPLACE INTO promos (code, discount, cat) VALUES (?, ?, ?)", (code.upper(), float(disc), cat), commit=True)
        bot.send_message(m.chat.id, f"✅ Код `{code.upper()}` на ${disc} для {cat} создан!")
    except: bot.send_message(m.chat.id, "❌ Ошибка. Пример: `HAPPY5 5`")

@bot.callback_query_handler(func=lambda c: c.data == "adm_broadcast")
def adm_broadcast_init(c):
    msg = bot.send_message(c.message.chat.id, "Введите текст рассылки:")
    bot.register_next_step_handler(msg, send_broadcast)

def send_broadcast(m):
    users = db_query("SELECT user_id FROM users")
    count = 0
    for u in users:
        try:
            bot.send_message(u[0], f"📢 **СООБЩЕНИЕ ОТ DEV STUDIO**\n\n{m.text}", parse_mode="Markdown")
            count += 1
        except: pass
    bot.send_message(ADMIN_ID, f"✅ Рассылка завершена. Получили: {count} чел.")

# === ОСТАЛЬНЫЕ КНОПКИ ===
@bot.message_handler(func=lambda m: m.text == "💰 Баланс")
def show_bal(m):
    b = db_query("SELECT balance FROM users WHERE user_id = ?", (m.from_user.id,), fetchone=True)[0]
    bot.send_message(m.chat.id, f"💵 Ваш бонусный счет: **${b}**", parse_mode="Markdown")

@bot.message_handler(func=lambda m: m.text == "📊 Статус")
def show_status(m):
    res = db_query("SELECT cat, status FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 1", (m.from_user.id,), fetchone=True)
    bot.send_message(m.chat.id, f"Последний заказ: **{res[0]}** — `{res[1]}`" if res else "Заказов нет.")

bot.infinity_polling()
