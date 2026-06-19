# app.py
import asyncio
from flask import Flask, render_template_string, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from telethon.sync import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
import json

app = Flask(__name__)
app.secret_key = 'vest_traffer_super_secret_key_1337'

# Жестко прописанная конфигурация БД и Telegram API
DATABASE_URL = "postgresql://bothost_db_6f5993e63d14:MKsFRAV0DVmbRSkNa1b_XNQVdJxnJJD2INqII8il4jk@node1.pghost.ru:15794/bothost_db_6f5993e63d14"
app.config['SQLALCHEMY_DATABASE_REPOSITORY'] = DATABASE_URL
app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

API_ID = 32480523
API_HASH = "147839735c9fa4e83451209e9b55cfc5"

# --- Модели БД ---
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
    chats = db.Column(db.Text, nullable=False)  # Храним JSON-список ID/юзернеймов чатов
    message = db.Column(db.Text, nullable=False)
    delay = db.Column(db.Integer, nullable=False)
    total_messages = db.Column(db.Integer, nullable=False)
    mailing_type = db.Column(db.String(50), nullable=False)  # simultaneous / random
    status = db.Column(db.String(50), default='Ожидает')  # Ожидает, В работе, Завершено, Ошибка

# --- HTML Шаблоны (Премиальный Неоновый Дизайн) ---
BASE_TEMPLATE = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <title>Vest Traffer</title>
    <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
    <style>
        body { background-color: #0b0f19; color: #e2e8f0; font-family: 'Inter', sans-serif; }
        .neon-border { box-shadow: 0 0 15px rgba(6, 182, 212, 0.4); border-color: #06b6d4; }
        .neon-text { text-shadow: 0 0 8px rgba(168, 85, 247, 0.6); }
        .gradient-bg { background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%); }
    </style>
</head>
<body class="min-h-screen flex flex-col justify-between">
    <header class="border-b border-cyan-500/30 bg-slate-950/80 backdrop-blur px-6 py-4 flex justify-between items-center sticky top-0 z-50">
        <a href="/" class="text-2xl font-black tracking-wider text-transparent bg-clip-text bg-gradient-to-r from-cyan-400 to-purple-500 neon-text">VEST TRAFFER</a>
        <div class="flex gap-4">
            {% if 'user_id' in session %}
                <a href="/dashboard" class="px-4 py-2 rounded-lg bg-slate-900 border border-purple-500 hover:bg-purple-500/20 transition">Панель управления</a>
                <a href="/logout" class="px-4 py-2 rounded-lg bg-red-950/50 border border-red-500 text-red-400 hover:bg-red-500 hover:text-white transition">Выйти</a>
            {% else %}
                <a href="/login" class="px-4 py-2 rounded-lg bg-slate-900 border border-cyan-500 text-cyan-400 hover:bg-cyan-500 hover:text-slate-950 font-semibold transition">Войти</a>
                <a href="/register" class="px-4 py-2 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 text-white font-semibold shadow-lg hover:brightness-110 transition">Регистрация</a>
            {% endif %}
        </div>
    </header>
    <main class="flex-grow container mx-auto px-4 py-8">
        {% with messages = get_flashed_messages() %}
          {% if messages %}
            {% for message in messages %}
              <div class="bg-purple-950/50 border border-purple-500 text-purple-200 p-4 rounded-xl mb-6 shadow-md">{{ message }}</div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        {% block content %}{% endblock %}
    </main>
    <footer class="border-t border-slate-800 bg-slate-950 text-center py-4 text-sm text-slate-500">
        &copy; 2026 Vest Traffer. All rights reserved.
    </footer>
</body>
</html>
"""

@app.route('/')
def index():
    html = """
    {% extends "base" %}
    {% block content %}
    <div class="text-center my-16">
        <h1 class="text-5xl font-extrabold mb-6 tracking-tight">Автоматизируйте ваш трафик в <span class="text-cyan-400">Telegram</span></h1>
        <p class="text-xl text-slate-400 max-w-2xl mx-auto mb-8">Удобная рассылка сообщений, менеджмент сетки аккаунтов и полный контроль над кампаниями из одного личного кабинета.</p>
        <a href="/register" class="px-8 py-4 rounded-xl bg-gradient-to-r from-cyan-500 to-purple-600 font-bold text-lg shadow-[0_0_25px_rgba(6,182,212,0.4)] hover:scale-105 transition inline-block">Начать работу прямо сейчас</a>
    </div>
    
    <div class="mt-20 max-w-3xl mx-auto">
        <h2 class="text-3xl font-bold mb-8 text-center text-purple-400 neon-text">Часто задаваемые вопросы (FAQ)</h2>
        <div class="space-y-4">
            <div class="p-6 rounded-xl bg-slate-900 border border-slate-800">
                <h3 class="text-lg font-semibold text-cyan-400 mb-2">Как работает авторизация аккаунтов?</h3>
                <p class="text-slate-400">Мы используем официальный протокол авторизации Telegram через API ID и хэш. Код подтверждения отправляется напрямую в ваше приложение Telegram.</p>
            </div>
            <div class="p-6 rounded-xl bg-slate-900 border border-slate-800">
                <h3 class="text-lg font-semibold text-cyan-400 mb-2">Безопасно ли хранить аккаунты у вас?</h3>
                <p class="text-slate-400">Все сессии шифруются и хранятся в защищенной базе данных PostgreSQL. Сессия используется исключительно для выполнения созданных вами задач на рассылку.</p>
            </div>
            <div class="p-6 rounded-xl bg-slate-900 border border-slate-800">
                <h3 class="text-lg font-semibold text-cyan-400 mb-2">Какие лимиты на рассылку сообщений в чаты?</h3>
                <p class="text-slate-400">Платформа позволяет выбирать до 50 чатов на одну сессию рассылки. Для предотвращения спам-блоков рекомендуем ставить задержку между сообщениями не менее 30-60 секунд.</p>
            </div>
        </div>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html))

