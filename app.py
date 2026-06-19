import asyncio
from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
import json
import traceback
import datetime
import urllib.request

app = Flask(__name__)
app.secret_key = 'vest_traffer_super_secret_key_1337'

# Конфигурация базы данных PostgreSQL и Telegram API
DATABASE_URL = "postgresql://bothost_db_6f5993e63d14:MKsFRAV0DVmbRSkNa1b_XNQVdJxnJJD2INqII8il4jk@node1.pghost.ru:15794/bothost_db_6f5993e63d14"
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 280
}

db = SQLAlchemy(app)

API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"
CRYPTO_BOT_TOKEN = "499354:AATdkiDyuC1tWd1ro5S5wFw6XcePNUNH5Ph"

# --- Модели Базы Данных ---
class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    subscription_ends = db.Column(db.DateTime, nullable=False)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    session_string = db.Column(db.Text, nullable=False)

class MailingTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    chats = db.Column(db.Text, nullable=False)  
    message = db.Column(db.Text, nullable=False)
    delay = db.Column(db.Integer, nullable=False)
    sent_count = db.Column(db.Integer, default=0)
    total_messages = db.Column(db.Integer, nullable=False)
    mailing_type = db.Column(db.String(50), nullable=False)  
    status = db.Column(db.String(50), default='Ожидает')  

class Autoresponder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    trigger_type = db.Column(db.String(30), nullable=False) 
    keywords = db.Column(db.Text, nullable=False) 
    reply_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

# Инициализация и безопасный многоуровневый патч старых колонок БД
with app.app_context():
    db.create_all()
    # Защита от UndefinedColumn: поочередно добавляем поля, если таблицы уже существовали
    for Сommand in [
        "ALTER TABLE mailing_task ADD COLUMN IF NOT EXISTS sent_count INTEGER DEFAULT 0;",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_ends TIMESTAMP;",
        "ALTER TABLE user ADD COLUMN IF NOT EXISTS subscription_ends TIMESTAMP;"
    ]:
        try:
            db.session.execute(db.text(Сommand))
            db.session.commit()
        except Exception:
            db.session.rollback()

# --- Безопасный менеджер асинхронных циклов для Vercel Serverless ---
def run_async(coro):
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

# --- Асинхронные методы работы с Telethon ---
async def _send_code(phone):
    client = TelegramClient(StringSession(), API_ID, API_HASH)
    await client.connect()
    try:
        res = await client.send_code_request(phone)
        return res.phone_code_hash, client.session.save()
    finally:
        await client.disconnect()

