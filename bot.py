import logging
import json
import os
import signal
import sys
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
    JobQueue,
)

# Настройка логирования
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Файлы
DATA_FILE = "data.json"
LOG_FILE = "admin_log.txt"
BACKUP_DIR = "backups"

# Создаём папку для бэкапов
os.makedirs(BACKUP_DIR, exist_ok=True)

# 🔴 УКАЖИ СВОЙ ID ЗДЕСЬ
ADMIN_IDS = [5043175452]  # ← Замени на свой Telegram ID!

# Логирование действий админа
def log_admin_action(admin_id, action):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] Админ {admin_id}: {action}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_entry)

# Загрузка данных
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()
            if not content:
                return {}
            return json.loads(content)
    except Exception as e:
        print(f"❌ Ошибка чтения data.json: {e}")
        if os.path.exists(DATA_FILE):
            os.rename(DATA_FILE, DATA_FILE + ".bak")
        return {}

# Сохранение данных
def save_data(data):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)

# Бэкап
def create_backup():
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.join(BACKUP_DIR, f"backup_{timestamp}.json")
    try:
        data = load_data()
        with open(backup_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        log_admin_action("SYSTEM", f"бэкап создан: {backup_path}")
    except Exception as e:
        logger.error(f"❌ Ошибка бэкапа: {e}")

# Автоматический бэкап
async def backup_job(context: ContextTypes.DEFAULT_TYPE):
    create_backup()

# Загрузка данных
data = load_data()

# Переменные
user_balances = data.get("balances", {})
user_upgrades = data.get("upgrades", {})
user_passive_last = data.get("passive_last", {})
used_promocodes = data.get("used_promocodes", {})  # {user_id: {promo_name: True}}
active_promocodes = data.get("active_promocodes", {
    "DEDACHA": {"reward": 50.0, "limit": 5, "used": 0}
})
daily_rewards = data.get("daily_rewards", {})
referrals = data.get("referrals", {})
referral_count = data.get("referral_count", {})
user_states = {}  # {user_id: состояние}

# Магазин
SHOP_ITEMS = {
    "shovel": {"name": "Лопата", "price": 100.0, "type": "click", "value": 0.010},
    "fishing_rod": {"name": "Удочка", "price": 200.0, "type": "passive", "value": 1.0},
    "greenhouse": {"name": "Теплица", "price": 500.0, "type": "click", "value": 0.050},
}

def save_all():
    data["balances"] = user_balances
    data["upgrades"] = user_upgrades
    data["passive_last"] = user_passive_last
    data["used_promocodes"] = used_promocodes
    data["active_promocodes"] = active_promocodes
    data["daily_rewards"] = daily_rewards
    data["referrals"] = referrals
    data["referral_count"] = referral_count
    save_data(data)

def get_click_multiplier(user_id):
    total = 0.050
    upgrades = user_upgrades.get(user_id, {})
    for item_id, count in upgrades.items():
        if SHOP_ITEMS[item_id]["type"] == "click":
            total += SHOP_ITEMS[item_id]["value"] * count
    return total

def calculate_passive_income(user_id):
    now = datetime.now()
    last_time = user_passive_last.get(user_id)
    if not last_time:
        user_passive_last[user_id] = now.isoformat()
        save_all()
        return 0.0
    try:
        last = datetime.fromisoformat(last_time)
    except:
        last = now
    minutes = (now - last).total_seconds() // 60
    income = 0.0
    rods = user_upgrades.get(user_id, {}).get("fishing_rod", 0)
    income = rods * 1.0 * minutes
    user_passive_last[user_id] = now.isoformat()
    return income

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in user_balances:
        user_balances[user_id] = 0.0
        user_upgrades[user_id] = {}
        user_passive_last[user_id] = datetime.now().isoformat()
        used_promocodes[user_id] = {}
        daily_rewards[user_id] = None
        save_all()

    passive = calculate_passive_income(user_id)
    if passive > 0:
        user_balances[user_id] += passive
        await update.message.reply_text(f"💰 Получено от пассива: {passive:.0f} Дача-коинов")

    keyboard = [
        [InlineKeyboardButton("⛏ Клик!", callback_data="click")],
        [InlineKeyboardButton("📊 Профиль", callback_data="profile")],
        [InlineKeyboardButton("🎁 Промокод", callback_data="promo")],
        [InlineKeyboardButton("🛒 Магазин", callback_data="shop")],
        [InlineKeyboardButton("📅 Ежедневная награда", callback_data="daily")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Добро пожаловать на дачу! 🌿", reply_markup=reply_markup)
    save_all()

# Обработка кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    await query.answer()  # Подтверждаем нажатие

    if user_id not in user_balances:
        await query.edit_message_text("❌ Ошибка: начните с /start")
        return

    data = query.data

    if data == "click":
        amount = get_click_multiplier(user_id)
        user_balances[user_id] += amount
        await query.edit_message_text(
            f"Вы получили {amount:.3f} Дача-коинов!\n"
            f"Баланс: {user_balances[user_id]:.3f}",
            reply_markup=query.message.reply_markup
        )
        save_all()

    elif data == "profile":
        balance = user_balances[user_id]
        await query.edit_message_text(
            f"👤 Профиль:\n"
            f"Баланс: {balance:.3f} Дача-коинов",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ Назад", callback_data="back")
            ]])
        )

    elif data == "promo":
        user_states[user_id] = "awaiting_promo"
        await query.message.reply_text("Введите промокод:")
        await query.delete_message()

    elif data == "shop":
        keyboard = [
            [InlineKeyboardButton(
                f"{item['name']} — {item['price']} 🪙",
                callback_data=f"buy_{k}"
            )] for k, item in SHOP_ITEMS.items()
        ]
        keyboard.append([InlineKeyboardButton("⬅️ Назад", callback_data="back")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("🛒 Магазин:", reply_markup=reply_markup)

    elif data.startswith("buy_"):
        item_id = data.replace("buy_", "")
        item = SHOP_ITEMS.get(item_id)
        if not item:
            await query.answer("❌ Товар не найден", show_alert=True)
            return
        if user_balances[user_id] < item["price"]:
            await query.answer("❌ Нехватает средств!", show_alert=True)
            return
        user_balances[user_id] -= item["price"]
        user_upgrades.setdefault(user_id, {})
        user_upgrades[user_id][item_id] = user_upgrades[user_id].get(item_id, 0) + 1
        await query.answer(f"✅ Куплено: {item['name']}")
        await button_handler(update, context)
        save_all()

    elif data == "daily":
        today = datetime.now().strftime("%Y-%m-%d")
        if daily_rewards.get(user_id) == today:
            await query.answer("Вы уже получили награду!", show_alert=True)
        else:
            user_balances[user_id] += 10.0
            daily_rewards[user_id] = today
            await query.answer("🎉 Получено 10 Дача-коинов!", show_alert=True)
            await query.edit_message_reply_markup(reply_markup=query.message.reply_markup)
            save_all()

    elif data == "back":
        keyboard = [
            [InlineKeyboardButton("⛏ Клик!", callback_data="click")],
            [InlineKeyboardButton("📊 Профиль", callback_data="profile")],
            [InlineKeyboardButton("🎁 Промокод", callback_data="promo")],
            [InlineKeyboardButton("🛒 Магазин", callback_data="shop")],
            [InlineKeyboardButton("📅 Ежедневная награда", callback_data="daily")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Меню дачи 🌿", reply_markup=reply_markup)

# Команда /admin
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("❌ Доступ запрещён.")
        return

    keyboard = [
        [InlineKeyboardButton("💵 Выдать коины", callback_data="admin_give")],
        [InlineKeyboardButton("📨 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton("🎁 Создать промо", callback_data="admin_create_promo")],
        [InlineKeyboardButton("🗑 Удалить промо", callback_data="admin_delete_promo")],
        [InlineKeyboardButton("📋 Игроки", callback_data="admin_list")],
        [InlineKeyboardButton("📄 Логи", callback_data="admin_logs")],
        [InlineKeyboardButton("🔄 Ручной бэкап", callback_data="admin_backup")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🔐 Админ-панель", reply_markup=reply_markup)

# Обработка админ-кнопок
async def admin_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id

    if user_id not in ADMIN_IDS:
        await query.answer("❌ Доступ запрещён.", show_alert=True)
        return

    await query.answer()

    data = query.data

    if data == "admin_give":
        user_states[user_id] = "admin_give"
        await query.message.reply_text("Введите: ID сумма\nПример: 123456789 100")

    elif data == "admin_broadcast":
        user_states[user_id] = "admin_broadcast"
        await query.message.reply_text("Введите текст рассылки:")

    elif data == "admin_create_promo":
        user_states[user_id] = "admin_create_promo"
        await query.message.reply_text("Введите: ИМЯ СУММА ЛИМИТ\nПример: НОВЫЙГОД 100 5")

    elif data == "admin_delete_promo":
        user_states[user_id] = "admin_delete_promo"
        promos = "\n".join(
            f"• {name} — {info['reward']} (использовано: {info['used']}/{info['limit']})"
            for name, info in active_promocodes.items()
        )
        await query.message.reply_text(f"Доступные промокоды:\n{promos or 'Нет'}\n\nВведите имя промокода для удаления:")

    elif data == "admin_list":
        players = "\n".join([f"ID {uid}: {bal:.1f}" for uid, bal in user_balances.items()])
        await query.message.reply_text(f"📋 Игроки:\n{players or 'Нет игроков'}")

    elif data == "admin_logs":
        logs = open(LOG_FILE, "r", encoding="utf-8").read()[-2000:] if os.path.exists(LOG_FILE) else "Логи пусты."
        await query.message.reply_text(f"📄 Логи:\n\n{logs}")

    elif data == "admin_backup":
        create_backup()
        await query.message.reply_text("✅ Бэкап создан вручную!")

    else:
        await query.message.reply_text("❌ Неизвестная команда.")

# Обработка сообщений
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Админ: выдать коины
    if user_id in ADMIN_IDS and user_id in user_states:
        state = user_states[user_id]

        if state == "admin_give":
            try:
                target_id, amount = map(float, text.split())
                target_id = int(target_id)
                if target_id not in user_balances:
                    user_balances[target_id] = 0.0
                    user_upgrades[target_id] = {}
                    user_passive_last[target_id] = datetime.now().isoformat()
                    used_promocodes[target_id] = {}
                user_balances[target_id] += amount
                await update.message.reply_text(f"✅ Выдано {amount} Дача-коинов пользователю {target_id}")
                log_admin_action(user_id, f"выдал {amount} → {target_id}")
                save_all()
            except:
                await update.message.reply_text("❌ Ошибка. Формат: ID сумма")
            finally:
                del user_states[user_id]

        elif state == "admin_broadcast":
            sent = 0
            for uid in user_balances:
                try:
                    await context.bot.send_message(chat_id=uid, text=f"📢 Рассылка:\n{text}")
                    sent += 1
                except:
                    pass
            await update.message.reply_text(f"📬 Рассылка: {sent} доставлено")
            log_admin_action(user_id, f"рассылка: {text}")
            del user_states[user_id]

        elif state == "admin_create_promo":
            try:
                name, amount, limit = text.split()
                amount, limit = float(amount), int(limit)
                if name in active_promocodes:
                    await update.message.reply_text("⚠️ Промокод с таким именем уже есть.")
                else:
                    active_promocodes[name] = {"reward": amount, "limit": limit, "used": 0}
                    await update.message.reply_text(f"✅ Промокод '{name}' создан: {amount} (лимит: {limit})")
                    log_admin_action(user_id, f"создал промокод '{name}' на {amount}, лимит {limit}")
                    save_all()
            except:
                await update.message.reply_text("❌ Формат: ИМЯ СУММА ЛИМИТ\nПример: СУПЕР 50 3")
            finally:
                del user_states[user_id]

        elif state == "admin_delete_promo":
            if text in active_promocodes:
                del active_promocodes[text]
                await update.message.reply_text(f"🗑 Промокод '{text}' удалён.")
                log_admin_action(user_id, f"удалил промокод '{text}'")
                save_all()
            else:
                await update.message.reply_text("❌ Промокод не найден.")
            del user_states[user_id]
            return

    # Обычные пользователи: промокоды
    elif user_id in user_states and user_states[user_id] == "awaiting_promo":
        if text in active_promocodes:
            promo = active_promocodes[text]
            if promo["used"] >= promo["limit"]:
                await update.message.reply_text("❌ Лимит активаций исчерпан.")
            elif text in used_promocodes.get(user_id, {}):
                await update.message.reply_text("⚠️ Вы уже использовали этот промокод.")
            else:
                amount = promo["reward"]
                user_balances[user_id] += amount
                used_promocodes.setdefault(user_id, {})[text] = True
                active_promocodes[text]["used"] += 1
                await update.message.reply_text(f"🎉 Промокод '{text}' активирован! Получено: {amount} Дача-коинов.")
                log_admin_action("SYSTEM", f"активировал '{text}'")
                save_all()
        else:
            await update.message.reply_text("❌ Неверный промокод.")
        del user_states[user_id]
    else:
        await update.message.reply_text("Используйте кнопки.")

# === ОСТАНОВКА БОТА ПО Ctrl+C ===
def signal_handler(signum, frame):
    print("\n\n🛑 Бот остановлен пользователем.")
    print("✅ Все данные сохранены.")
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)  # Ловим Ctrl+C

# Основная функция
def main():
    TOKEN = "7587434641:AAE6J4xmeB3uxvvFSHi81TJn9BYiLCVX23I"  # ⚠️ Замени на токен от @BotFather

    job_queue = JobQueue()

    application = Application.builder().token(TOKEN).job_queue(job_queue).build()

    # Планирование бэкапов
    application.job_queue.run_once(backup_job, 1)
    application.job_queue.run_repeating(backup_job, interval=24*3600, first=24*3600)

    # Хендлеры
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("admin", admin_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(CallbackQueryHandler(admin_button_handler, pattern="^admin_"))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    print("✅ Бот запущен. Нажмите Ctrl+C для остановки.")
    try:
        application.run_polling()
    except KeyboardInterrupt:
        print("\n🛑 Бот остановлен через KeyboardInterrupt.")
    except Exception as e:
        logger.error(f"Ошибка: {e}")

if __name__ == '__main__':
    main()