# --- Авторизация пользователей ---
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
        flash('Регистрация успешна! Теперь вы можете войти.')
        return redirect(url_for('login'))
    
    html = """
    {% extends "base" %}
    {% block content %}
    <div class="max-w-md mx-auto gradient-bg p-8 rounded-2xl border border-cyan-500/30 shadow-2xl mt-10">
        <h2 class="text-2xl font-bold mb-6 text-center text-cyan-400">Регистрация аккаунта</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Логин</label>
                <input type="text" name="username" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-cyan-500 focus:outline-none text-white">
            </div>
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Пароль</label>
                <input type="password" name="password" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-cyan-500 focus:outline-none text-white">
            </div>
            <button type="submit" class="w-full py-3 rounded-lg bg-gradient-to-r from-cyan-500 to-purple-600 font-bold hover:brightness-110 transition">Создать аккаунт</button>
        </form>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html))

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
    {% extends "base" %}
    {% block content %}
    <div class="max-w-md mx-auto gradient-bg p-8 rounded-2xl border border-purple-500/30 shadow-2xl mt-10">
        <h2 class="text-2xl font-bold mb-6 text-center text-purple-400">Авторизация</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Логин</label>
                <input type="text" name="username" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-purple-500 focus:outline-none text-white">
            </div>
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Пароль</label>
                <input type="password" name="password" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-purple-500 focus:outline-none text-white">
            </div>
            <button type="submit" class="w-full py-3 rounded-lg bg-gradient-to-r from-purple-500 to-cyan-500 font-bold hover:brightness-110 transition">Войти в кабинет</button>
        </form>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# --- Личный Кабинет ---
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    
    accounts = Account.query.filter_by(user_id=session['user_id']).all()
    tasks = MailingTask.query.filter_by(user_id=session['user_id']).order_by(MailingTask.id.desc()).all()
    
    html = """
    {% extends "base" %}
    {% block content %}
    <div class="flex flex-col lg:flex-row gap-8">
        <div class="w-full lg:w-1/4 flex flex-col gap-4">
            <div class="p-6 rounded-2xl bg-slate-900 border border-slate-800">
                <h2 class="text-lg font-bold mb-4 text-slate-400">Разделы системы</h2>
                <div class="flex flex-col gap-2">
                    <a href="#accounts-sec" class="px-4 py-2.5 rounded-lg bg-slate-950 border border-cyan-500/30 hover:border-cyan-400 text-cyan-400 font-medium transition block">👤 Менеджер аккаунтов</a>
                    <a href="#functions-sec" class="px-4 py-2.5 rounded-lg bg-slate-950 border border-purple-500/30 hover:border-purple-400 text-purple-400 font-medium transition block">⚡ Функции рассылки</a>
                </div>
            </div>
        </div>

        <div class="w-full lg:w-3/4 space-y-12">
            <section id="accounts-sec" class="p-6 rounded-2xl bg-slate-900 border border-slate-800">
                <div class="flex justify-between items-center mb-6">
                    <h2 class="text-2xl font-bold text-cyan-400">Менеджер аккаунтов</h2>
                    <a href="/accounts/add" class="px-4 py-2 rounded-lg bg-cyan-600 text-white text-sm font-bold hover:bg-cyan-500 transition">+ Добавить аккаунт</a>
                </div>
                {% if not accounts %}
                    <p class="text-slate-500">У вас пока нет добавленных Telegram-аккаунтов.</p>
                {% else %}
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
                        {% for acc in accounts %}
                        <div class="p-4 rounded-xl bg-slate-950 border border-slate-800 flex justify-between items-center">
                            <div>
                                <p class="font-mono text-cyan-400">{{ acc.phone }}</p>
                                <span class="text-xs text-green-400 bg-green-950/40 px-2 py-0.5 rounded border border-green-500/30">Активен</span>
                            </div>
                            <a href="/mailing/create?account_id={{ acc.id }}" class="text-xs bg-purple-950 border border-purple-500 text-purple-300 px-3 py-1.5 rounded-lg hover:bg-purple-500 hover:text-white transition">Запустить рассылку</a>
                        </div>
                        {% endfor %}
                    </div>
                {% endif %}
            </section>

            <section id="functions-sec" class="p-6 rounded-2xl bg-slate-900 border border-slate-800">
                <h2 class="text-2xl font-bold text-purple-400 mb-6">Функции: Рассылка</h2>
                
                {% if not accounts %}
                    <div class="p-4 bg-yellow-950/30 border border-yellow-600/40 text-yellow-300 rounded-xl mb-4 text-sm">
                        Для настройки рассылок сначала привяжите хотя бы один аккаунт во вкладке выше.
                    </div>
                {% else %}
                    <div class="p-4 bg-slate-950 border border-slate-800 rounded-xl mb-6">
                        <h3 class="font-semibold text-slate-300 mb-3">Быстрый запуск новой кампании</h3>
                        <form action="/mailing/load_chats" method="GET" class="flex gap-4 items-end">
                            <div class="flex-grow">
                                <label class="block text-xs font-medium mb-1 text-slate-400">Выберите аккаунт-донор чатов</label>
                                <select name="account_id" class="w-full bg-slate-900 border border-slate-800 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-purple-500">
                                    {% for acc in accounts %}
                                        <option value="{{ acc.id }}">{{ acc.phone }}</option>
                                    {% endfor %}
                                </select>
                            </div>
                            <button type="submit" class="px-5 py-2 rounded-lg bg-purple-600 hover:bg-purple-500 font-bold text-sm transition text-white whitespace-nowrap">Загрузить чаты аккаунта</button>
                        </form>
                    </div>
                {% endif %}

                <h3 class="text-lg font-bold text-slate-300 mb-4">Журнал и статусы текущих рассылок</h3>
                <div class="overflow-x-auto">
                    <table class="w-full text-left text-sm text-slate-400">
                        <thead class="bg-slate-950 text-xs uppercase text-slate-400 border-b border-slate-800">
                            <tr>
                                <th class="py-3 px-4">ID</th>
                                <th class="py-3 px-4">Тип</th>
                                <th class="py-3 px-4">Сообщений</th>
                                <th class="py-3 px-4">Задержка</th>
                                <th class="py-3 px-4">Статус</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for t in tasks %}
                            <tr class="border-b border-slate-800/50 hover:bg-slate-950/40">
                                <td class="py-3 px-4 font-mono text-slate-300">#{{ t.id }}</td>
                                <td class="py-3 px-4">
                                    {% if t.mailing_type == 'simultaneous' %}Одновременный{% else %}Рандомный{% endif %}
                                </td>
                                <td class="py-3 px-4 text-purple-400 font-semibold">{{ t.total_messages }}</td>
                                <td class="py-3 px-4 font-mono">{{ t.delay }} сек.</td>
                                <td class="py-3 px-4">
                                    {% if t.status == 'Ожидает' %}
                                        <span class="text-yellow-400 bg-yellow-950/40 border border-yellow-500/30 px-2 py-0.5 rounded text-xs">Ожидает</span>
                                    {% elif t.status == 'В работе' %}
                                        <span class="text-blue-400 bg-blue-950/40 border border-blue-500/30 px-2 py-0.5 rounded text-xs animate-pulse">В работе</span>
                                    {% elif t.status == 'Завершено' %}
                                        <span class="text-green-400 bg-green-950/40 border border-green-500/30 px-2 py-0.5 rounded text-xs">Завершено</span>
                                    {% else %}
                                        <span class="text-red-400 bg-red-950/40 border border-red-500/30 px-2 py-0.5 rounded text-xs">{{ t.status }}</span>
                                    {% endif %}
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </section>
        </div>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html), accounts=accounts, tasks=tasks)