async def _sign_in_code(phone, code, phone_code_hash, temp_session):
    client = TelegramClient(StringSession(temp_session), API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
        return "SUCCESS", client.session.save()
    except SessionPasswordNeededError:
        return "2FA_NEEDED", client.session.save()
    finally:
        await client.disconnect()

async def _sign_in_2fa(password, temp_session):
    client = TelegramClient(StringSession(temp_session), API_ID, API_HASH)
    await client.connect()
    try:
        await client.sign_in(password=password)
        return client.session.save()
    finally:
        await client.disconnect()

async def _get_chats(session_string):
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise Exception("Сессия этого аккаунта невалидна.")
        dialogs = await client.get_dialogs(limit=100)
        parsed_chats = []
        for d in dialogs:
            title = d.name if d.name else f"ID {d.id}"
            if d.is_user:
                title = f"👤 ЛС: {title}"
            elif d.is_group:
                title = f"👥 Группа: {title}"
            elif d.is_channel:
                title = f"📢 Канал: {title}"
            parsed_chats.append({'id': d.id, 'title': title})
        return parsed_chats
    finally:
        await client.disconnect()

def create_crypto_pay_invoice(amount_rub):
    url = "https://pay.cryptobot.site/api/createInvoice"
    data = {
        "amount": str(amount_rub),
        "fiat": "RUB",
        "currency_type": "fiat",
        "accepted_assets": "USDT,TON,BTC"
    }
    req = urllib.request.Request(url, data=json.dumps(data).encode('utf-8'), method="POST")
    req.add_header("Crypto-Pay-API-Token", CRYPTO_BOT_TOKEN)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as response:
            res = json.loads(response.read().decode('utf-8'))
            if res.get("ok"):
                return res["result"]["pay_url"]
    except Exception as e:
        print(f"Ошибка инвойса CryptoBot: {e}")
    return None

# --- Панель интерфейса (Неоново-Синий Адаптив) ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Traffer</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <style>
        body { background-color: #02040a; color: #f3f4f6; font-family: 'Inter', sans-serif; padding-bottom: 95px; }
        .blue-glow { box-shadow: 0 0 25px rgba(37, 99, 235, 0.4); }
        .blue-text-glow { text-shadow: 0 0 12px rgba(59, 130, 246, 0.5); }
        .premium-card { background: linear-gradient(180deg, #0b0f19 0%, #040712 100%); border: 1px solid rgba(59, 130, 246, 0.15); }
        input, select, textarea { background-color: #02050c !important; border: 1px solid rgba(59, 130, 246, 0.2) !important; color: white !important; }
        input:focus, select:focus, textarea:focus { border-color: #2563eb !important; outline: none !important; box-shadow: 0 0 12px rgba(37, 99, 235, 0.25); }
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between antialiased">

    <header class="border-b border-blue-500/20 bg-slate-950/90 backdrop-blur sticky top-0 z-50 px-4 py-4">
        <div class="container mx-auto flex justify-between items-center">
            <a href="/" class="text-2xl font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-blue-500 to-sky-400 blue-text-glow">VEST TRAFFER</a>
            <div>
                {% if 'user_id' not in session %}
                    <a href="/login" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-slate-900 border border-blue-500/30 text-blue-400 font-bold">Войти</a>
                {% else %}
                    <a href="/logout" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-red-950/40 border border-red-500/30 text-red-400 font-medium">Выйти</a>
                {% endif %}
            </div>
        </div>
    </header>

    <main class="flex-grow container mx-auto px-4 py-6 max-w-4xl">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            {% for message in messages %}
              <div class="bg-blue-950/60 border border-blue-500/40 text-blue-200 p-4 rounded-2xl mb-6 text-sm font-semibold shadow-md">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>

    {% if 'user_id' in session %}
    <div class="fixed bottom-0 left-0 right-0 border-t border-slate-900 bg-slate-950/95 backdrop-blur-md py-3 px-4 z-50">
        <div class="max-w-md mx-auto flex justify-between items-center gap-2">
            <a href="/dashboard?tab=accounts" class="flex-1 text-center py-2.5 rounded-xl text-xs font-bold transition-all {% if current_tab == 'accounts' %} bg-blue-600 text-white blue-glow {% else %} bg-slate-900 text-slate-400 border border-slate-800 {% endif %}">Менеджер аккаунтов</a>
            <a href="/dashboard?tab=functions" class="flex-1 text-center py-2.5 rounded-xl text-xs font-bold transition-all {% if current_tab == 'functions' %} bg-blue-600 text-white blue-glow {% else %} bg-slate-900 text-slate-400 border border-slate-800 {% endif %}">Функции</a>
            <a href="/dashboard?tab=profile" class="flex-1 text-center py-2.5 rounded-xl text-xs font-bold transition-all {% if current_tab == 'profile' %} bg-blue-600 text-white blue-glow {% else %} bg-slate-900 text-slate-400 border border-slate-800 {% endif %}">Профиль</a>
        </div>
    </div>
    {% else %}
    <footer class="border-t border-slate-900 bg-slate-950/80 py-4 text-center">
        <p class="text-xs text-slate-500">Vest Traffer &copy; 2026. Поддержка: <a href="https://t.me/VestTraffSupport" target="_blank" class="text-blue-400 underline">@VestTraffSupport</a></p>
    </footer>
    {% endif %}

</body>
</html>
"""

def render_page(content_html, **context):
    if 'current_tab' not in context:
        context['current_tab'] = None
    full_page = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', content_html)
    return render_template_string(full_page, **context)

# --- Роуты страниц ---
@app.route('/')
def index():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    html = """
    <div class="text-center my-12 max-w-2xl mx-auto">
        <h1 class="text-4xl font-black mb-6 text-white leading-tight">Автоматизация трафика в Telegram</h1>
        <p class="text-slate-400 text-base mb-8">Удобная панель управления сеткой рабочих сессий, массовые рассылки и продвинутый автоответчик. Новым пользователям тест на 3 дня бесплатно.</p>
        <div class="flex flex-col sm:flex-row gap-4 justify-center">
            <a href="/register" class="px-6 py-3.5 rounded-xl bg-blue-600 text-white font-bold text-sm blue-glow">Создать кабинет</a>
            <a href="/login" class="px-6 py-3.5 rounded-xl bg-slate-900 border border-slate-800 text-slate-300 text-sm font-bold">Войти в систему</a>
        </div>
    </div>

    <div class="mt-16 max-w-3xl mx-auto px-2">
        <h2 class="text-2xl font-black mb-8 text-center text-blue-400 blue-text-glow uppercase tracking-wider">Часто задаваемые вопросы (FAQ)</h2>
        <div class="space-y-4">
            <div class="p-6 rounded-2xl premium-card">
                <h3 class="text-base sm:text-lg font-bold text-white mb-2">Какие виды чатов и переписок загружает софт?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Vest Traffer сканирует абсолютно все сущности аккаунта: группы, супергруппы, каналы, а также всю историю личных переписок (ЛС).</p>
            </div>
            <div class="p-6 rounded-2xl premium-card">
                <h3 class="text-base sm:text-lg font-bold text-white mb-2">Безопасно ли хранение сессий аккаунтов?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Все авторизованные аккаунты конвертируются в формат текстовых строк StringSession и хранятся в защищенной базе данных PostgreSQL.</p>
            </div>
        </div>
    </div>
    """
    return render_page(html)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            flash('Этот логин уже занят.')
            return redirect(url_for('register'))
            
        trial_ends = datetime.datetime.utcnow() + datetime.timedelta(days=3)
        new_user = User(username=username, password_hash=generate_password_hash(password), subscription_ends=trial_ends)
        db.session.add(new_user)
        db.session.commit()
        flash('Вы успешно зарегистрированы! Начислено 3 дня бесплатного теста.')
        return redirect(url_for('login'))
        
    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-2xl font-black mb-6 text-center text-blue-400">Регистрация</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Логин</label><input type="text" name="username" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Пароль</label><input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 font-bold text-white uppercase text-sm tracking-wider blue-glow">Зарегистрироваться</button>
        </form>
    </div>
    """
    return render_page(html)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            session['user_id'] = user.id
            session['username'] = user.username
            return redirect(url_for('dashboard'))
        flash('Неверный логин или пароль.')
        
    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-2xl font-black mb-6 text-center text-blue-400">Вход</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Логин</label><input type="text" name="username" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Пароль</label><input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 font-bold text-white uppercase text-sm tracking-wider blue-glow">Войти</button>
        </form>
    </div>
    """
    return render_page(html)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    current_tab = request.args.get('tab', 'accounts')
    user = User.query.get(session['user_id'])
    
    accounts = Account.query.filter_by(user_id=user.id).all()
    tasks = MailingTask.query.filter_by(user_id=user.id).order_by(MailingTask.id.desc()).all()
    responders = Autoresponder.query.filter_by(user_id=user.id).all()
    
    is_sub_active = user.subscription_ends > datetime.datetime.utcnow()
    sub_status_text = f"Активна до {user.subscription_ends.strftime('%d.%m.%Y %H:%M')}" if is_sub_active else "Истекла"

    if current_tab == 'accounts':
        html = """
        <div class="space-y-6">
            <div class="p-6 rounded-2xl premium-card flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 shadow-xl">
                <div>
                    <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider">👤 Менеджер аккаунтов</h2>
                    <p class="text-xs text-slate-500 mt-1">Привязка и управление сессиями</p>
                </div>
                <a href="/accounts/add" class="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-blue-600 text-white font-bold text-xs uppercase tracking-wider blue-glow text-center">+ Добавить аккаунт</a>
            </div>
            
            {% if not accounts %}
                <p class="text-slate-500 text-sm italic p-4 text-center">У вас пока нет привязанных аккаунтов Telegram.</p>
            {% else %}
                <div class="space-y-3">
                    {% for acc in accounts %}
                    <div class="p-4 rounded-xl bg-slate-950/60 border border-slate-900 flex justify-between items-center text-sm gap-4">
                        <div>
                            <p class="font-mono text-blue-400 font-bold">{{ acc.phone }}</p>
                            <span class="inline-block text-[10px] text-green-400 bg-green-950/20 px-2 py-0.5 rounded border border-green-500/20 mt-1 font-bold">ВАЛИДЕН</span>
                        </div>
                        <a href="/accounts/delete/{{ acc.id }}" class="text-xs text-red-400 hover:underline">Удалить</a>
                    </div>
                    {% endfor %}
                </div>
            {% endif %}
        </div>
        """
    
    elif current_tab == 'functions':
        html = f"""
        <div class="space-y-6">
            <div class="p-6 rounded-2xl premium-card shadow-xl">
                <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider mb-4">🚀 Запуск Рассылки (Этап 1)</h2>
                
                {% if not is_sub_active %}
                    <div class="p-4 bg-red-950/30 border border-red-500/30 text-red-400 rounded-xl text-xs font-bold mb-4">
                        Доступ заблокирован. Продлите лицензию во вкладке "Профиль".
                    </div>
                {% endif %}
                
                {% if not accounts %}
                    <p class="text-slate-500 text-sm italic">Для запуска функций сначала добавьте аккаунт во вкладке "Менеджер аккаунтов".</p>
                {% else %}
                    <form action="/mailing/load_chats" method="GET" class="space-y-4">
                        <div>
                            <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Выберите рабочий аккаунт для рассылки</label>
                            <select name="account_id" class="w-full rounded-xl px-4 py-3 text-white text-sm" {% if not is_sub_active %}disabled{% endif %}>
                                {% for acc in accounts %}
                                    <option value="{{ acc.id }}">{{ acc.phone }}</option>
                                {% endfor %}
                            </select>
                        </div>
                        <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 font-bold text-white text-xs uppercase tracking-wider blue-glow {% if not is_sub_active %}opacity-50 cursor-not-allowed{% endif %}" {% if not is_sub_active %}disabled{% endif %}>Загрузить переписки и перейти далее</button>
                    </form>
                {% endif %}
            </div>

            <div class="p-6 rounded-2xl premium-card shadow-xl">
                <div class="flex justify-between items-center mb-4">
                    <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider">🤖 Автоответчик</h2>
                    {% if accounts and is_sub_active %}
                    <a href="/autoresponder/select_acc" class="text-xs text-blue-400 font-bold hover:underline">Добавить автоответчик</a>
                    {% endif %}
                </div>
                {% if not responders %}
                    <p class="text-slate-500 text-sm italic">Нет запущенных автоответчиков.</p>
                {% else %}
                    <div class="space-y-3">
                        {% for r in responders %}
                        <div class="p-4 rounded-xl bg-slate-950/40 border border-slate-900 flex justify-between items-center text-xs">
                            <div>
                                <span class="text-slate-400 uppercase font-bold text-[10px]">Область:</span>
                                <span class="text-blue-400 font-bold">{% if r.trigger_type == 'pms' %}Только ЛС{% elif r.trigger_type == 'groups' %}Только группы{% else %}Все сообщения{% endif %}</span>
                                <p class="text-slate-500 mt-1">Ключевые слова: <code class="bg-slate-900 px-1 py-0.5 rounded text-slate-300 font-mono">{{ r.keywords }}</code></p>
                            </div>
                            <a href="/autoresponder/delete/{{ r.id }}" class="text-red-400 hover:underline">Выключить</a>
                        </div>
                        {% endfor %}
                    </div>
                {% endif %}
            </div>

            <div class="p-6 rounded-2xl premium-card shadow-xl">
                <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider mb-4">📊 Журнал и Прогресс Рассылок</h2>
                <div class="space-y-4">
                    {% for t in tasks %}
                    <div class="p-4 rounded-xl bg-slate-950 border border-slate-900 text-xs space-y-2">
                        <div class="flex justify-between font-mono">
                            <span class="text-slate-400">Задача #{{ t.id }} ({{ t.status }})</span>
                            <span class="text-blue-400 font-bold">{{ t.sent_count }} / {{ t.total_messages }}</span>
                        </div>
                        {% set pct = (t.sent_count / t.total_messages * 100)|int if t.total_messages > 0 else 0 %}
                        <div class="w-full bg-slate-900 rounded-full h-2 overflow-hidden border border-slate-800">
                            <div class="bg-blue-600 h-full rounded-full transition-all" style="width: {{ pct if pct <= 100 else 100 }}%"></div>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </div>
        """
        
    else:
        html = f"""
        <div class="space-y-6">
            <div class="p-6 rounded-2xl premium-card shadow-xl space-y-4">
                <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider pb-2 border-b border-slate-900">Профиль пользователя</h2>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4 text-sm">
                    <div class="p-4 bg-slate-950 rounded-xl border border-slate-900"><span class="text-xs text-slate-500 uppercase block font-bold">Ник</span><strong class="text-white font-mono text-base">{user.username}</strong></div>
                    <div class="p-4 bg-slate-950 rounded-xl border border-slate-900"><span class="text-xs text-slate-500 uppercase block font-bold">Количество аккаунтов</span><strong class="text-blue-400 text-base">{len(accounts)} шт.</strong></div>
                    <div class="p-4 bg-slate-950 rounded-xl border border-slate-900"><span class="text-xs text-slate-500 uppercase block font-bold">Активная подписка</span><strong class="text-purple-400 text-sm">{sub_status_text}</strong></div>
                </div>
            </div>

            <div class="p-6 rounded-2xl premium-card shadow-xl">
                <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider mb-4">🛒 Купить подписку Vest Traffer</h2>
                <form action="/subscription/pay" method="POST" class="space-y-4">
                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Выберите срок подписки</label>
                        <select name="duration" class="w-full rounded-xl px-4 py-3 text-white text-sm">
                            <option value="7">7 дней — 20₽</option>
                            <option value="14">14 дней — 35₽ (Выгода 12%)</option>
                            <option value="30">30 дней — 65₽ (Выгода 24%)</option>
                            <option value="60">60 дней — 110₽ (Выгода 35%)</option>
                            <option value="120">120 дней — 200₽ (Выгода 41%)</option>
                            <option value="360">360 дней — 500₽ (Выгода 51%)</option>
                        </select>
                    </div>
                    <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 font-bold text-white text-xs uppercase tracking-wider blue-glow">Оплатить через Crypto Bot</button>
                </form>
            </div>
        </div>
        """
        
    return render_page(html, current_tab=current_tab, accounts=accounts, tasks=tasks, responders=responders, is_sub_active=is_sub_active)

@app.route('/subscription/pay', methods=['POST'])
def subscription_pay():
    if 'user_id' not in session: return redirect(url_for('login'))
    duration = request.form.get('duration')
    
    pricing = {"7": 20, "14": 35, "30": 65, "60": 110, "120": 200, "360": 500}
    price = pricing.get(duration, 20)
    
    pay_url = create_crypto_pay_invoice(price)
    if pay_url:
        user = User.query.get(session['user_id'])
        days = int(duration)
        if user.subscription_ends > datetime.datetime.utcnow():
            user.subscription_ends += datetime.timedelta(days=days)
        else:
            user.subscription_ends = datetime.datetime.utcnow() + datetime.timedelta(days=days)
        db.session.commit()
        return redirect(pay_url)
    else:
        flash("Ошибка подключения к платежному шлюзу Crypto Bot. Повторите попытку.")
        return redirect(url_for('dashboard', tab='profile'))

@app.route('/mailing/load_chats')
def load_chats():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    acc = Account.query.filter_by(id=account_id, user_id=session['user_id']).first_or_404()
    try:
        chats_list = run_async(_get_chats(acc.session_string))
        session['temp_chats'] = chats_list
        return redirect(url_for('create_mailing_form', account_id=account_id))
    except Exception as e:
        flash(f"Ошибка загрузки диалогов аккаунта: {str(e)}")
        return redirect(url_for('dashboard', tab='functions'))

@app.route('/mailing/create', methods=['GET', 'POST'])
def create_mailing_form():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    chats = session.get('temp_chats', [])
    
    if request.method == 'POST':
        selected_chat_ids = request.form.getlist('selected_chats')
        if not selected_chat_ids or len(selected_chat_ids) > 50:
            flash("Вы должны выбрать от 1 до 50 диалогов.")
            return redirect(request.url)
            
        new_task = MailingTask(
            user_id=session['user_id'], account_id=account_id,
            chats=json.dumps(selected_chat_ids), message=request.form['message'],
            delay=int(request.form['delay']), total_messages=int(request.form['total_messages']),
            mailing_type=request.form['mailing_type']
        )
        db.session.add(new_task)
        db.session.commit()
        session.pop('temp_chats', None)
        flash("Кампания успешно сформирована и добавлена!")
        return redirect(url_for('dashboard', tab='functions'))

    html = """
    <div class="premium-card p-5 sm:p-8 rounded-3xl shadow-2xl max-w-4xl mx-auto">
        <div class="flex items-center justify-between max-w-md mx-auto mb-10 border-b border-slate-800 pb-6">
            <div class="text-center">
                <div class="w-8 h-8 rounded-full bg-blue-600 text-white font-bold flex items-center justify-center text-xs mx-auto blue-glow">1</div>
                <span class="text-[10px] uppercase font-bold text-blue-400 mt-2 block">Цели</span>
            </div>
            <div class="h-0.5 bg-slate-800 flex-grow mx-4 rounded" id="line-1"></div>
            <div class="text-center">
                <div class="w-8 h-8 rounded-full bg-slate-900 border border-slate-800 text-slate-500 font-bold flex items-center justify-center text-xs mx-auto">2</div>
                <span class="text-[10px] uppercase font-bold text-slate-500 mt-2 block">Опции</span>
            </div>
            <div class="h-0.5 bg-slate-800 flex-grow mx-4 rounded" id="line-2"></div>
            <div class="text-center">
                <div class="w-8 h-8 rounded-full bg-slate-900 border border-slate-800 text-slate-500 font-bold flex items-center justify-center text-xs mx-auto">3</div>
                <span class="text-[10px] uppercase font-bold text-slate-500 mt-2 block">Текст</span>
            </div>
        </div>

        <form method="POST" id="wizard-form" class="space-y-6">
            <div id="step-1" class="space-y-4">
                <div class="flex justify-between items-center"><label class="block text-xs font-bold uppercase text-slate-400">Выберите получателей (Выбрано: <span id="chat-counter" class="text-blue-400 font-black">0</span> / 50)</label><button type="button" onclick="selectAllChats()" class="text-xs text-blue-400 font-bold hover:underline">Выбрать первые 50</button></div>
                <div class="bg-slate-950 border border-slate-900 rounded-2xl p-3 h-72 overflow-y-auto space-y-2">
                    {% for c in chats %}
                    <label class="flex items-center gap-3 p-2.5 bg-slate-900/40 rounded-xl hover:bg-slate-900 cursor-pointer text-xs sm:text-sm border border-transparent hover:border-blue-500/10">
                        <input type="checkbox" name="selected_chats" value="{{ c.id }}" onchange="updateCounter()" class="w-4 h-4 rounded text-blue-600 bg-slate-950 border-slate-800 chat-checkbox">
                        <span class="truncate text-slate-200 font-medium">{{ c.title }}</span>
                    </label>
                    {% endfor %}
                </div>
                <div class="flex justify-end pt-4"><button type="button" onclick="goToStep(2)" class="px-6 py-3 rounded-xl bg-blue-600 text-white font-bold text-xs uppercase tracking-wider shadow-md blue-glow">Далее</button></div>
            </div>

            <div id="step-2" class="space-y-4 hidden">
                <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400">Параметры лимитов</h3>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div><label class="block text-xs font-bold uppercase text-slate-500 mb-2">Алгоритм обхода</label><select name="mailing_type" class="w-full rounded-xl px-4 py-3 text-white text-sm"><option value="simultaneous">Одновременный</option><option value="random">Рандомный</option></select></div>
                    <div><label class="block text-xs font-bold uppercase text-slate-500 mb-2">Задержка (сек.)</label><input type="number" name="delay" value="30" min="5" required class="w-full rounded-xl px-4 py-3 text-white text-sm"></div>
                    <div><label class="block text-xs font-bold uppercase text-slate-500 mb-2">Всего сообщений</label><input type="number" name="total_messages" value="10" min="1" required class="w-full rounded-xl px-4 py-3 text-white text-sm"></div>
                </div>
                <div class="flex justify-between pt-6 border-t border-slate-900"><button type="button" onclick="goToStep(1)" class="px-5 py-3 rounded-xl bg-slate-900 border border-slate-800 font-bold text-xs text-slate-400 uppercase">Назад</button><button type="button" onclick="goToStep(3)" class="px-6 py-3 rounded-xl bg-blue-600 text-white font-bold text-xs uppercase tracking-wider shadow-md blue-glow">Далее</button></div>
            </div>

            <div id="step-3" class="space-y-4 hidden">
                <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400">Текст сообщения</h3>
                <div><textarea name="message" rows="5" placeholder="Рекламное сообщение..." required class="w-full rounded-xl px-4 py-3 text-white text-sm"></textarea></div>
                <div class="flex justify-between pt-6 border-t border-slate-900"><button type="button" onclick="goToStep(2)" class="px-5 py-3 rounded-xl bg-slate-900 border border-slate-800 font-bold text-xs text-slate-400 uppercase">Назад</button><button type="submit" class="px-8 py-3.5 rounded-xl bg-blue-600 font-black text-white uppercase tracking-wider text-xs shadow-xl blue-glow">Запустить</button></div>
            </div>
        </form>
    </div>

    <script>
        function updateCounter() { let c = document.querySelectorAll('.chat-checkbox:checked').length; document.getElementById('chat-counter').innerText = c; }
        function selectAllChats() { let checkboxes = document.querySelectorAll('.chat-checkbox'); let count = 0; checkboxes.forEach(cb => { if(count < 50) { cb.checked = true; count++; } else { cb.checked = false; } }); updateCounter(); }
        function goToStep(s) {
            if (s === 2) { let c = document.querySelectorAll('.chat-checkbox:checked').length; if (c === 0 || c > 50) { alert("Ошибка: Вы должны выбрать от 1 до 50 диалогов."); return; } }
            document.getElementById('step-1').classList.add('hidden'); document.getElementById('step-2').classList.add('hidden'); document.getElementById('step-3').classList.add('hidden');
            document.getElementById('step-' + s).classList.remove('hidden');
            document.getElementById('line-1').style.backgroundColor = (s >= 2) ? "#2563eb" : "#1e293b"; document.getElementById('line-2').style.backgroundColor = (s >= 3) ? "#2563eb" : "#1e293b";
        }
    </script>
    """
    return render_page(html, chats=chats, current_tab='functions')

@app.route('/autoresponder/select_acc')
def autoresponder_select_acc():
    if 'user_id' not in session: return redirect(url_for('login'))
    accounts = Account.query.filter_by(user_id=session['user_id']).all()
    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl">
        <h2 class="text-xl font-black text-blue-400 mb-6 uppercase tracking-wider">Выбор аккаунта для автоответчика</h2>
        <form action="/autoresponder/setup" method="GET" class="space-y-4">
            <div>
                <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Выберите аккаунт</label>
                <select name="account_id" class="w-full rounded-xl px-4 py-3 text-white text-sm">
                    {% for acc in accounts %}
                        <option value="{{ acc.id }}">{{ acc.phone }}</option>
                    {% endfor %}
                </select>
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 text-white font-bold text-xs uppercase tracking-wider blue-glow">Перейти к настройке</button>
        </form>
    </div>
    """
    return render_page(html, accounts=accounts, current_tab='functions')

@app.route('/autoresponder/setup', methods=['GET', 'POST'])
def autoresponder_setup():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    
    if request.method == 'POST':
        new_responder = Autoresponder(
            user_id=session['user_id'], account_id=account_id,
            trigger_type=request.form['trigger_type'], keywords=request.form['keywords'].strip(),
            reply_text=request.form['reply_text'], is_active=True
        )
        db.session.add(new_responder)
        db.session.commit()
        flash("Автоответчик успешно настроен и запущен!")
        return redirect(url_for('dashboard', tab='functions'))
        
    html = """
    <div class="max-w-xl mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl">
        <h2 class="text-xl font-black text-blue-400 mb-6 uppercase tracking-wider">Настройка Автоответчика</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Где ловить сообщения?</label>
                <select name="trigger_type" class="w-full rounded-xl px-4 py-3 text-white text-sm">
                    <option value="pms">Только личные сообщения (ЛС)</option>
                    <option value="groups">Только группы и супергруппы</option>
                    <option value="all">Все входящие сообщения</option>
                </select>
            </div>
            <div>
                <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Ключевые слова-триггеры</label>
                <input type="text" name="keywords" value="-" required class="w-full rounded-xl px-4 py-3 text-sm">
                <p class="text-[10px] text-slate-500 mt-1">Перечислите ключевые слова через запятую. Если написать одиночный знак <strong>-</strong>, автоответчик будет реагировать на любые входящие.</p>
            </div>
            <div>
                <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Текст автоответа</label>
                <textarea name="reply_text" rows="4" required class="w-full rounded-xl px-4 py-3 text-sm"></textarea>
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 text-white font-bold text-sm uppercase blue-glow">Активировать автоответчик</button>
        </form>
    </div>
    """
    return render_page(html, current_tab='functions')

@app.route('/autoresponder/delete/<int:rid>')
def autoresponder_delete(rid):
    if 'user_id' not in session: return redirect(url_for('login'))
    r = Autoresponder.query.filter_by(id=rid, user_id=session['user_id']).first_or_404()
    db.session.delete(r)
    db.session.commit()
    return redirect(url_for('dashboard', tab='functions'))

@app.route('/accounts/add', methods=['GET', 'POST'])
def accounts_add():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        phone = request.form['phone'].replace(" ", "").replace("-", "")
        try:
            phone_code_hash, temp_session = run_async(_send_code(phone))
            session['auth_phone'] = phone
            session['auth_phone_code_hash'] = phone_code_hash
            session['auth_temp_session'] = temp_session
            return redirect(url_for('accounts_code'))
        except Exception as e:
            flash(f"Ошибка при отправке кода: {str(e)}")
            
    html = """
    <div class="max-w-md mx-auto premium-card p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-blue-400">Привязка аккаунта</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Номер телефона</label><input type="text" name="phone" placeholder="+79991234567" required class="w-full rounded-xl px-4 py-3 text-white text-sm"></div>
            <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 font-bold text-white transition-all text-sm uppercase tracking-wider shadow-md blue-glow">Запросить СМС</button>
        </form>
    </div>
    """
    return render_page(html, current_tab='accounts')

@app.route('/accounts/code', methods=['GET', 'POST'])
def accounts_code():
    if 'user_id' not in session or 'auth_phone' not in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        code = request.form['code']
        try:
            status, session_str = run_async(_sign_in_code(
                session['auth_phone'], code, session['auth_phone_code_hash'], session['auth_temp_session']
            ))
            session['auth_temp_session'] = session_str
            if status == "SUCCESS":
                new_acc = Account(user_id=session['user_id'], phone=session['auth_phone'], session_string=session_str)
                db.session.add(new_acc)
                db.session.commit()
                flash("Аккаунт успешно подключен к Vest Traffer!")
                return redirect(url_for('dashboard'))
            elif status == "2FA_NEEDED":
                return redirect(url_for('accounts_2fa'))
        except Exception as e:
            flash(f"Ошибка кода: {str(e)}")

    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-blue-400">Ввод СМС-кода</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Код подтверждения</label><input type="text" name="code" required class="w-full rounded-xl px-4 py-3 text-center text-lg font-mono tracking-widest text-white"></div>
            <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 font-bold text-white uppercase tracking-wider text-sm transition-all shadow-md blue-glow">Подтвердить</button>
        </form>
    </div>
    """
    return render_page(html, current_tab='accounts')

@app.route('/accounts/2fa', methods=['GET', 'POST'])
def accounts_2fa():
    if 'user_id' not in session or 'auth_phone' not in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        password = request.form['password']
        try:
            final_session = run_async(_sign_in_2fa(password, session['auth_temp_session']))
            new_acc = Account(user_id=session['user_id'], phone=session['auth_phone'], session_string=final_session)
            db.session.add(new_acc)
            db.session.commit()
            flash("Аккаунт успешно добавлен в Vest Traffer!")
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"Неверный пароль 2FA: {str(e)}")

    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-blue-400">Облачный пароль (2FA)</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Введите двухфакторный пароль</label><input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-white text-sm"></div>
            <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 font-bold text-white uppercase text-sm tracking-wider transition-all shadow-md blue-glow">Авторизовать</button>
        </form>
    </div>
    """
    return render_page(html, current_tab='accounts')

@app.route('/accounts/delete/<int:aid>')
def accounts_delete(aid):
    if 'user_id' not in session: return redirect(url_for('login'))
    acc = Account.query.filter_by(id=aid, user_id=session['user_id']).first_or_404()
    db.session.delete(acc)
    db.session.commit()
    return redirect(url_for('dashboard', tab='accounts'))

application = app

if __name__ == '__main__':
    app.run(debug=True, port=5000)
