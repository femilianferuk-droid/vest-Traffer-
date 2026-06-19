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

# Оптимизация пула соединений под Serverless (Vercel)
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

# Автоматическое создание таблиц структуры при холодном старте Serverless контейнера
with app.app_context():
    db.create_all()

# --- Асинхронные функции Telethon Движка ---
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
        dialogs = await client.get_dialogs(limit=100)
        return [{'id': d.id, 'title': d.name} for d in dialogs if d.is_group or d.is_channel]
    finally:
        await client.disconnect()

# --- Глобальный Базовый Макет (Премиум Неон + Адаптивность) ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Traffer — Сетка аккаунтов и Рассылка</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <style>
        body { background-color: #05070f; color: #f1f5f9; font-family: 'Inter', sans-serif; }
        .neon-glow-cyan { box-shadow: 0 0 20px rgba(6, 182, 212, 0.2); }
        .neon-glow-purple { box-shadow: 0 0 20px rgba(168, 85, 247, 0.25); }
        .neon-text { text-shadow: 0 0 10px rgba(6, 182, 212, 0.5); }
        .gradient-card { background: linear-gradient(145deg, #0b1120 0%, #070a14 100%); }
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between antialiased">

    <header class="border-b border-cyan-500/20 bg-slate-950/80 backdrop-blur-md sticky top-0 z-50 px-4 sm:px-6 py-4">
        <div class="container mx-auto flex flex-col sm:flex-row justify-between items-center gap-4">
            <a href="/" class="text-2xl font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-500 neon-text">VEST TRAFFER</a>
            <div class="flex flex-wrap gap-3 justify-center items-center">
                {% if 'user_id' in session %}
                    <a href="/dashboard" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-slate-900 border border-purple-500/50 text-purple-300 hover:bg-purple-500/20 transition-all font-semibold">Панель управления</a>
                    <a href="/logout" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-red-950/40 border border-red-500/40 text-red-400 hover:bg-red-600 hover:text-white transition-all">Выйти</a>
                {% else %}
                    <a href="/login" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-slate-900 border border-cyan-500/40 text-cyan-400 hover:bg-cyan-500 hover:text-slate-950 font-bold transition-all">Войти</a>
                    <a href="/register" class="text-xs sm:text-sm px-5 py-2 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 text-white font-bold shadow-md hover:brightness-110 transition-all neon-glow-cyan">Регистрация</a>
                {% endif %}
            </div>
        </div>
    </header>

    <main class="flex-grow container mx-auto px-4 sm:px-6 py-8">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            {% for message in messages %}
              <div class="bg-purple-950/40 border border-purple-500/50 text-purple-200 p-4 rounded-2xl mb-6 shadow-lg text-sm sm:text-base">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>

    <footer class="border-t border-slate-900 bg-slate-950/60 py-6 px-4">
        <div class="container mx-auto flex flex-col md:flex-row justify-between items-center gap-4 text-center md:text-left">
            <div>
                <p class="text-sm font-semibold text-slate-400">&copy; 2026 <span class="text-cyan-400 font-bold">Vest Traffer</span>. Все права защищены.</p>
                <p class="text-xs text-slate-600 mt-1">Премиум платформа автоматизации трафика Telegram</p>
            </div>
            <div>
                <a href="https://t.me/VestTraffSupport" target="_blank" class="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-gradient-to-r from-cyan-600 to-blue-600 text-white font-bold text-sm shadow-md hover:scale-105 active:scale-95 transition-all neon-glow-purple">
                    ✈️ Написать в поддержку
                </a>
            </div>
        </div>
    </footer>

</body>
</html>
"""

def render_page(content_html, **context):
    """Вспомогательная безопасная функция сборки шаблонов под Vercel"""
    full_page = BASE_TEMPLATE.replace('{% block content %}{% endblock %}', content_html)
    return render_template_string(full_page, **context)

# --- Обработчик Ошибок ---
@app.errorhandler(500)
def serverless_error_handler(e):
    return f"<div style='background:#05070f;color:#f1f5f9;padding:20px;font-family:monospace;'><h2 style='color:#ef4444'>Serverless Traceback:</h2><pre>{traceback.format_exc()}</pre></div>", 500

# --- Роуты Страниц ---

@app.route('/')
def index():
    html = """
    <div class="text-center my-10 sm:my-20 max-w-4xl mx-auto px-2">
        <span class="px-3 py-1 text-xs font-bold tracking-widest text-cyan-400 uppercase bg-cyan-950/40 rounded-full border border-cyan-500/30">NEW UPDATE 2026</span>
        <h1 class="text-4xl sm:text-6xl font-black mb-6 tracking-tight mt-4 leading-tight">
            Автоматизируйте ваш трафик в <span class="text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-400">Telegram</span>
        </h1>
        <p class="text-base sm:text-xl text-slate-400 max-w-2xl mx-auto mb-10 leading-relaxed">
            Профессиональный софт для управления сетками аккаунтов, массовой циклической и рандомизированной рассылки без сложной настройки. Все сессии в облаке.
        </p>
        <div class="flex flex-col sm:flex-row gap-4 justify-center">
            <a href="/register" class="px-8 py-4 rounded-2xl bg-gradient-to-r from-cyan-500 to-purple-600 font-extrabold text-lg shadow-xl hover:brightness-110 active:scale-95 transition-all text-center">Создать личный кабинет</a>
            <a href="#faq-section" class="px-8 py-4 rounded-2xl bg-slate-900 border border-slate-800 text-slate-300 font-bold hover:bg-slate-800 transition-all text-center">Узнать больше (FAQ)</a>
        </div>
    </div>
    
    <div class="grid grid-cols-1 md:grid-cols-3 gap-6 my-16">
        <div class="p-6 rounded-2xl gradient-card border border-slate-900 shadow-xl">
            <div class="w-12 h-12 rounded-xl bg-cyan-950/50 border border-cyan-500/30 flex items-center justify-center text-xl mb-4 text-cyan-400">👤</div>
            <h3 class="text-lg font-bold text-white mb-2">Telethon Сессии</h3>
            <p class="text-sm text-slate-400">Все аккаунты сохраняются как зашифрованные StringSession. Нет файловой зависимости на диске.</p>
        </div>
        <div class="p-6 rounded-2xl gradient-card border border-slate-900 shadow-xl">
            <div class="w-12 h-12 rounded-xl bg-purple-950/50 border border-purple-500/30 flex items-center justify-center text-xl mb-4 text-purple-400">⚡</div>
            <h3 class="text-lg font-bold text-white mb-2">Умные рассылки</h3>
            <p class="text-sm text-slate-400">До 50 чатов на задачу. Выбирайте одновременный алгоритм обхода или случайный выбор таргетов.</p>
        </div>
        <div class="p-6 rounded-2xl gradient-card border border-slate-900 shadow-xl">
            <div class="w-12 h-12 rounded-xl bg-blue-950/50 border border-blue-500/30 flex items-center justify-center text-xl mb-4 text-blue-400">🤖</div>
            <h3 class="text-lg font-bold text-white mb-2">Фоновый Воркер</h3>
            <p class="text-sm text-slate-400">Telegram-бот мгновенно подхватывает задачи из СУБД, освобождая веб-интерфейс от нагрузок.</p>
        </div>
    </div>

    <div id="faq-section" class="mt-24 max-w-3xl mx-auto px-2">
        <h2 class="text-3xl font-extrabold mb-10 text-center text-purple-400 neon-text">Ответы на частые вопросы (FAQ)</h2>
        <div class="space-y-4">
            <div class="p-6 rounded-2xl gradient-card border border-slate-900">
                <h3 class="text-lg font-bold text-cyan-400 mb-2">Как работает привязка аккаунтов?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Авторизация идет через официальный протокол. Вы вводите телефон, код и пароль 2FA. Система упаковывает подключение в текстовую сессию.</p>
            </div>
            <div class="p-6 rounded-2xl gradient-card border border-slate-900">
                <h3 class="text-lg font-bold text-cyan-400 mb-2">Какие лимиты на отправку?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Вы можете выбрать до 50 чатов за раз. Ограничения по объёму и паузам вы задаете сами, во избежание спам-блоков рекомендуем ставить задержку от 30 секунд.</p>
            </div>
            <div class="p-6 rounded-2xl gradient-card border border-slate-900">
                <h3 class="text-lg font-bold text-cyan-400 mb-2">Что делать при возникновении сбоев?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Внизу каждой страницы нашего сервиса доступна кнопка перехода в официальный саппорт. Мы на связи и поможем с решением любых задач.</p>
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
        flash('Регистрация успешна! Теперь войти.')
        return redirect(url_for('login'))
    
    html = """
    <div class="max-w-md mx-auto gradient-card p-6 sm:p-8 rounded-3xl border border-cyan-500/20 shadow-2xl mt-6">
        <h2 class="text-2xl font-black mb-6 text-center text-cyan-400">Регистрация профиля</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Ваш Логин</label>
                <input type="text" name="username" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-cyan-500 focus:outline-none text-white text-sm">
            </div>
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Надежный Пароль</label>
                <input type="password" name="password" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-cyan-500 focus:outline-none text-white text-sm">
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 font-bold hover:brightness-110 active:scale-[0.99] transition-all text-sm uppercase tracking-wider shadow-lg">Создать кабинет</button>
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
    <div class="max-w-md mx-auto gradient-card p-6 sm:p-8 rounded-3xl border border-purple-500/20 shadow-2xl mt-6">
        <h2 class="text-2xl font-black mb-6 text-center text-purple-400">Вход в систему</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Логин</label>
                <input type="text" name="username" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-purple-500 focus:outline-none text-white text-sm">
            </div>
            <div>
                <label class="block text-xs font-semibold uppercase tracking-wider mb-2 text-slate-400">Пароль</label>
                <input type="password" name="password" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-purple-500 focus:outline-none text-white text-sm">
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-gradient-to-r from-purple-500 to-cyan-500 font-bold hover:brightness-110 active:scale-[0.99] transition-all text-sm uppercase tracking-wider shadow-lg">Войти</button>
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
            <div class="p-5 rounded-2xl gradient-card border border-slate-900 sticky top-24">
                <h2 class="text-sm font-bold uppercase tracking-widest mb-4 text-slate-500">Навигация</h2>
                <div class="flex flex-row lg:flex-col gap-2 overflow-x-auto lg:overflow-visible whitespace-nowrap pb-2 lg:pb-0">
                    <a href="#accounts-sec" class="px-4 py-2.5 rounded-xl bg-slate-950 border border-cyan-500/20 text-cyan-400 text-xs sm:text-sm font-medium hover:border-cyan-400 transition-all">👤 Менеджер аккаунтов</a>
                    <a href="#functions-sec" class="px-4 py-2.5 rounded-xl bg-slate-950 border border-purple-500/20 text-purple-400 text-xs sm:text-sm font-medium hover:border-purple-400 transition-all">⚡ Функции рассылки</a>
                </div>
            </div>
        </div>

        <div class="w-full lg:w-3/4 space-y-8">
            <section id="accounts-sec" class="p-5 sm:p-6 rounded-2xl gradient-card border border-slate-900 shadow-xl">
                <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6">
                    <h2 class="text-xl sm:text-2xl font-black text-cyan-400">Менеджер аккаунтов</h2>
                    <a href="/accounts/add" class="w-full sm:w-auto px-4 py-2.5 rounded-xl bg-cyan-600 text-white text-xs font-bold hover:bg-cyan-500 transition-all text-center shadow-md">+ Добавить аккаунт</a>
                </div>
                
                {% if not accounts %}
                    <p class="text-slate-500 text-sm">У вас пока нет добавленных Telegram-аккаунтов.</p>
                {% else %}
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {% for acc in accounts %}
                        <div class="p-4 rounded-xl bg-slate-950 border border-slate-900/60 flex justify-between items-center gap-4">
                            <div class="truncate">
                                <p class="font-mono text-cyan-400 text-sm sm:text-base truncate">{{ acc.phone }}</p>
                                <span class="inline-block text-[10px] text-green-400 bg-green-950/30 px-2 py-0.5 rounded border border-green-500/20 mt-1 font-bold uppercase tracking-wider">Активен</span>
                            </div>
                            <a href="/mailing/load_chats?account_id={{ acc.id }}" class="text-xs font-bold bg-purple-950/50 border border-purple-500/40 text-purple-300 px-3 py-2 rounded-xl hover:bg-purple-600 hover:text-white transition-all whitespace-nowrap">Рассылка</a>
                        </div>
                        {% endfor %}
                    </div>
                {% endif %}
            </section>

            <section id="functions-sec" class="p-5 sm:p-6 rounded-2xl gradient-card border border-slate-900 shadow-xl">
                <h2 class="text-xl sm:text-2xl font-black text-purple-400 mb-6">Функции: Мониторинг задач</h2>
                
                <div class="overflow-x-auto rounded-xl border border-slate-900 bg-slate-950">
                    <table class="w-full text-left text-xs sm:text-sm text-slate-400">
                        <thead class="bg-slate-900/50 text-[10px] sm:text-xs uppercase text-slate-400 border-b border-slate-900">
                            <tr>
                                <th class="py-3 px-4">ID</th>
                                <th class="py-3 px-4">Тип</th>
                                <th class="py-3 px-4">Кол-во</th>
                                <th class="py-3 px-4">Пауза</th>
                                <th class="py-3 px-4">Статус</th>
                            </tr>
                        </thead>
                        <tbody class="divide-y divide-slate-900">
                            {% for t in tasks %}
                            <tr class="hover:bg-slate-900/20 transition-all">
                                <td class="py-3.5 px-4 font-mono text-slate-300 text-xs">#{{ t.id }}</td>
                                <td class="py-3.5 px-4 text-xs">
                                    {% if t.mailing_type == 'simultaneous' %}Круговой{% else %}Рандом{% endif %}
                                </td>
                                <td class="py-3.5 px-4 text-purple-400 font-bold">{{ t.total_messages }}</td>
                                <td class="py-3.5 px-4 font-mono text-xs">{{ t.delay }}с</td>
                                <td class="py-3.5 px-4">
                                    <span class="inline-block text-[10px] sm:text-xs px-2 py-0.5 rounded-md border bg-slate-900 font-medium">{{ t.status }}</span>
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
    <div class="max-w-md mx-auto gradient-card p-6 sm:p-8 rounded-3xl border border-cyan-500/20 shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-cyan-400">Шаг 1: Привязка по номеру</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-2">Номер телефона</label>
                <input type="text" name="phone" placeholder="+79991234567" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-cyan-500 focus:outline-none text-white text-sm">
            </div>
            <button type="submit" class="w-full py-3 rounded-xl bg-cyan-600 font-bold hover:bg-cyan-500 text-white transition-all text-sm uppercase tracking-wider shadow-md">Запросить СМС-код</button>
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
                flash("Аккаунт успешно подключен!")
                return redirect(url_for('dashboard'))
            elif status == "2FA_NEEDED":
                return redirect(url_for('accounts_2fa'))
        except Exception as e:
            flash(f"Ошибка авторизации: {str(e)}")

    html = """
    <div class="max-w-md mx-auto gradient-card p-6 sm:p-8 rounded-3xl border border-cyan-500/20 shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-cyan-400">Шаг 2: Ввод кода</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-2">Код подтверждения</label>
                <input type="text" name="code" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-center text-lg font-mono tracking-widest focus:border-cyan-500 focus:outline-none text-white">
            </div>
            <button type="submit" class="w-full py-3 rounded-xl bg-cyan-600 font-bold text-white uppercase tracking-wider text-sm transition-all shadow-md">Подтвердить</button>
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
            flash("Аккаунт с 2FA успешно добавлен!")
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"Неверный пароль 2FA: {str(e)}")

    html = """
    <div class="max-w-md mx-auto gradient-card p-6 sm:p-8 rounded-3xl border border-purple-500/20 shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-purple-400">Шаг 3: Облачный пароль (2FA)</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-2">Ваш 2FA Пароль</label>
                <input type="password" name="password" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-purple-500 focus:outline-none text-white text-sm">
            </div>
            <button type="submit" class="w-full py-3 rounded-xl bg-gradient-to-r from-purple-500 to-cyan-500 font-bold text-white uppercase text-sm tracking-wider transition-all shadow-md">Авторизовать</button>
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
        session['temp_chats'] = chats_list
        return redirect(url_for('create_mailing_form', account_id=account_id))
    except Exception as e:
        flash(f"Не удалось считать чаты аккаунта: {str(e)}")
        return redirect(url_for('dashboard'))

@app.route('/mailing/create', methods=['GET', 'POST'])
def create_mailing_form():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    chats = session.get('temp_chats', [])
    
    if request.method == 'POST':
        selected_chat_ids = request.form.getlist('selected_chats')
        if not selected_chat_ids or len(selected_chat_ids) > 50:
            flash("Вы должны выбрать от 1 до 50 чатов.")
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
        flash("Задача зарегистрирована в СУБД для Telegram воркера!")
        return redirect(url_for('dashboard'))

    html = """
    <div class="gradient-card p-5 sm:p-8 rounded-3xl border border-purple-500/20 shadow-2xl max-w-4xl mx-auto mt-4">
        <h2 class="text-xl sm:text-2xl font-black mb-6 text-purple-400">Настройка рекламной рассылки</h2>
        <form method="POST" class="space-y-6">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                    <label class="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Выберите чаты (от 1 до 50)</label>
                    <div class="bg-slate-950 border border-slate-900 rounded-2xl p-3 h-64 overflow-y-auto space-y-2">
                        {% for c in chats %}
                        <label class="flex items-center gap-3 p-2 bg-slate-900/40 rounded-xl hover:bg-slate-900/90 cursor-pointer text-xs sm:text-sm transition-all">
                            <input type="checkbox" name="selected_chats" value="{{ c.id }}" class="w-4 h-4 rounded text-purple-600 bg-slate-950 border-slate-800">
                            <span class="truncate text-slate-200">{{ c.title }}</span>
                        </label>
                        {% endfor %}
                    </div>
                </div>
                
                <div class="space-y-4">
                    <div>
                        <label class="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Алгоритм рассылки</label>
                        <select name="mailing_type" class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 text-white text-sm focus:border-purple-500 focus:outline-none">
                            <option value="simultaneous">Одновременный (по кругу)</option>
                            <option value="random">Рандомный (случайный чат)</option>
                        </select>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Пауза (сек.)</label>
                            <input type="number" name="delay" value="30" min="5" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-purple-500 focus:outline-none text-white text-sm">
                        </div>
                        <div>
                            <label class="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Сообщений</label>
                            <input type="number" name="total_messages" value="10" min="1" required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-purple-500 focus:outline-none text-white text-sm">
                        </div>
                    </div>
                </div>
            </div>
            <div>
                <label class="block text-xs font-bold uppercase tracking-wider text-slate-400 mb-2">Рекламное сообщение</label>
                <textarea name="message" rows="4" placeholder="Введите ваш текст..." required class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-3 focus:border-purple-500 focus:outline-none text-white text-sm"></textarea>
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-gradient-to-r from-purple-600 to-cyan-500 font-bold text-white uppercase text-sm tracking-wider shadow-lg hover:brightness-110 transition-all">Запустить кампанию</button>
        </form>
    </div>
    """
    return render_page(html, chats=chats)

application = app

if __name__ == '__main__':
    app.run(debug=True, port=5000)