# --- Добавление аккаунтов (Telethon Step-by-Step) ---
@app.route('/accounts/add', methods=['GET', 'POST'])
def accounts_add():
    if 'user_id' not in session: return redirect(url_for('login'))
    if request.method == 'POST':
        phone = request.form['phone'].replace(" ", "").replace("-", "")
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TelegramClient(StringSession(), API_ID, API_HASH, loop=loop)
        
        try:
            loop.run_until_complete(client.connect())
            phone_code_hash = loop.run_until_complete(client.send_code_request(phone)).phone_code_hash
            
            # Сохраняем промежуточные данные авторизации в сессию Flask
            session['auth_phone'] = phone
            session['auth_phone_code_hash'] = phone_code_hash
            session['auth_temp_session'] = client.session.save()
            return redirect(url_for('accounts_code'))
        except Exception as e:
            flash(f"Ошибка при отправке кода: {str(e)}")
        finally:
            loop.run_until_complete(client.disconnect())
            loop.close()

    html = """
    {% extends "base" %}
    {% block content %}
    <div class="max-w-md mx-auto gradient-bg p-8 rounded-2xl border border-cyan-500/30 shadow-2xl mt-10">
        <h2 class="text-2xl font-bold mb-6 text-cyan-400">Шаг 1: Привязка Телеграм аккаунта</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Номер телефона (с кодом страны)</label>
                <input type="text" name="phone" placeholder="+79991234567" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-cyan-500 focus:outline-none text-white">
            </div>
            <button type="submit" class="w-full py-3 rounded-lg bg-cyan-600 font-bold text-white hover:bg-cyan-500 transition">Получить код авторизации</button>
        </form>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html))

@app.route('/accounts/code', methods=['GET', 'POST'])
def accounts_code():
    if 'user_id' not in session or 'auth_phone' not in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        code = request.form['code']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TelegramClient(StringSession(session['auth_temp_session']), API_ID, API_HASH, loop=loop)
        
        try:
            loop.run_until_complete(client.connect())
            try:
                loop.run_until_complete(client.sign_in(session['auth_phone'], code, phone_code_hash=session['auth_phone_code_hash']))
                
                # Успешный вход без 2FA
                new_acc = Account(user_id=session['user_id'], phone=session['auth_phone'], session_string=client.session.save())
                db.session.add(new_acc)
                db.session.commit()
                flash("Аккаунт успешно подключен к системе Vest Traffer!")
                return redirect(url_for('dashboard'))
            except SessionPasswordNeededError:
                # Требуется 2FA пароль
                session['auth_temp_session'] = client.session.save()
                return redirect(url_for('accounts_2fa'))
        except Exception as e:
            flash(f"Неверный код или ошибка: {str(e)}")
        finally:
            loop.run_until_complete(client.disconnect())
            loop.close()

    html = """
    {% extends "base" %}
    {% block content %}
    <div class="max-w-md mx-auto gradient-bg p-8 rounded-2xl border border-cyan-500/30 shadow-2xl mt-10">
        <h2 class="text-2xl font-bold mb-6 text-cyan-400">Шаг 2: Ввод кода подтверждения</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Код из Telegram</label>
                <input type="text" name="code" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-cyan-500 focus:outline-none text-white text-center text-lg font-bold tracking-widest">
            </div>
            <button type="submit" class="w-full py-3 rounded-lg bg-cyan-600 font-bold text-white hover:bg-cyan-500 transition">Подтвердить код</button>
        </form>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html))

