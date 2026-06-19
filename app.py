import asyncio
from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
import json
import traceback

app = Flask(__name__)
app.secret_key = 'vest_traffer_super_secret_key_1337'

# Конфигурация базы данных PostgreSQL и Telegram API
DATABASE_URL = "postgresql://bothost_db_6f5993e63d14:MKsFRAV0DVmbRSkNa1b_XNQVdJxnJJD2INqII8il4jk@node1.pghost.ru:15794/bothost_db_6f5993e63d14"
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Оптимизация соединений для Serverless сред (Vercel)
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 280
}

db = SQLAlchemy(app)

API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"

# --- Модели Базы Данных ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    session_string = db.Column(db.Text, nullable=False)

class MailingTask(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    chats = db.Column(db.Text, nullable=False)  
    message = db.Column(db.Text, nullable=False)
    delay = db.Column(db.Integer, nullable=False)
    total_messages = db.Column(db.Integer, nullable=False)
    mailing_type = db.Column(db.String(50), nullable=False)  
    status = db.Column(db.String(50), default='Ожидает')  

# Инициализация таблиц при старте контейнера Vercel
with app.app_context():
    db.create_all()

# --- Асинхронные Функции Telethon (Выполняются сайтом) ---
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
    """Сайт сканирует ВСЕ диалоги: Личные переписки (ЛС), Группы и Каналы"""
    client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    await client.connect()
    try:
        if not await client.is_user_authorized():
            raise Exception("Сессия этого аккаунта невалидна или была завершена.")
        
        dialogs = await client.get_dialogs(limit=120)
        parsed_chats = []
        for d in dialogs:
            title = d.name if d.name else f"ID {d.id}"
            
            # Маркировка типов чатов для премиального отображения
            if d.is_user:
                title = f"👤 {title} (Личная переписка)"
            elif d.is_group:
                title = f"👥 {title} (Группа)"
            elif d.is_channel:
                title = f"📢 {title} (Канал)"
            else:
                title = f"💬 {title} (Диалог)"
                
            parsed_chats.append({
                'id': d.id, 
                'title': title
            })
        return parsed_chats
    finally:
        await client.disconnect()

# --- Глобальный Базовый Макет (Премиум Неоново-Синий) ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Traffer — Панель Автоматизации</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <style>
        body { background-color: #030712; color: #f3f4f6; font-family: 'Inter', sans-serif; }
        .blue-glow { box-shadow: 0 0 25px rgba(37, 99, 235, 0.4); }
        .blue-text-glow { text-shadow: 0 0 15px rgba(59, 130, 246, 0.6); }
        .premium-card { background: linear-gradient(145deg, #0f172a 0%, #030712 100%); border: 1px solid rgba(59, 130, 246, 0.15); }
        input, select, textarea { background-color: #020617 !important; border: 1px solid rgba(59, 130, 246, 0.2) !important; color: white !important; }
        input:focus, select:focus, textarea:focus { border-color: #2563eb !important; outline: none !important; box-shadow: 0 0 12px rgba(37, 99, 235, 0.3); }
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between antialiased">

    <header class="border-b border-blue-500/20 bg-slate-950/90 backdrop-blur-md sticky top-0 z-50 px-4 sm:px-6 py-4">
        <div class="container mx-auto flex flex-col sm:flex-row justify-between items-center gap-4">
            <a href="/" class="text-2xl font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-blue-500 to-sky-400 blue-text-glow">VEST TRAFFER</a>
            <div class="flex flex-wrap gap-3 justify-center items-center">
                {% if 'user_id' in session %}
                    <a href="/dashboard" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-slate-900 border border-blue-500/40 text-blue-400 hover:bg-blue-600 hover:text-white transition-all font-bold">Панель управления</a>
                    <a href="/logout" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-red-950/40 border border-red-500/40 text-red-400 hover:bg-red-600 hover:text-white transition-all font-medium">Выйти</a>
                {% else %}
                    <a href="/login" class="text-xs sm:text-sm px-5 py-2 rounded-xl bg-slate-900 border border-blue-500/30 text-blue-400 hover:bg-blue-600 hover:text-white font-bold transition-all">Войти</a>
                    <a href="/register" class="text-xs sm:text-sm px-5 py-2 rounded-xl bg-blue-600 text-white font-bold hover:bg-blue-500 transition-all blue-glow">Регистрация</a>
                {% endif %}
            </div>
        </div>
    </header>

    <main class="flex-grow container mx-auto px-4 sm:px-6 py-8">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            {% for message in messages %}
              <div class="bg-blue-950/60 border border-blue-500/40 text-blue-200 p-4 rounded-2xl mb-6 shadow-lg text-sm font-medium">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>

    <footer class="border-t border-slate-900 bg-slate-950/80 py-6 px-4">
        <div class="container mx-auto flex flex-col md:flex-row justify-between items-center gap-4 text-center md:text-left">
            <div>
                <p class="text-sm font-semibold text-slate-400">&copy; 2026 <span class="text-blue-500 font-bold">Vest Traffer</span>. Все права защищены.</p>
                <p class="text-xs text-slate-600 mt-1">Премиум-софт для комплексного привлечения трафика и рассылок</p>
            </div>
            <div>
                <a href="https://t.me/VestTraffSupport" target="_blank" class="inline-flex items-center gap-2 px-6 py-3 rounded-xl bg-blue-600 text-white font-black text-sm shadow-lg hover:bg-blue-500 hover:scale-105 active:scale-95 transition-all blue-glow">
                    ✈️ Написать в поддержку
                </a>
            </div>
        </div>
    </footer>

</body>
</html>
"""

def render_page(content_html, **context):
    full_page = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', content_html)
    return render_template_string(full_page, **context)

@app.errorhandler(500)
def serverless_error_handler(e):
    return f"<div style='background:#030712;color:#f3f4f6;padding:20px;font-family:monospace;'><h2 style='color:#ef4444'>Serverless Traceback:</h2><pre>{traceback.format_exc()}</pre></div>", 500

# --- Роуты Приложения ---

@app.route('/')
def index():
    html = """
    <div class="text-center my-10 sm:my-20 max-w-4xl mx-auto px-2">
        <span class="px-4 py-1.5 text-xs font-bold tracking-widest text-blue-400 uppercase bg-blue-950/40 rounded-full border border-blue-500/30">SUPREME VERSION 2.5</span>
        <h1 class="text-4xl sm:text-6xl font-black mb-6 tracking-tight mt-5 leading-tight text-white">
            Масштабируйте ваш трафик в <span class="text-transparent bg-clip-text bg-gradient-to-r from-blue-500 to-sky-400 blue-text-glow">Telegram</span>
        </h1>
        <p class="text-base sm:text-xl text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            Автоматизированный веб-сервис Vest Traffer для мгновенного импорта аккаунтов, безопасного извлечения всех типов диалогов (включая ЛС) и запуска пошаговых рассылок.
        </p>
        <div class="flex flex-col sm:flex-row gap-4 justify-center">
            <a href="/register" class="px-8 py-4 rounded-2xl bg-blue-600 font-extrabold text-lg shadow-xl hover:bg-blue-500 active:scale-95 transition-all text-center blue-glow text-white">Начать работу</a>
            <a href="#faq-section" class="px-8 py-4 rounded-2xl bg-slate-900/50 border border-slate-800 text-slate-300 font-bold hover:bg-slate-800 transition-all text-center">Инструкция (FAQ)</a>
        </div>
    </div>
    
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 my-16">
        <div class="p-6 rounded-2xl premium-card shadow-xl">
            <div class="w-12 h-12 rounded-xl bg-blue-950/50 border border-blue-500/30 flex items-center justify-center text-xl mb-4 text-blue-400">🛡️</div>
            <h3 class="text-lg font-bold text-white mb-2">Облачные Сессии</h3>
            <p class="text-sm text-slate-400">Сайт упаковывает доступы в StringSession. Ваши аккаунты всегда защищены внутри СУБД PostgreSQL.</p>
        </div>
        <div class="p-6 rounded-2xl premium-card shadow-xl">
            <div class="w-12 h-12 rounded-xl bg-blue-950/50 border border-blue-500/30 flex items-center justify-center text-xl mb-4 text-blue-400">📊</div>
            <h3 class="text-lg font-bold text-white mb-2">Абсолютный Парсинг</h3>
            <p class="text-sm text-slate-400">Сайт сканирует все виды диалогов: личные переписки (ЛС), приватные группы, супергруппы и каналы.</p>
        </div>
        <div class="p-6 rounded-2xl premium-card shadow-xl">
            <div class="w-12 h-12 rounded-xl bg-blue-950/50 border border-blue-500/30 flex items-center justify-center text-xl mb-4 text-blue-400">🚶‍♂️</div>
            <h3 class="text-lg font-bold text-white mb-2">Пошаговый Конфигуратор</h3>
            <p class="text-sm text-slate-400">Интуитивный Wizard-интерфейс создания рассылки по этапам с автоматической валидацией лимитов.</p>
        </div>
    </div>

    <div id="faq-section" class="mt-24 max-w-3xl mx-auto px-2">
        <h2 class="text-3xl font-extrabold mb-10 text-center text-blue-400 blue-text-glow">Часто задаваемые вопросы</h2>
        <div class="space-y-4">
            <div class="p-6 rounded-2xl premium-card">
                <h3 class="text-lg font-bold text-blue-400 mb-2">Какие типы чатов поддерживает софт?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Vest Traffer поддерживает отправку как по группам/каналам, так и по пользователям из списка ваших личных диалогов (ЛС).</p>
            </div>
            <div class="p-6 rounded-2xl premium-card">
                <h3 class="text-lg font-bold text-blue-400 mb-2">Как работает фоновый воркер?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">После завершения всех шагов настройки на сайте, задача улетает в базу данных, откуда её моментально забирает в работу фоновый скрипт бота.</p>
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
        new_user = User(username=username, password_hash=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        flash('Регистрация успешна! Войдите в аккаунт.')
        return redirect(url_for('login'))
    
    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-2xl font-black mb-6 text-center text-blue-400">Регистрация профиля</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Логин</label>
                <input type="text" name="username" required class="w-full rounded-xl px-4 py-3 text-sm text-white">
            </div>
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Пароль</label>
                <input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-sm text-white">
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 font-bold hover:bg-blue-500 transition-all text-sm uppercase tracking-wider shadow-lg blue-glow text-white">Создать аккаунт</button>
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
        <h2 class="text-2xl font-black mb-6 text-center text-blue-400">Авторизация</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Логин</label>
                <input type="text" name="username" required class="w-full rounded-xl px-4 py-3 text-sm text-white">
            </div>
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Пароль</label>
                <input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-sm text-white">
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 font-bold hover:bg-blue-500 transition-all text-sm uppercase tracking-wider shadow-lg blue-glow text-white">Войти</button>
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
    
    accounts = Account.query.filter_by(user_id=session['user_id']).all()
    tasks = MailingTask.query.filter_by(user_id=session['user_id']).order_by(MailingTask.id.desc()).all()
    
    html = """
    <div class="flex flex-col lg:flex-row gap-8">
        <div class="w-full lg:w-1/4">
            <div class="p-5 rounded-2xl premium-card sticky top-24">
                <h2 class="text-sm font-bold uppercase tracking-widest mb-4 text-slate-500">Vest Traffer</h2>
                <div class="flex flex-row lg:flex-col gap-2 overflow-x-auto lg:overflow-visible whitespace-nowrap pb-2 lg:pb-0">
                    <a href="#accounts-sec" class="px-4 py-2.5 rounded-xl bg-slate-950 border border-blue-500/20 text-blue-400 text-xs sm:text-sm font-bold hover:border-blue-400 transition-all">👤 Менеджер аккаунтов</a>
                    <a href="#functions-sec" class="px-4 py-2.5 rounded-xl bg-slate-950 border border-blue-500/20 text-blue-400 text-xs sm:text-sm font-bold hover:border-blue-400 transition-all">⚡ Лог рассылок</a>
                </div>
            </div>
        </div>

        <div class="w-full lg:w-3/4 space-y-8">
            <section id="accounts-sec" class="p-5 sm:p-6 rounded-2xl premium-card shadow-xl">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
                    <h2 class="text-xl sm:text-2xl font-black text-blue-400">Менеджер аккаунтов</h2>
                    <a href="/accounts/add" class="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-blue-600 text-white text-xs font-bold hover:bg-blue-500 transition-all text-center shadow-md blue-glow"> + Добавить аккаунт</a>
                </div>
                
                {% if not accounts %}
                    <p class="text-slate-500 text-sm">У вас пока нет подключенных аккаунтов.</p>
                {% else %}
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {% for acc in accounts %}
                        <div class="p-4 rounded-xl bg-slate-950 border border-slate-900 flex justify-between items-center gap-4">
                            <div class="truncate">
                                <p class="font-mono text-blue-400 text-sm sm:text-base truncate">{{ acc.phone }}</p>
                                <span class="inline-block text-[10px] text-green-400 bg-green-950/20 px-2 py-0.5 rounded border border-green-500/30 mt-1 font-bold uppercase tracking-wider">Валиден</span>
                            </div>
                            <a href="/mailing/load_chats?account_id={{ acc.id }}" class="text-xs font-bold bg-blue-600 text-white px-4 py-2.5 rounded-xl hover:bg-blue-500 transition-all whitespace-nowrap blue-glow">Считать все чаты</a>
                        </div>
                        {% endfor %}
                    </div>
                {% endif %}
            </section>

            <section id="functions-sec" class="p-5 sm:p-6 rounded-2xl premium-card shadow-xl">
                <h2 class="text-xl sm:text-2xl font-black text-blue-400 mb-6">Журнал запущенных кампаний</h2>
                
                <div class="overflow-x-auto rounded-xl border border-slate-900 bg-slate-950">
                    <table class="w-full text-left text-xs sm:text-sm text-slate-400">
                        <thead class="bg-slate-900/40 text-[10px] sm:text-xs uppercase text-slate-400 border-b border-slate-900">
                            <tr>
                                <th class="py-3 px-4">ID</th>
                                <th class="py-3 px-4">Тип</th>
                                <th class="py-3 px-4">Лимит</th>
                                <th class="py-3 px-4">Пауза</th>
                                <th class="py-3 px-4">Текущий Статус</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-900">
                            {% for t in tasks %}
                            <tr class="hover:bg-slate-900/10 transition-all">
                                <td class="py-3.5 px-4 font-mono text-slate-300 text-xs">#{{ t.id }}</td>
                                <td class="py-3.5 px-4 text-xs">
                                    {% if t.mailing_type == 'simultaneous' %}Одновременный{% else %}Рандомный{% endif %}
                                tap</td>
                                <td class="py-3.5 px-4 text-blue-400 font-bold">{{ t.total_messages }}</td>
                                <td class="py-3.5 px-4 font-mono text-xs">{{ t.delay }}с</td>
                                <td class="py-3.5 px-4">
                                    <span class="inline-block text-[10px] sm:text-xs px-2 py-0.5 rounded-md border bg-slate-900 font-bold border-blue-500/20 text-blue-300">{{ t.status }}</span>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
    </div>
    """
    return render_page(html, accounts=accounts, tasks=tasks)

@app.route('/accounts/add', methods=['GET', 'POST'])
def accounts_add():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        phone = request.form['phone'].replace(" ", "").replace("-", "")
        try:
            phone_code_hash, temp_session = asyncio.run(_send_code(phone))
            session['auth_phone'] = phone
            session['auth_phone_code_hash'] = phone_code_hash
            session['auth_temp_session'] = temp_session
            return redirect(url_for('accounts_code'))
        except Exception as e:
            flash(f"Ошибка при отправке кода: {str(e)}")
            
    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-blue-400">Привязка аккаунта (Шаг 1)</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-2">Номер телефона</label>
                <input type="text" name="phone" placeholder="+79991234567" required class="w-full rounded-xl px-4 py-3 text-white text-sm">
            </div>
            <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 font-bold hover:bg-blue-500 text-white transition-all text-sm uppercase tracking-wider shadow-md blue-glow">Запросить СМС</button>
        </form>
    </div>
    """
    return render_page(html)

@app.route('/accounts/code', methods=['GET', 'POST'])
def accounts_code():
    if 'user_id' not in session or 'auth_phone' not in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        code = request.form['code']
        try:
            status, session_str = asyncio.run(_sign_in_code(
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
        <h2 class="text-xl font-black mb-4 text-blue-400">Ввод СМС-кода (Шаг 2)</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-2">Код подтверждения</label>
                <input type="text" name="code" required class="w-full rounded-xl px-4 py-3 text-center text-lg font-mono tracking-widest text-white">
            </div>
            <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 font-bold text-white uppercase tracking-wider text-sm transition-all shadow-md blue-glow">Подтвердить</button>
        </form>
    </div>
    """
    return render_page(html)

@app.route('/accounts/2fa', methods=['GET', 'POST'])
def accounts_2fa():
    if 'user_id' not in session or 'auth_phone' not in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        password = request.form['password']
        try:
            final_session = asyncio.run(_sign_in_2fa(password, session['auth_temp_session']))
            new_acc = Account(user_id=session['user_id'], phone=session['auth_phone'], session_string=final_session)
            db.session.add(new_acc)
            db.session.commit()
            flash("Аккаунт успешно добавлен в Vest Traffer!")
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"Неверный пароль 2FA: {str(e)}")

    html = """
    <div class="max-w-md mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-blue-400">Облачный пароль (Шаг 3)</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-2">Введите двухфакторный пароль</label>
                <input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-white text-sm">
            </div>
            <button type="submit" class="w-full py-3 rounded-xl bg-blue-600 font-bold text-white uppercase text-sm tracking-wider transition-all shadow-md blue-glow">Авторизовать</button>
        </form>
    </div>
    """
    return render_page(html)

@app.route('/mailing/load_chats')
def load_chats():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    acc = Account.query.filter_by(id=account_id, user_id=session['user_id']).first_or_404()
    try:
        chats_list = asyncio.run(_get_chats(acc.session_string))
        if not chats_list:
            flash("Сайт успешно считал сессию, но на аккаунте нет абсолютно никаких переписок или чатов.")
            return redirect(url_for('dashboard'))
        session['temp_chats'] = chats_list
        return redirect(url_for('create_mailing_form', account_id=account_id))
    except Exception as e:
        flash(f"Ошибка загрузки диалогов сайтом: {str(e)}")
        return redirect(url_for('dashboard'))

@app.route('/mailing/create', methods=['GET', 'POST'])
def create_mailing_form():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    chats = session.get('temp_chats', [])
    
    if request.method == 'POST':
        selected_chat_ids = request.form.getlist('selected_chats')
        if not selected_chat_ids or len(selected_chat_ids) > 50:
            flash("Вы должны выбрать от 1 до 50 целей для запуска.")
            return redirect(request.url)
            
        new_task = MailingTask(
            user_id=session['user_id'],
            account_id=account_id,
            chats=json.dumps(selected_chat_ids),
            message=request.form['message'],
            delay=int(request.form['delay']),
            total_messages=int(request.form['total_messages']),
            mailing_type=request.form['mailing_type']
        )
        db.session.add(new_task)
        db.session.commit()
        session.pop('temp_chats', None)
        flash("Пошаговый конфигуратор завершен. Задача успешно добавлена!")
        return redirect(url_for('dashboard'))

    html = """
    <div class="premium-card p-5 sm:p-8 rounded-3xl shadow-2xl max-w-4xl mx-auto mt-4">
        
        <div class="flex items-center justify-between max-w-md mx-auto mb-10 border-b border-slate-800 pb-6">
            <div class="text-center step-indicator" id="ind-1">
                <div class="w-8 h-8 rounded-full bg-blue-600 text-white font-bold flex items-center justify-center text-xs mx-auto blue-glow">1</div>
                <span class="text-[10px] uppercase font-bold text-blue-400 mt-2 block">Цели</span>
            </div>
            <div class="h-0.5 bg-slate-800 flex-grow mx-4 rounded" id="line-1"></div>
            <div class="text-center step-indicator" id="ind-2">
                <div class="w-8 h-8 rounded-full bg-slate-900 border border-slate-800 text-slate-500 font-bold flex items-center justify-center text-xs mx-auto">2</div>
                <span class="text-[10px] uppercase font-bold text-slate-500 mt-2 block">Опции</span>
            </div>
            <div class="h-0.5 bg-slate-800 flex-grow mx-4 rounded" id="line-2"></div>
            <div class="text-center step-indicator" id="ind-3">
                <div class="w-8 h-8 rounded-full bg-slate-900 border border-slate-800 text-slate-500 font-bold flex items-center justify-center text-xs mx-auto">3</div>
                <span class="text-[10px] uppercase font-bold text-slate-500 mt-2 block">Текст</span>
            </div>
        </div>

        <form method="POST" id="wizard-form" class="space-y-6">
            
            <div id="step-1" class="space-y-4">
                <div class="flex justify-between items-center">
                    <label class="block text-xs font-bold uppercase tracking-wider text-slate-400">Шаг 1: Выберите получателей (Выбрано: <span id="chat-counter" class="text-blue-400 font-black">0</span> / 50)</label>
                    <button type="button" onclick="selectAllChats()" class="text-xs text-blue-400 font-bold hover:underline">Выбрать топ-50</button>
                </div>
                <div class="bg-slate-950 border border-slate-900 rounded-2xl p-3 h-72 overflow-y-auto space-y-2">
                    {% for c in chats %}
                    <label class="flex items-center gap-3 p-2.5 bg-slate-900/40 rounded-xl hover:bg-slate-900 cursor-pointer text-xs sm:text-sm transition-all border border-transparent hover:border-blue-500/10">
                        <input type="checkbox" name="selected_chats" value="{{ c.id }}" onchange="updateCounter()" class="w-4 h-4 rounded text-blue-600 bg-slate-950 border-slate-800 chat-checkbox">
                        <span class="truncate text-slate-200 font-medium">{{ c.title }}</span>
                    </label>
                    {% endfor %}
                </div>
                <div class="flex justify-end pt-4">
                    <button type="button" onclick="goToStep(2)" class="px-6 py-3 rounded-xl bg-blue-600 text-white font-bold text-xs uppercase tracking-wider shadow-md blue-glow hover:bg-blue-500 transition-all">Далее</button>
                </div>
            </div>

            <div id="step-2" class="space-y-4 hidden">
                <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400">Шаг 2: Настройка таймингов</h3>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-2">Алгоритм</label>
                        <select name="mailing_type" class="w-full rounded-xl px-4 py-3 text-white text-sm">
                            <option value="simultaneous">Одновременный (по кругу)</option>
                            <option value="random">Рандомный (выборочно)</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-2">Пауза (сек.)</label>
                        <input type="number" name="delay" value="30" min="5" required class="w-full rounded-xl px-4 py-3 text-white text-sm">
                    </div>
                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-2">Всего сообщений</label>
                        <input type="number" name="total_messages" value="10" min="1" required class="w-full rounded-xl px-4 py-3 text-white text-sm">
                    </div>
                </div>
                <div class="flex justify-between pt-6 border-t border-slate-900">
                    <button type="button" onclick="goToStep(1)" class="px-5 py-3 rounded-xl bg-slate-900 border border-slate-800 font-bold text-xs uppercase text-slate-400 hover:text-white transition-all">Назад</button>
                    <button type="button" onclick="goToStep(3)" class="px-6 py-3 rounded-xl bg-blue-600 text-white font-bold text-xs uppercase tracking-wider shadow-md blue-glow hover:bg-blue-500 transition-all">Далее</button>
                </div>
            </div>

            <div id="step-3" class="space-y-4 hidden">
                <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400">Шаг 3: Текст креатива</h3>
                <div>
                    <label class="block text-xs font-bold uppercase text-slate-500 mb-2">Сообщение для рассылки</label>
                    <textarea name="message" rows="5" placeholder="Введите ваш продающий рекламный текст или оффер..." required class="w-full rounded-xl px-4 py-3 text-white text-sm"></textarea>
                </div>
                <div class="flex justify-between pt-6 border-t border-slate-900">
                    <button type="button" onclick="goToStep(2)" class="px-5 py-3 rounded-xl bg-slate-900 border border-slate-800 font-bold text-xs uppercase text-slate-400 hover:text-white transition-all">Назад</button>
                    <button type="submit" class="px-8 py-3.5 rounded-xl bg-gradient-to-r from-blue-600 to-indigo-600 font-black text-white uppercase tracking-wider text-xs shadow-xl blue-glow hover:from-blue-500 transition-all">Запустить воркер</button>
                </div>
            </div>

        </form>
    </div>

    <script>
        function updateCounter() {
            let checkedCount = document.querySelectorAll('.chat-checkbox:checked').length;
            document.getElementById('chat-counter').innerText = checkedCount;
        }

        function selectAllChats() {
            let checkboxes = document.querySelectorAll('.chat-checkbox');
            let count = 0;
            checkboxes.forEach(cb => {
                if(count < 50) {
                    cb.checked = true;
                    count++;
                } else {
                    cb.checked = false;
                }
            });
            updateCounter();
        }

        function goToStep(stepNum) {
            if (stepNum === 2) {
                let checkedCount = document.querySelectorAll('.chat-checkbox:checked').length;
                if (checkedCount === 0 || checkedCount > 50) {
                    alert("Ошибка: Вы должны выбрать от 1 до 50 диалогов для старта кампании.");
                    return;
                }
            }

            // Скрываем все шаги
            document.getElementById('step-1').classList.add('hidden');
            document.getElementById('step-2').classList.add('hidden');
            document.getElementById('step-3').classList.add('hidden');

            // Показываем текущий
            document.getElementById('step-' + stepNum).classList.remove('hidden');

            // Сбрасываем стили степпера
            for(let i=1; i<=3; i++) {
                let ind = document.getElementById('ind-' + i);
                let circle = ind.querySelector('div');
                let text = ind.querySelector('span');
                
                if(i <= stepNum) {
                    circle.className = "w-8 h-8 rounded-full bg-blue-600 text-white font-bold flex items-center justify-center text-xs mx-auto blue-glow";
                    text.className = "text-[10px] uppercase font-bold text-blue-400 mt-2 block";
                } else {
                    circle.className = "w-8 h-8 rounded-full bg-slate-900 border border-slate-800 text-slate-500 font-bold flex items-center justify-center text-xs mx-auto";
                    text.className = "text-[10px] uppercase font-bold text-slate-500 mt-2 block";
                }
            }
            
            // Линии степпера
            document.getElementById('line-1').style.backgroundColor = (stepNum >= 2) ? "#2563eb" : "#1e293b";
            document.getElementById('line-2').style.backgroundColor = (stepNum >= 3) ? "#2563eb" : "#1e293b";
        }
    </script>
    """
    return render_page(html, chats=chats)

application = app

if __name__ == '__main__':
    app.run(debug=True, port=5000)
