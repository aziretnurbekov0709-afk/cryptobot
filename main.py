import telebot
from telebot import types
import requests

# Установите библиотеку: pip install pyTelegramBotAPI==4.14.0
TOKEN = "8656129697:AAH4g6qI-7aRKH7yYEA_1j_CHUJKHhmb5PI"
CRYPTO_TOKEN = "558894:AATjq3d3xESUI4XFNSMlzL32oDDLigfkxok" # Получить в @CryptoBot (Testnet или Mainnet)
ADMIN_ID = 6498779131 # Главный админ

bot = telebot.TeleBot(TOKEN)

# Данные о товарах
PRICES = {
    "Сайт": 50,
    "ТГ Бот": 15
}

users = {}
orders = {}
history = {}
pending_payments = {} # Для отслеживания счетов {invoice_id: {'uid': user_id, 'cat': category}}

# ===== КРИПТО ОПЛАТА (API) =====
def create_invoice(amount, description):
    url = "https://pay.crypt.bot/api/createInvoice" # Для теста используйте testnet.pay.crypt.bot
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    data = {
        "asset": "USDT",
        "amount": str(amount),
        "description": description,
        "allow_comments": False
    }
    try:
        response = requests.post(url, headers=headers, json=data).json()
        return response['result']
    except Exception as e:
        print(f"Ошибка оплаты: {e}")
        return None

def check_invoice(invoice_id):
    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    try:
        response = requests.get(url, headers=headers).json()
        status = response['result']['items'][0]['status']
        return status == "active" or status == "paid" # Проверка статуса
    except:
        return False

# ===== СТАРТ =====
@bot.message_handler(commands=['start'])
def start(m):
    users[m.from_user.id] = m.from_user.username
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("🌐 Заказать сайт ($50)", "🤖 Заказать ТГ Бота ($15)")
    kb.add("📊 Статус", "🧾 История")
    
    if m.from_user.id == ADMIN_ID:
        kb.add("📋 Все заказы")

    bot.send_message(m.chat.id, "Добро пожаловать в DEV SHOP 💻", reply_markup=kb)

# ===== ЛОГИКА ЗАКАЗА =====
@bot.message_handler(func=lambda m: "Заказать" in m.text)
def handle_order(m):
    category = "Сайт" if "сайт" in m.text.lower() else "ТГ Бот"
    price = PRICES[category]
    
    msg = bot.send_message(m.chat.id, f"Вы выбрали: {category}.\nОпишите ТЗ (техническое задание) одним сообщением:")
    bot.register_next_step_handler(msg, lambda x: process_payment(x, category, price))

def process_payment(m, category, price):
    description = f"Оплата {category}"
    invoice = create_invoice(price, description)
    
    if not invoice:
        bot.send_message(m.chat.id, "❌ Ошибка платежной системы. Попробуйте позже.")
        return

    invoice_id = invoice['invoice_id']
    pay_url = invoice['pay_url']
    
    # Сохраняем временные данные о заказе
    pending_payments[invoice_id] = {
        "uid": m.from_user.id,
        "cat": category,
        "desc": m.text
    }

    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("💳 Оплатить USDT", url=pay_url))
    kb.add(types.InlineKeyboardButton("✅ Проверить оплату", callback_data=f"check_{invoice_id}"))

    bot.send_message(m.chat.id, f"Для оформления заказа необходимо оплатить **{price}$**", 
                     reply_markup=kb, parse_mode="Markdown")

# ===== ПРОВЕРКА ПЛАТЕЖА =====
@bot.callback_query_handler(func=lambda c: c.data.startswith("check_"))
def verify_payment(c):
    invoice_id = int(c.data.split("_")[1])
    
    # В реальном проекте здесь лучше использовать getInvoices и проверять статус "paid"
    # Для упрощения логики считаем, что кнопка нажимается после оплаты
    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={invoice_id}"
    headers = {"Crypto-Pay-API-Token": CRYPTO_TOKEN}
    res = requests.get(url, headers=headers).json()
    
    if res['result']['items'][0]['status'] == "paid":
        data = pending_payments.get(invoice_id)
        if data:
            uid = data['uid']
            cat = data['cat']
            desc = data['desc']

            # Фиксируем в базе
            orders[uid] = "⏳ В разработке"
            history.setdefault(uid, []).append(f"{cat}: {desc} (Оплачено)")

            # Уведомляем админа
            bot.send_message(ADMIN_ID, f"💰 НОВЫЙ ЗАКАЗ (ОПЛАЧЕНО)\nОт: @{c.from_user.username}\nТип: {cat}\nТЗ: {desc}")
            bot.send_message(uid, "✅ Оплата получена! Заказ передан разработчику.")
            
            del pending_payments[invoice_id]
    else:
        bot.answer_callback_query(c.id, "❌ Оплата еще не поступила", show_alert=True)

# ===== СТАТУС И ИСТОРИЯ =====
@bot.message_handler(func=lambda m: m.text == "📊 Статус")
def st(m):
    bot.send_message(m.chat.id, f"Текущий статус: {orders.get(m.from_user.id, 'Активных заказов нет')}")

@bot.message_handler(func=lambda m: m.text == "🧾 История")
def hs(m):
    h = history.get(m.from_user.id)
    bot.send_message(m.chat.id, "\n---\n".join(h) if h else "История пуста")

# ===== АДМИНКА =====
@bot.message_handler(func=lambda m: m.text == "📋 Все заказы")
def admin_orders(m):
    if m.from_user.id != ADMIN_ID: return
    if not orders:
        bot.send_message(m.chat.id, "Заказов пока нет")
        return
    
    res = "📋 СПИСОК ЗАКАЗОВ:\n\n"
    for uid, status in orders.items():
        res += f"👤 @{users.get(uid)} ({uid})\n📊 {status}\n\n"
    bot.send_message(ADMIN_ID, res)

bot.infinity_polling()