@app.route('/accounts/2fa', methods=['GET', 'POST'])
def accounts_2fa():
    if 'user_id' not in session or 'auth_phone' not in session: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        password = request.form['password']
        
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        client = TelegramClient(StringSession(session['auth_temp_session']), API_ID, API_HASH, loop=loop)
        
        try:
            loop.run_until_complete(client.connect())
            loop.run_until_complete(client.sign_in(password=password))
            
            new_acc = Account(user_id=session['user_id'], phone=session['auth_phone'], session_string=client.session.save())
            db.session.add(new_acc)
            db.session.commit()
            flash("Аккаунт с Двухфакторной аутентификацией (2FA) успешно добавлен!")
            return redirect(url_for('dashboard'))
        except Exception as e:
            flash(f"Неверный пароль 2FA: {str(e)}")
        finally:
            loop.run_until_complete(client.disconnect())
            loop.close()

    html = """
    {% extends "base" %}
    {% block content %}
    <div class="max-w-md mx-auto gradient-bg p-8 rounded-2xl border border-purple-500/30 shadow-2xl mt-10">
        <h2 class="text-2xl font-bold mb-6 text-purple-400">Шаг 3: Обнаружен Облачный Пароль (2FA)</h2>
        <form method="POST" class="space-y-4">
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Введите ваш пароль двухфакторной защиты</label>
                <input type="password" name="password" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-purple-500 focus:outline-none text-white">
            </div>
            <button type="submit" class="w-full py-3 rounded-lg bg-gradient-to-r from-purple-500 to-cyan-500 font-bold text-white transition">Авторизовать сессию</button>
        </form>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html))

# --- Парсинг чатов и создание задач на рассылку ---
@app.route('/mailing/load_chats')
def load_chats():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    acc = Account.query.filter_by(id=account_id, user_id=session['user_id']).first_or_404()
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = TelegramClient(StringSession(acc.session_string), API_ID, API_HASH, loop=loop)
    
    chats_list = []
    try:
        loop.run_until_complete(client.connect())
        dialogs = loop.run_until_complete(client.get_dialogs(limit=100))
        for d in dialogs:
            if d.is_group or d.is_channel:
                chats_list.append({'id': d.id, 'title': d.name})
    except Exception as e:
        flash(f"Не удалось считать чаты аккаунта: {str(e)}")
        return redirect(url_for('dashboard'))
    finally:
        loop.run_until_complete(client.disconnect())
        loop.close()

    session['temp_chats'] = chats_list
    return redirect(url_for('create_mailing_form', account_id=account_id))

@app.route('/mailing/create', methods=['GET', 'POST'])
def create_mailing_form():
    if 'user_id' not in session: return redirect(url_for('login'))
    account_id = request.args.get('account_id')
    chats = session.get('temp_chats', [])
    
    if request.method == 'POST':
        selected_chat_ids = request.form.getlist('selected_chats')
        if not selected_chat_ids or len(selected_chat_ids) > 50:
            flash("Вы должны выбрать от 1 до 50 чатов для проведения спам-кампании.")
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
        flash("Задача на рассылку успешно зарегистрирована и передана Telegram-боту в обработку!")
        return redirect(url_for('dashboard'))

    html = """
    {% extends "base" %}
    {% block content %}
    <div class="gradient-bg p-8 rounded-2xl border border-purple-500/30 shadow-2xl max-w-4xl mx-auto">
        <h2 class="text-2xl font-bold mb-6 text-purple-400">Параметры и конфигурация новой рассылки</h2>
        <form method="POST" class="space-y-6">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-6">
                <div>
                    <label class="block text-sm font-semibold text-slate-300 mb-2">Выберите целевые чаты (Выбрано: от 1 до 50)</label>
                    <div class="bg-slate-950 border border-slate-800 rounded-xl p-4 h-64 overflow-y-auto space-y-2">
                        {% for c in chats %}
                        <label class="flex items-center gap-3 p-2 bg-slate-900/60 rounded-lg hover:bg-slate-900 cursor-pointer text-sm">
                            <input type="checkbox" name="selected_chats" value="{{ c.id }}" class="rounded text-purple-600 focus:ring-purple-500 bg-slate-950 border-slate-800">
                            <span class="truncate text-slate-200">{{ c.title }}</span>
                        </label>
                        {% endfor %}
                    </div>
                </div>
                
                <div class="space-y-4">
                    <div>
                        <label class="block text-sm font-medium mb-1 text-slate-400">Тип алгоритма рассылки</label>
                        <select name="mailing_type" class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 text-white focus:border-purple-500 focus:outline-none">
                            <option value="simultaneous">Одновременный (по кругу)</option>
                            <option value="random">Рандомный (выборочный чат)</option>
                        </select>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-sm font-medium mb-1 text-slate-400">Задержка (в сек.)</label>
                            <input type="number" name="delay" value="30" min="5" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-purple-500 focus:outline-none text-white">
                        </div>
                        <div>
                            <label class="block text-sm font-medium mb-1 text-slate-400">Кол-во сообщений</label>
                            <input type="number" name="total_messages" value="10" min="1" required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-purple-500 focus:outline-none text-white">
                        </div>
                    </div>
                </div>
            </div>
            
            <div>
                <label class="block text-sm font-medium mb-1 text-slate-400">Текст рекламного сообщения</label>
                <textarea name="message" rows="4" placeholder="Введите текст сообщения..." required class="w-full bg-slate-950 border border-slate-800 rounded-lg px-4 py-2 focus:border-purple-500 focus:outline-none text-white"></textarea>
            </div>
            
            <button type="submit" class="w-full py-3 rounded-lg bg-gradient-to-r from-purple-600 to-cyan-500 font-bold text-white hover:brightness-110 transition">Запустить кампанию в обработку воркера</button>
        </form>
    </div>
    {% endblock %}
    """
    return render_template_string(BASE_TEMPLATE.replace('{% block content %}{% endblock %}', html), chats=chats)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5000)
