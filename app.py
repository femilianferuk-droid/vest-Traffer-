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
    sent_count = db.Column(db.Integer, default=0) # Новое поле для прогресс-бара
    total_messages = db.Column(db.Integer, nullable=False)
    mailing_type = db.Column(db.String(50), nullable=False)  
    status = db.Column(db.String(50), default='Ожидает')  

class Autoresponder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    trigger_type = db.Column(db.String(30), nullable=False) 
    keywords = db.Column(db.Text, nullable=False) 
    reply_text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)

# Инициализация и автоматический патч структуры старых таблиц БД
with app.app_context():
    db.create_all()
    try:
        # Патч: Принудительно внедряем колонку sent_count, если таблица была создана ранее без неё
        db.session.execute(db.text("ALTER TABLE mailing_task ADD COLUMN IF NOT EXISTS sent_count INTEGER DEFAULT 0;"))
        db.session.commit()
    except Exception as patch_err:
        db.session.rollback()

# --- Асинхронные методы парсинга и авторизации сайтом ---
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
            raise Exception("Сессия этого аккаунта отозвана или невалидна.")
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

# --- Синий Премиум Макет (100% Адаптивный Вертикальный Скролл) ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Traffer</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <style>
        body { background-color: #02040a; color: #f3f4f6; font-family: 'Inter', sans-serif; }
        .blue-glow { box-shadow: 0 0 25px rgba(37, 99, 235, 0.4); }
        .blue-text-glow { text-shadow: 0 0 12px rgba(59, 130, 246, 0.5); }
        .premium-card { background: linear-gradient(180deg, #0b0f19 0%, #040712 100%); border: 1px solid rgba(59, 130, 246, 0.15); }
        input, select, textarea { background-color: #02050c !important; border: 1px solid rgba(59, 130, 246, 0.2) !important; color: white !important; }
        input:focus, select:focus, textarea:focus { border-color: #2563eb !important; outline: none !important; box-shadow: 0 0 12px rgba(37, 99, 235, 0.25); }
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between antialiased">

    <header class="border-b border-blue-500/20 bg-slate-950/90 backdrop-blur sticky top-0 z-50 px-4 py-4">
        <div class="container mx-auto flex flex-col sm:flex-row justify-between items-center gap-4">
            <a href="/" class="text-2xl font-black tracking-widest text-transparent bg-clip-text bg-gradient-to-r from-blue-500 to-sky-400 blue-text-glow">VEST TRAFFER</a>
            <div class="flex gap-3">
                {% if 'user_id' in session %}
                    <a href="/dashboard" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-slate-900 border border-blue-500/40 text-blue-400 hover:bg-blue-600 hover:text-white transition-all font-bold">Личный кабинет</a>
                    <a href="/logout" class="text-xs sm:text-sm px-4 py-2 rounded-xl bg-red-950/40 border border-red-500/30 text-red-400 hover:bg-red-600 hover:text-white transition-all font-medium">Выйти</a>
                {% else %}
                    <a href="/login" class="text-xs sm:text-sm px-5 py-2 rounded-xl bg-slate-900 border border-blue-500/30 text-blue-400 font-bold transition-all">Войти</a>
                    <a href="/register" class="text-xs sm:text-sm px-5 py-2 rounded-xl bg-blue-600 text-white font-bold hover:bg-blue-500 transition-all blue-glow">Регистрация</a>
                {% endif %}
            </div>
        </div>
    </header>

    <main class="flex-grow container mx-auto px-4 py-8 max-w-5xl">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            {% for message in messages %}
              <div class="bg-blue-950/60 border border-blue-500/40 text-blue-200 p-4 rounded-2xl mb-6 text-sm font-semibold shadow-md">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>

    <footer class="border-t border-slate-900 bg-slate-950/80 py-6 px-4 text-center">
        <div class="container mx-auto flex flex-col md:flex-row justify-between items-center gap-4">
            <p class="text-sm text-slate-500 mx-auto md:mx-0">&copy; 2026 <span class="text-blue-500 font-bold">Vest Traffer</span>. Официальная техподдержка проекта: <a href="https://t.me/VestTraffSupport" target="_blank" class="text-blue-400 underline hover:text-blue-300 font-bold">@VestTraffSupport</a></p>
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
    return f"<div style='background:#02040a;color:#f3f4f6;padding:20px;font-family:monospace;'><h2 style='color:#ef4444'>Serverless Traceback:</h2><pre>{traceback.format_exc()}</pre></div>", 500

# --- Роуты Страниц ---

@app.route('/')
def index():
    html = """
    <div class="text-center my-10 max-w-3xl mx-auto">
        <span class="px-4 py-1.5 text-xs font-bold tracking-widest text-blue-400 uppercase bg-blue-950/40 rounded-full border border-blue-500/30">PREMIUM EDITION</span>
        <h1 class="text-4xl sm:text-5xl font-black mb-6 text-white leading-tight mt-4">Профессиональный софт <br><span class="text-blue-400 blue-text-glow">Vest Traffer</span></h1>
        <p class="text-slate-400 text-base sm:text-lg mb-8">Менеджмент безлимитных сеток аккаунтов, пошаговые алгоритмы массовой рассылки по всем видам диалогов и автоматизированные триггерные автоответчики.</p>
        <a href="/register" class="px-8 py-4 rounded-2xl bg-blue-600 font-bold text-lg hover:bg-blue-500 text-white transition-all blue-glow inline-block">Создать рабочий профиль</a>
    </div>

    <div class="mt-20 max-w-3xl mx-auto px-2">
        <h2 class="text-2xl sm:text-3xl font-black mb-8 text-center text-blue-400 blue-text-glow uppercase tracking-wider">Часто задаваемые вопросы (FAQ)</h2>
        <div class="space-y-4">
            <div class="p-6 rounded-2xl premium-card">
                <h3 class="text-base sm:text-lg font-bold text-white mb-2">Какие виды чатов и переписок загружает софт?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">В отличие от аналогов, Vest Traffer сканирует абсолютно все сущности аккаунта: группы, супергруппы, каналы, а также всю историю личных переписок (ЛС).</p>
            </div>
            <div class="p-6 rounded-2xl premium-card">
                <h3 class="text-base sm:text-lg font-bold text-white mb-2">Безопасно ли хранение сессий аккаунтов?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Все авторизованные аккаунты конвертируются в формат текстовых строк StringSession и хранятся в защищенной базе данных PostgreSQL. Сессии используются сервером только для выполнения запущенных вами задач.</p>
            </div>
            <div class="p-6 rounded-2xl premium-card">
                <h3 class="text-base sm:text-lg font-bold text-white mb-2">Как работает модуль автоответчика?</h3>
                <p class="text-sm text-slate-400 leading-relaxed">Вы можете настроить триггер на ЛС или группы, указать ключевые слова через запятую или поставить знак "-", чтобы отвечать абсолютно на все новые входящие сообщения заготовленным рекламным текстом.</p>
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
        flash('Регистрация успешна!')
        return redirect(url_for('login'))
    
    html = """
    <div class="max-w-md mx-auto premium-card p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-2xl font-black mb-6 text-center text-blue-400">Регистрация кабинета</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Логин</label><input type="text" name="username" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Пароль</label><input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 font-bold text-white transition-all blue-glow uppercase tracking-wider text-sm">Создать профиль</button>
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
    <div class="max-w-md mx-auto premium-card p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-2xl font-black mb-6 text-center text-blue-400">Вход в систему</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Логин</label><input type="text" name="username" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Пароль</label><input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-sm"></div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 font-bold text-white transition-all blue-glow uppercase tracking-wider text-sm">Войти</button>
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
    responders = Autoresponder.query.filter_by(user_id=session['user_id']).all()
    
    html = """
    <div class="flex flex-col gap-8 w-full">
        
        <section class="p-6 rounded-2xl premium-card shadow-xl">
            <div class="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-6 pb-4 border-b border-slate-900">
                <div>
                    <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider">👤 Менеджер аккаунтов</h2>
                    <p class="text-xs text-slate-500 mt-1">Подключение аккаунтов через Telethon и запуск рабочих функций</p>
                </div>
                <a href="/accounts/add" class="w-full sm:w-auto px-5 py-2.5 rounded-xl bg-blue-600 text-white font-bold text-xs hover:bg-blue-500 transition-all text-center uppercase tracking-wider blue-glow">+ Подключить аккаунт</a>
            </div>
            
            {% if not accounts %}
                <p class="text-slate-500 text-sm italic">У вас пока нет активных сессий Telegram.</p>
            {% else %}
                <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {% for acc in accounts %}
                    <div class="p-4 rounded-xl bg-slate-950/60 border border-slate-900 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                        <div>
                            <p class="font-mono text-blue-400 text-sm font-bold">{{ acc.phone }}</p>
                            <span class="inline-block text-[10px] text-green-400 bg-green-950/20 px-2 py-0.5 rounded border border-green-500/20 mt-1 uppercase font-bold">Подключен</span>
                        </div>
                        <div class="flex gap-2 w-full sm:w-auto">
                            <a href="/mailing/load_chats?account_id={{ acc.id }}" class="flex-1 text-center text-xs font-bold bg-blue-600 text-white px-4 py-2.5 rounded-xl hover:bg-blue-500 transition-all shadow-md blue-glow">Рассылка</a>
                            <a href="/autoresponder/setup?account_id={{ acc.id }}" class="flex-1 text-center text-xs font-bold bg-slate-900 border border-slate-800 text-slate-300 px-3 py-2.5 rounded-xl hover:text-white transition-all">Автоответчик</a>
                        </div>
                    </div>
                    {% endfor %}
                </div>
            {% endif %}
        </section>

        <section class="p-6 rounded-2xl premium-card shadow-xl">
            <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider mb-4">🤖 Активные Автоответчики</h2>
            {% if not responders %}
                <p class="text-slate-500 text-sm italic">Нет запущенных конфигураций автоответа.</p>
            {% else %}
                <div class="space-y-3">
                    {% for r in responders %}
                    <div class="p-4 rounded-xl bg-slate-950/40 border border-slate-900 flex justify-between items-center text-sm gap-4">
                        <div>
                            <span class="text-xs uppercase font-bold text-slate-500">Область действия: </span>
                            <span class="text-blue-400 font-bold">
                                {% if r.trigger_type == 'pms' %}Только ЛС{% elif r.trigger_type == 'groups' %}Только группы{% else %}Все сообщения{% endif %}
                            </span>
                            <p class="text-xs text-slate-500 mt-1">Ключевые слова: <code class="bg-slate-900 px-1.5 py-0.5 rounded text-slate-300 font-mono">{{ r.keywords }}</code></p>
                        </div>
                        <a href="/autoresponder/delete/{{ r.id }}" class="text-xs bg-red-950/30 border border-red-500/30 text-red-400 px-3 py-1.5 rounded-xl hover:bg-red-600 hover:text-white transition-all">Остановить</a>
                    </div>
                    {% endfor %}
                </div>
            {% endif %}
        </section>

        <section class="p-6 rounded-2xl premium-card shadow-xl">
            <h2 class="text-xl font-black text-blue-400 uppercase tracking-wider mb-6">⚡ Журнал и Прогресс Рассылок (Скролл вниз)</h2>
            <div class="space-y-4">
                {% if not tasks %}
                    <p class="text-slate-500 text-sm italic">История рассылок пуста.</p>
                {% endif %}
                {% for t in tasks %}
                <div class="p-4 rounded-xl bg-slate-950 border border-slate-900 space-y-3">
                    <div class="flex flex-col sm:flex-row justify-between sm:items-center gap-2 text-xs sm:text-sm">
                        <span class="font-mono text-slate-400 font-bold">Задача #{{ t.id }} — Статус: <span class="text-blue-400">{{ t.status }}</span></span>
                        <span class="text-slate-400">Доставлено: <strong class="text-blue-400">{{ t.sent_count }}</strong> из <strong class="text-slate-300">{{ t.total_messages }}</strong></span>
                    </div>
                    
                    {% set pct = (t.sent_count / t.total_messages * 100)|int if t.total_messages > 0 else 0 %}
                    <div class="w-full bg-slate-900 rounded-full h-2.5 overflow-hidden border border-slate-800">
                        <div class="bg-blue-600 h-full rounded-full transition-all duration-500 blue-glow" style="width: {{ pct if pct <= 100 else 100 }}%"></div>
                    </div>

                    <details class="text-xs text-slate-500 group cursor-pointer">
                        <summary class="hover:text-slate-300 font-medium select-none py-1">Показать список выбранных ID чатов и опции</summary>
                        <div class="mt-2 p-3 bg-slate-900/60 rounded-xl space-y-2 text-slate-400">
                            <p><strong>Тип обхода:</strong> {% if t.mailing_type == 'simultaneous' %}Одновременный{% else %}Рандомный{% endif %} | <strong>Пауза:</strong> {{ t.delay }} секунд</p>
                            <p class="text-slate-500 font-semibold uppercase text-[10px] tracking-wider">Пул целей (JSON ID):</p>
                            <div class="max-h-24 overflow-y-auto font-mono text-[11px] bg-slate-950/80 p-2 rounded-lg text-blue-300">
                                {{ t.chats }}
                            </div>
                        </div>
                    </details>
                </div>
                {% endfor %}
            </div>
        </section>

    </div>
    """
    return render_page(html, accounts=accounts, tasks=tasks, responders=responders)

@app.route('/autoresponder/setup', methods=['GET', 'POST'])
def autoresponder_setup():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    
    if request.method == 'POST':
        new_responder = Autoresponder(
            user_id=session['user_id'],
            account_id=account_id,
            trigger_type=request.form['trigger_type'],
            keywords=request.form['keywords'].strip(),
            reply_text=request.form['reply_text'],
            is_active=True
        )
        db.session.add(new_responder)
        db.session.commit()
        flash("Автоответчик успешно запущен фоновым воркером!")
        return redirect(url_for('dashboard'))
        
    html = """
    <div class="max-w-xl mx-auto premium-card p-6 sm:p-8 rounded-3xl shadow-2xl">
        <h2 class="text-xl font-black text-blue-400 mb-6 uppercase tracking-wider">⚙️ Конфигурация Автоответчика</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-bold uppercase text-slate-400 mb-2">На какие сообщения реагировать?</label>
                <select name="trigger_type" class="w-full rounded-xl px-4 py-3 text-white text-sm">
                    <option value="pms">Только личные сообщения (ЛС)</option>
                    <option value="groups">Только группы и супергруппы</option>
                    <option value="all">Все входящие уведомления (ЛС + группы)</option>
                </select>
            </div>
            <div>
                <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Ключевые слова-триггеры</label>
                <input type="text" name="keywords" value="-" required class="w-full rounded-xl px-4 py-3 text-sm">
                <p class="text-[10px] text-slate-500 mt-1">Укажите ключевые слова через запятую. Если написать одиночный знак <strong class="text-blue-400">-</strong>, автоответчик будет срабатывать на абсолютно любые текстовые сообщения.</p>
            </div>
            <div>
                <label class="block text-xs font-bold uppercase text-slate-400 mb-2">Текст автоответа</label>
                <textarea name="reply_text" rows="4" placeholder="Ваш рекламный текст ответа..." required class="w-full rounded-xl px-4 py-3 text-sm"></textarea>
            </div>
            <button type="submit" class="w-full py-3.5 rounded-xl bg-blue-600 text-white font-bold text-sm uppercase tracking-wider blue-glow">Запустить триггер</button>
        </form>
    </div>
    """
    return render_page(html)

@app.route('/autoresponder/delete/<int:rid>')
def autoresponder_delete(rid):
    if 'user_id' not in session: return redirect(url_for('login'))
    r = Autoresponder.query.filter_by(id=rid, user_id=session['user_id']).first_or_404()
    db.session.delete(r)
    db.session.commit()
    flash("Автоответчик успешно деактивирован.")
    return redirect(url_for('dashboard'))

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
    <div class="max-w-md mx-auto premium-card p-8 rounded-3xl shadow-2xl mt-6">
        <h2 class="text-xl font-black mb-4 text-blue-400">Привязка аккаунта (Шаг 1)</h2>
        <form method="POST" class="space-y-4">
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Номер телефона</label><input type="text" name="phone" placeholder="+79991234567" required class="w-full rounded-xl px-4 py-3 text-white text-sm"></div>
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
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Код подтверждения</label><input type="text" name="code" required class="w-full rounded-xl px-4 py-3 text-center text-lg font-mono tracking-widest text-white"></div>
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
            <div><label class="block text-xs font-bold uppercase text-slate-400 mb-2">Введите двухфакторный пароль</label><input type="password" name="password" required class="w-full rounded-xl px-4 py-3 text-white text-sm"></div>
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
        flash("Пошаговый мастер завершен. Кампания передана боту в обработку!")
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
                    <label class="block text-xs font-bold uppercase tracking-wider text-slate-400">Выберите получателей (Выбрано: <span id="chat-counter" class="text-blue-400 font-black">0</span> / 50)</label>
                    <button type="button" onclick="selectAllChats()" class="text-xs text-blue-400 font-bold hover:underline">Выбрать первые 50</button>
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
                <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400">Настройка алгоритма и лимитов</h3>
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                        <label class="block text-xs font-bold uppercase text-slate-500 mb-2">Алгоритм обхода</label>
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
                <h3 class="text-sm font-bold uppercase tracking-wider text-slate-400">Текст рекламного креатива</h3>
                <div>
                    <textarea name="message" rows="5" placeholder="Введите ваш продающий рекламный оффер..." required class="w-full rounded-xl px-4 py-3 text-white text-sm"></textarea>
                </div>
                <div class="flex justify-between pt-6 border-t border-slate-900">
                    <button type="button" onclick="goToStep(2)" class="px-5 py-3 rounded-xl bg-slate-900 border border-slate-800 font-bold text-xs uppercase text-slate-400 hover:text-white transition-all">Назад</button>
                    <button type="submit" class="px-8 py-3.5 rounded-xl bg-blue-600 font-black text-white uppercase tracking-wider text-xs shadow-xl blue-glow hover:bg-blue-500 transition-all">Запустить рассылку</button>
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
                    alert("Ошибка: Вы должны выбрать от 1 до 50 диалогов.");
                    return;
                }
            }

            document.getElementById('step-1').classList.add('hidden');
            document.getElementById('step-2').classList.add('hidden');
            document.getElementById('step-3').classList.add('hidden');
            document.getElementById('step-' + stepNum).classList.remove('hidden');

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
            document.getElementById('line-1').style.backgroundColor = (stepNum >= 2) ? "#2563eb" : "#1e293b";
            document.getElementById('line-2').style.backgroundColor = (stepNum >= 3) ? "#2563eb" : "#1e293b";
        }
    </script>
    """
    return render_page(html, chats=chats)

application = app

if __name__ == '__main__':
    app.run(debug=True, port=5000)
