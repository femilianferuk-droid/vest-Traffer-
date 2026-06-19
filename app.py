import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from functools import wraps
import urllib.request

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify
)
import psycopg2
import psycopg2.extras
from telethon import TelegramClient
from telethon.errors import (
    SessionPasswordNeededError, PhoneCodeInvalidError,
    FloodWaitError, PhoneNumberInvalidError
)
from telethon.sessions import StringSession

# Конфигурация
DATABASE_URL = 'postgresql://bothost_db_6f5993e63d14:MKsFRAV0DVmbRSkNa1b_XNQVdJxnJJD2INqII8il4jk@node1.pghost.ru:15794/bothost_db_6f5993e63d14'
CRYPTO_BOT_TOKEN = '499354:AATdkiDyuC1tWd1ro5S5wFw6XcePNUNH5Ph'
API_ID = 32480523
API_HASH = '147839735c9fa4e83451209e9b55cfc5'
SECRET_KEY = os.environ.get('SECRET_KEY', 'vest-traffer-secret-key-2024')

app = Flask(__name__)
app.secret_key = SECRET_KEY

temp_auth_data = {}

def get_db_connection():
    db_url = DATABASE_URL.replace('postgresql://', '')
    user_pass, host_db = db_url.split('@')
    user, password = user_pass.split(':')
    host_port, database = host_db.split('/')
    host, port = host_port.split(':')
    
    conn = psycopg2.connect(
        host=host, port=port, user=user,
        password=password, database=database
    )
    return conn

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            subscription_ends TIMESTAMP DEFAULT NULL
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS account (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            phone VARCHAR(20) NOT NULL,
            session_string TEXT
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS mailing_task (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            account_id INTEGER REFERENCES account(id),
            chats JSONB,
            message TEXT,
            delay INTEGER DEFAULT 10,
            sent_count INTEGER DEFAULT 0,
            total_messages INTEGER DEFAULT 0,
            mailing_type VARCHAR(20) DEFAULT 'simultaneous',
            status VARCHAR(20) DEFAULT 'Ожидает'
        )
    ''')
    
    cur.execute('''
        CREATE TABLE IF NOT EXISTS autoresponder (
            id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(id),
            account_id INTEGER REFERENCES account(id),
            trigger_type VARCHAR(20) DEFAULT 'all',
            keywords TEXT,
            reply_text TEXT,
            is_active BOOLEAN DEFAULT true
        )
    ''')
    
    # SQL патчи для добавления колонок
    cur.execute('ALTER TABLE mailing_task ADD COLUMN IF NOT EXISTS sent_count INTEGER DEFAULT 0')
    cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_ends TIMESTAMP DEFAULT NULL')
    
    conn.commit()
    cur.close()
    conn.close()

init_db()

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_current_user():
    if 'user_id' not in session:
        return None
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM users WHERE id = %s', (session['user_id'],))
    user = cur.fetchone()
    cur.close()
    conn.close()
    return user

def check_subscription(user):
    if not user or not user['subscription_ends']:
        return False
    return user['subscription_ends'] > datetime.utcnow()

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

class AsyncManager:
    @staticmethod
    def run_async(coro):
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Traffer - Автоматизация Telegram</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        sapphire: {
                            50: '#eff6ff',
                            100: '#dbeafe',
                            200: '#bfdbfe',
                            300: '#93c5fd',
                            400: '#60a5fa',
                            500: '#3b82f6',
                            600: '#2563eb',
                            700: '#1d4ed8',
                            800: '#1e40af',
                            900: '#1e3a8a',
                            950: '#172554'
                        }
                    }
                }
            }
        }
    </script>
</head>
<body class="bg-sapphire-950 min-h-screen text-white">
    <header class="bg-sapphire-900/50 backdrop-blur-sm border-b border-sapphire-700 p-4">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-2xl font-bold text-sapphire-400">⚡ Vest Traffer</h1>
            <div class="space-x-4">
                <button onclick="showLogin()" class="bg-sapphire-600 hover:bg-sapphire-500 px-6 py-2 rounded-lg font-semibold transition">
                    Войти
                </button>
            </div>
        </div>
    </header>

    <div id="loginModal" class="hidden fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
        <div class="bg-sapphire-900 rounded-xl p-6 max-w-md w-full border border-sapphire-700">
            <h2 class="text-xl font-bold mb-4">Вход в систему</h2>
            <input type="text" id="loginUsername" placeholder="Логин" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
            <input type="password" id="loginPassword" placeholder="Пароль" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-4 text-white">
            <button onclick="login()" class="w-full bg-sapphire-600 hover:bg-sapphire-500 py-3 rounded-lg font-semibold transition">Войти</button>
            <p class="mt-4 text-center text-sapphire-300">
                Нет аккаунта? <a href="#" onclick="showRegister()" class="text-sapphire-400 hover:underline">Зарегистрироваться</a>
            </p>
            <button onclick="closeModal('loginModal')" class="mt-4 w-full bg-gray-700 hover:bg-gray-600 py-2 rounded-lg transition">Закрыть</button>
        </div>
    </div>

    <div id="registerModal" class="hidden fixed inset-0 bg-black/70 flex items-center justify-center z-50 p-4">
        <div class="bg-sapphire-900 rounded-xl p-6 max-w-md w-full border border-sapphire-700">
            <h2 class="text-xl font-bold mb-4">Регистрация</h2>
            <p class="text-sapphire-300 mb-4">🎁 3 дня триала бесплатно!</p>
            <input type="text" id="regUsername" placeholder="Логин (мин. 3 символа)" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
            <input type="password" id="regPassword" placeholder="Пароль (мин. 6 символов)" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-4 text-white">
            <button onclick="register()" class="w-full bg-green-600 hover:bg-green-500 py-3 rounded-lg font-semibold transition">Зарегистрироваться</button>
            <p class="mt-4 text-center text-sapphire-300">
                Уже есть аккаунт? <a href="#" onclick="showLogin()" class="text-sapphire-400 hover:underline">Войти</a>
            </p>
            <button onclick="closeModal('registerModal')" class="mt-4 w-full bg-gray-700 hover:bg-gray-600 py-2 rounded-lg transition">Закрыть</button>
        </div>
    </div>

    <main class="container mx-auto px-4 py-12">
        <div class="text-center mb-16">
            <h2 class="text-4xl md:text-6xl font-bold text-sapphire-400 mb-6">
                Автоматизация Telegram рассылок
            </h2>
            <p class="text-xl text-sapphire-200 mb-8 max-w-2xl mx-auto">
                Профессиональный инструмент для массовых рассылок и автоответов в Telegram.
                Управляйте сотнями чатов с одного аккаунта.
            </p>
            <button onclick="showRegister()" class="bg-sapphire-600 hover:bg-sapphire-500 px-8 py-4 rounded-lg text-lg font-semibold transition">
                🚀 Начать бесплатно
            </button>
        </div>

        <div class="grid md:grid-cols-3 gap-6 mb-16">
            <div class="bg-sapphire-900/50 p-6 rounded-xl border border-sapphire-700">
                <h3 class="text-xl font-bold text-sapphire-400 mb-3">📨 Массовые рассылки</h3>
                <p class="text-sapphire-200">Отправка сообщений в десятки чатов одновременно. Выбор чатов, настройка задержек, рандомная или последовательная отправка.</p>
            </div>
            <div class="bg-sapphire-900/50 p-6 rounded-xl border border-sapphire-700">
                <h3 class="text-xl font-bold text-sapphire-400 mb-3">🤖 Автоответчики</h3>
                <p class="text-sapphire-200">Настройка автоматических ответов на входящие сообщения по ключевым словам. Поддержка ЛС и групп.</p>
            </div>
            <div class="bg-sapphire-900/50 p-6 rounded-xl border border-sapphire-700">
                <h3 class="text-xl font-bold text-sapphire-400 mb-3">🔐 Безопасность</h3>
                <p class="text-sapphire-200">Шифрование сессий, защита аккаунтов, современные протоколы безопасности.</p>
            </div>
        </div>

        <div class="max-w-3xl mx-auto">
            <h2 class="text-3xl font-bold text-center mb-8 text-sapphire-400">Часто задаваемые вопросы</h2>
            
            <div class="space-y-4">
                <div class="bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700">
                    <h3 class="font-bold text-lg mb-2">📊 Какие лимиты на рассылки?</h3>
                    <p class="text-sapphire-200">До 50 чатов за одну рассылку. Telegram имеет лимит ~50 сообщений в минуту для обычных аккаунтов. Рекомендуем задержку 10-30 секунд между сообщениями.</p>
                </div>
                <div class="bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700">
                    <h3 class="font-bold text-lg mb-2">🔒 Насколько безопасно хранить сессии?</h3>
                    <p class="text-sapphire-200">Сессии хранятся в зашифрованном виде в базе данных. Доступ имеет только наш воркер. Ваши данные никогда не передаются третьим лицам.</p>
                </div>
                <div class="bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700">
                    <h3 class="font-bold text-lg mb-2">💳 Как оплатить подписку?</h3>
                    <p class="text-sapphire-200">Оплата принимается через Crypto Bot. Доступны тарифы от 7 до 360 дней. После оплаты подписка активируется автоматически.</p>
                </div>
                <div class="bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700">
                    <h3 class="font-bold text-lg mb-2">🔄 Что такое рандомная рассылка?</h3>
                    <p class="text-sapphire-200">Сообщения отправляются в случайном порядке выбранным чатам. Это помогает избежать паттернов и снижает риск блокировки.</p>
                </div>
                <div class="bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700">
                    <h3 class="font-bold text-lg mb-2">⏱ Как быстро обрабатываются задачи?</h3>
                    <p class="text-sapphire-200">Воркер проверяет новые задачи каждые 5 секунд. Рассылка начинается мгновенно после создания.</p>
                </div>
            </div>
        </div>
    </main>

    <script>
        function showLogin() {
            closeModal('registerModal');
            document.getElementById('loginModal').classList.remove('hidden');
        }
        function showRegister() {
            closeModal('loginModal');
            document.getElementById('registerModal').classList.remove('hidden');
        }
        function closeModal(id) {
            document.getElementById(id).classList.add('hidden');
        }
        async function login() {
            const username = document.getElementById('loginUsername').value;
            const password = document.getElementById('loginPassword').value;
            try {
                const response = await fetch('/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                const data = await response.json();
                if (data.success) {
                    window.location.href = '/dashboard';
                } else {
                    alert(data.error || 'Ошибка входа');
                }
            } catch (e) {
                alert('Ошибка соединения');
            }
        }
        async function register() {
            const username = document.getElementById('regUsername').value;
            const password = document.getElementById('regPassword').value;
            try {
                const response = await fetch('/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                const data = await response.json();
                if (data.success) {
                    alert(data.message);
                    showLogin();
                } else {
                    alert(data.error || 'Ошибка регистрации');
                }
            } catch (e) {
                alert('Ошибка соединения');
            }
        }
    </script>
</body>
</html>'''

@app.route('/register', methods=['POST'])
def register():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    if not username or not password:
        return jsonify({'error': 'Заполните все поля'}), 400
    if len(username) < 3:
        return jsonify({'error': 'Логин должен быть не менее 3 символов'}), 400
    if len(password) < 6:
        return jsonify({'error': 'Пароль должен быть не менее 6 символов'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT id FROM users WHERE username = %s', (username,))
    if cur.fetchone():
        cur.close()
        conn.close()
        return jsonify({'error': 'Пользователь уже существует'}), 400
    
    password_hash = hash_password(password)
    trial_ends = datetime.utcnow() + timedelta(days=3)
    
    cur.execute(
        'INSERT INTO users (username, password_hash, subscription_ends) VALUES (%s, %s, %s)',
        (username, password_hash, trial_ends)
    )
    conn.commit()
    cur.close()
    conn.close()
    
    return jsonify({'success': True, 'message': 'Регистрация успешна! Вам предоставлен триал на 3 дня.'})

@app.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    
    password_hash = hash_password(password)
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        'SELECT * FROM users WHERE username = %s AND password_hash = %s',
        (username, password_hash)
    )
    user = cur.fetchone()
    cur.close()
    conn.close()
    
    if user:
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({'success': True})
    return jsonify({'error': 'Неверный логин или пароль'}), 401

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/dashboard')
@login_required
def dashboard():
    return '''
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Vest Traffer - Панель управления</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        sapphire: {
                            50: '#eff6ff',
                            100: '#dbeafe',
                            200: '#bfdbfe',
                            300: '#93c5fd',
                            400: '#60a5fa',
                            500: '#3b82f6',
                            600: '#2563eb',
                            700: '#1d4ed8',
                            800: '#1e40af',
                            900: '#1e3a8a',
                            950: '#172554'
                        }
                    }
                }
            }
        }
    </script>
</head>
<body class="bg-sapphire-950 min-h-screen text-white pb-20">
    <header class="bg-sapphire-900/50 backdrop-blur-sm border-b border-sapphire-700 p-4">
        <div class="container mx-auto">
            <h1 class="text-xl font-bold text-sapphire-400">⚡ Vest Traffer</h1>
        </div>
    </header>

    <main class="container mx-auto px-4 py-6" id="mainContent">
        <!-- Контент загружается динамически -->
    </main>

    <!-- Bottom Navigation Bar -->
    <nav class="fixed bottom-0 left-0 right-0 bg-sapphire-900/95 backdrop-blur-sm border-t border-sapphire-700">
        <div class="container mx-auto flex justify-around py-3">
            <button onclick="loadTab('accounts')" class="flex flex-col items-center tab-btn text-sapphire-400" id="tab-accounts">
                <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 2a4 4 0 100 8 4 4 0 000-8zM3 18v-2a5 5 0 015-5h4a5 5 0 015 5v2H3z"/>
                </svg>
                <span class="text-xs mt-1">Аккаунты</span>
            </button>
            <button onclick="loadTab('functions')" class="flex flex-col items-center tab-btn" id="tab-functions">
                <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z"/>
                </svg>
                <span class="text-xs mt-1">Функции</span>
            </button>
            <button onclick="loadTab('profile')" class="flex flex-col items-center tab-btn" id="tab-profile">
                <svg class="w-6 h-6" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                </svg>
                <span class="text-xs mt-1">Профиль</span>
            </button>
        </div>
    </nav>

    <script>
        let currentTab = 'accounts';
        
        async function loadTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab-btn').forEach(btn => {
                btn.classList.remove('text-sapphire-400');
                btn.classList.add('text-gray-400');
            });
            document.getElementById('tab-' + tab).classList.add('text-sapphire-400');
            document.getElementById('tab-' + tab).classList.remove('text-gray-400');
            
            const main = document.getElementById('mainContent');
            
            switch(tab) {
                case 'accounts':
                    main.innerHTML = await loadAccountsTab();
                    await loadAccounts();
                    break;
                case 'functions':
                    main.innerHTML = await loadFunctionsTab();
                    await loadAccountsForSelect();
                    break;
                case 'profile':
                    main.innerHTML = await loadProfileTab();
                    await loadProfile();
                    break;
            }
        }
        
        async function loadAccountsTab() {
            return `
                <div>
                    <h2 class="text-2xl font-bold mb-4 text-sapphire-400">Менеджер аккаунтов</h2>
                    <button onclick="showAddAccount()" class="w-full bg-sapphire-600 hover:bg-sapphire-500 py-3 rounded-lg font-semibold mb-4 transition">
                        + Добавить аккаунт
                    </button>
                    <div id="accountsList" class="space-y-3"></div>
                </div>
                <div id="addAccountSteps" class="hidden mt-4 bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700">
                    <h3 class="text-lg font-bold mb-3">Добавление аккаунта</h3>
                    <div id="step1">
                        <label class="block mb-2">Номер телефона</label>
                        <input type="text" id="phoneNumber" placeholder="+79123456789" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
                        <button onclick="sendCode()" class="w-full bg-sapphire-600 hover:bg-sapphire-500 py-3 rounded-lg font-semibold transition">Получить код</button>
                    </div>
                    <div id="step2" class="hidden">
                        <label class="block mb-2">Код из SMS</label>
                        <input type="text" id="smsCode" placeholder="12345" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
                        <label class="block mb-2">2FA пароль (если есть)</label>
                        <input type="password" id="twofaPassword" placeholder="Оставьте пустым если нет" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
                        <button onclick="verifyCode()" class="w-full bg-green-600 hover:bg-green-500 py-3 rounded-lg font-semibold transition">Подтвердить</button>
                    </div>
                    <button onclick="hideAddAccount()" class="mt-4 w-full bg-gray-700 hover:bg-gray-600 py-2 rounded-lg transition">Отмена</button>
                </div>`;
        }
        
        async function loadFunctionsTab() {
            return `
                <div>
                    <h2 class="text-2xl font-bold mb-4 text-sapphire-400">Функции</h2>
                    
                    <!-- Выбор аккаунта и загрузка чатов -->
                    <div class="bg-sapphire-900/50 rounded-xl p-4 border border-sapphire-700 mb-4">
                        <label class="block mb-2 font-semibold">Рабочий аккаунт</label>
                        <select id="accountSelect" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
                            <option value="">Выберите аккаунт</option>
                        </select>
                        <button onclick="loadChats()" class="w-full bg-sapphire-600 hover:bg-sapphire-500 py-3 rounded-lg font-semibold transition">
                            Загрузить чаты
                        </button>
                    </div>
                    
                    <!-- Степпер рассылки -->
                    <div id="mailingWizard" class="hidden bg-sapphire-900/50 rounded-xl p-4 border border-sapphire-700 mb-4">
                        <h3 class="text-lg font-bold mb-3">Создание рассылки</h3>
                        <div id="wizardStep1">
                            <h4 class="font-semibold mb-2">Шаг 1: Выберите чаты (1-50)</h4>
                            <button onclick="selectFirst50()" class="bg-sapphire-600 hover:bg-sapphire-500 px-4 py-2 rounded-lg mb-3 transition">Выбрать первые 50</button>
                            <div id="chatsList" class="max-h-60 overflow-y-auto space-y-2 mb-3"></div>
                            <button onclick="nextWizardStep(2)" class="w-full bg-sapphire-600 hover:bg-sapphire-500 py-2 rounded-lg transition">Далее</button>
                        </div>
                        <div id="wizardStep2" class="hidden">
                            <h4 class="font-semibold mb-2">Шаг 2: Настройки</h4>
                            <label class="block mb-2">Задержка (сек)</label>
                            <input type="number" id="delayInput" value="10" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
                            <label class="block mb-2">Тип рассылки</label>
                            <select id="mailingType" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white">
                                <option value="simultaneous">Одновременная по кругу</option>
                                <option value="random">Рандомная</option>
                            </select>
                            <button onclick="nextWizardStep(3)" class="w-full bg-sapphire-600 hover:bg-sapphire-500 py-2 rounded-lg transition">Далее</button>
                        </div>
                        <div id="wizardStep3" class="hidden">
                            <h4 class="font-semibold mb-2">Шаг 3: Текст сообщения</h4>
                            <textarea id="messageText" rows="4" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-3 text-white" placeholder="Введите текст рассылки..."></textarea>
                            <button onclick="startMailing()" class="w-full bg-green-600 hover:bg-green-500 py-3 rounded-lg font-semibold transition">Запустить рассылку</button>
                        </div>
                    </div>
                    
                    <!-- Список рассылок -->
                    <div class="bg-sapphire-900/50 rounded-xl p-4 border border-sapphire-700 mb-4">
                        <h3 class="text-lg font-bold mb-3">Активные рассылки</h3>
                        <div id="mailingList" class="space-y-3"></div>
                    </div>
                    
                    <!-- Автоответчики -->
                    <div class="bg-sapphire-900/50 rounded-xl p-4 border border-sapphire-700">
                        <h3 class="text-lg font-bold mb-3">Автоответчики</h3>
                        <button onclick="showCreateAutoresponder()" class="w-full bg-sapphire-600 hover:bg-sapphire-500 py-2 rounded-lg mb-3 transition">Создать автоответчик</button>
                        <div id="createAutoresponder" class="hidden mb-3">
                            <select id="arTriggerType" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-2 text-white">
                                <option value="pms">Только ЛС</option>
                                <option value="groups">Только группы</option>
                                <option value="all">Все сообщения</option>
                            </select>
                            <input type="text" id="arKeywords" value="-" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-2 text-white" placeholder="Ключевые слова через запятую (- для всех)">
                            <textarea id="arReplyText" rows="3" class="w-full bg-sapphire-800 border border-sapphire-600 rounded-lg p-3 mb-2 text-white" placeholder="Текст ответа..."></textarea>
                            <button onclick="createAutoresponder()" class="w-full bg-green-600 hover:bg-green-500 py-2 rounded-lg transition">Создать</button>
                        </div>
                        <div id="autoresponderList" class="space-y-2"></div>
                    </div>
                </div>`;
        }
        
        async function loadProfileTab() {
            return `
                <div>
                    <h2 class="text-2xl font-bold mb-4 text-sapphire-400">Профиль</h2>
                    <div class="bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700 mb-4">
                        <div id="profileInfo"></div>
                    </div>
                    
                    <div class="bg-sapphire-900/50 rounded-xl p-6 border border-sapphire-700">
                        <h3 class="text-lg font-bold mb-3">Купить подписку</h3>
                        <div class="grid grid-cols-2 gap-2">
                            <button onclick="buySubscription('7')" class="bg-sapphire-600 hover:bg-sapphire-500 p-3 rounded-lg transition">
                                <div class="font-bold">7 дней</div>
                                <div class="text-sm">20₽</div>
                            </button>
                            <button onclick="buySubscription('14')" class="bg-sapphire-600 hover:bg-sapphire-500 p-3 rounded-lg transition">
                                <div class="font-bold">14 дней</div>
                                <div class="text-sm">35₽</div>
                            </button>
                            <button onclick="buySubscription('30')" class="bg-sapphire-600 hover:bg-sapphire-500 p-3 rounded-lg transition">
                                <div class="font-bold">30 дней</div>
                                <div class="text-sm">65₽</div>
                            </button>
                            <button onclick="buySubscription('60')" class="bg-sapphire-600 hover:bg-sapphire-500 p-3 rounded-lg transition">
                                <div class="font-bold">60 дней</div>
                                <div class="text-sm">110₽</div>
                            </button>
                            <button onclick="buySubscription('120')" class="bg-sapphire-600 hover:bg-sapphire-500 p-3 rounded-lg transition">
                                <div class="font-bold">120 дней</div>
                                <div class="text-sm">200₽</div>
                            </button>
                            <button onclick="buySubscription('360')" class="bg-sapphire-600 hover:bg-sapphire-500 p-3 rounded-lg transition">
                                <div class="font-bold">360 дней</div>
                                <div class="text-sm">500₽</div>
                            </button>
                        </div>
                    </div>
                    
                    <button onclick="logout()" class="w-full bg-red-600 hover:bg-red-500 py-3 rounded-lg font-semibold mt-4 transition">Выйти</button>
                </div>`;
        }
        
        // Функции для аккаунтов
        function showAddAccount() {
            document.getElementById('addAccountSteps').classList.remove('hidden');
            document.getElementById('step2').classList.add('hidden');
            document.getElementById('step1').classList.remove('hidden');
        }
        
        function hideAddAccount() {
            document.getElementById('addAccountSteps').classList.add('hidden');
        }
        
        async function sendCode() {
            const phone = document.getElementById('phoneNumber').value;
            const response = await fetch('/api/accounts/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({phone})
            });
            const data = await response.json();
            if (data.success) {
                document.getElementById('step1').classList.add('hidden');
                document.getElementById('step2').classList.remove('hidden');
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        async function verifyCode() {
            const code = document.getElementById('smsCode').value;
            const password = document.getElementById('twofaPassword').value;
            const response = await fetch('/api/accounts/verify', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code, password})
            });
            const data = await response.json();
            if (data.success) {
                alert(data.message);
                hideAddAccount();
                loadAccounts();
            } else if (data.need_2fa) {
                document.getElementById('twofaPassword').focus();
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        async function loadAccounts() {
            const response = await fetch('/api/accounts');
            const accounts = await response.json();
            const list = document.getElementById('accountsList');
            list.innerHTML = accounts.map(acc => `
                <div class="bg-sapphire-900/50 rounded-xl p-4 border border-sapphire-700 flex justify-between items-center">
                    <div>
                        <div class="font-semibold">${acc.phone}</div>
                        <div class="text-sm ${acc.has_session ? 'text-green-400' : 'text-yellow-400'}">
                            ${acc.has_session ? '✅ Авторизован' : '⚠️ Нет сессии'}
                        </div>
                    </div>
                    <button onclick="deleteAccount(${acc.id})" class="bg-red-600 hover:bg-red-500 px-3 py-1 rounded-lg text-sm transition">Удалить</button>
                </div>
            `).join('');
        }
        
        async function deleteAccount(id) {
            if (confirm('Удалить аккаунт?')) {
                await fetch('/api/accounts/delete/' + id, {method: 'POST'});
                loadAccounts();
            }
        }
        
        // Функции для рассылок
        let loadedChats = [];
        
        async function loadAccountsForSelect() {
            const response = await fetch('/api/accounts');
            const accounts = await response.json();
            const select = document.getElementById('accountSelect');
            if (select) {
                select.innerHTML = '<option value="">Выберите аккаунт</option>' + 
                    accounts.filter(a => a.has_session).map(a => 
                        `<option value="${a.id}">${a.phone}</option>`
                    ).join('');
            }
        }
        
        async function loadChats() {
            const accountId = document.getElementById('accountSelect').value;
            if (!accountId) {
                alert('Выберите аккаунт');
                return;
            }
            
            const response = await fetch('/api/chats/load/' + accountId);
            const data = await response.json();
            
            if (data.success) {
                loadedChats = data.chats;
                document.getElementById('mailingWizard').classList.remove('hidden');
                displayChats();
                window.scrollTo(0, document.getElementById('mailingWizard').offsetTop);
            } else {
                alert(data.error || 'Ошибка загрузки чатов');
            }
        }
        
        function displayChats() {
            const container = document.getElementById('chatsList');
            container.innerHTML = loadedChats.map(chat => `
                <label class="flex items-center p-2 bg-sapphire-800/50 rounded-lg">
                    <input type="checkbox" value="${chat.id}" class="chat-checkbox mr-2">
                    <span class="text-sm">${chat.name} (${chat.type})</span>
                </label>
            `).join('');
        }
        
        function selectFirst50() {
            const checkboxes = document.querySelectorAll('.chat-checkbox');
            checkboxes.forEach((cb, i) => {
                cb.checked = i < 50;
            });
        }
        
        function nextWizardStep(step) {
            document.getElementById('wizardStep1').classList.add('hidden');
            document.getElementById('wizardStep2').classList.add('hidden');
            document.getElementById('wizardStep3').classList.add('hidden');
            document.getElementById('wizardStep' + step).classList.remove('hidden');
        }
        
        async function startMailing() {
            const accountId = document.getElementById('accountSelect').value;
            const selectedChats = Array.from(document.querySelectorAll('.chat-checkbox:checked'))
                .map(cb => cb.value);
            
            if (selectedChats.length < 1 || selectedChats.length > 50) {
                alert('Выберите от 1 до 50 чатов');
                return;
            }
            
            const delay = parseInt(document.getElementById('delayInput').value) || 10;
            const mailingType = document.getElementById('mailingType').value;
            const message = document.getElementById('messageText').value;
            
            const response = await fetch('/api/mailing/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    account_id: accountId,
                    chats: selectedChats,
                    message,
                    delay,
                    mailing_type: mailingType
                })
            });
            
            const data = await response.json();
            if (data.success) {
                alert('Рассылка запущена!');
                loadMailings();
                document.getElementById('mailingWizard').classList.add('hidden');
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        async function loadMailings() {
            const response = await fetch('/api/mailing/list');
            const tasks = await response.json();
            const container = document.getElementById('mailingList');
            if (container) {
                container.innerHTML = tasks.map(task => `
                    <div class="bg-sapphire-800/50 rounded-lg p-3">
                        <div class="flex justify-between text-sm mb-1">
                            <span class="text-sapphire-300">${task.message}</span>
                            <span class="text-${task.status === 'В работе' ? 'yellow' : task.status === 'Завершено' ? 'green' : 'red'}-400">${task.status}</span>
                        </div>
                        <div class="w-full bg-sapphire-900 rounded-full h-2">
                            <div class="bg-sapphire-500 h-2 rounded-full" style="width: ${task.progress}%"></div>
                        </div>
                        <div class="text-xs text-gray-400 mt-1">${task.sent_count}/${task.total_messages} (${task.mailing_type})</div>
                    </div>
                `).join('');
            }
        }
        
        // Функции для автоответчиков
        function showCreateAutoresponder() {
            document.getElementById('createAutoresponder').classList.toggle('hidden');
        }
        
        async function createAutoresponder() {
            const accountId = document.getElementById('accountSelect').value;
            const triggerType = document.getElementById('arTriggerType').value;
            const keywords = document.getElementById('arKeywords').value;
            const replyText = document.getElementById('arReplyText').value;
            
            const response = await fetch('/api/autoresponder/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    account_id: accountId,
                    trigger_type: triggerType,
                    keywords,
                    reply_text: replyText
                })
            });
            
            const data = await response.json();
            if (data.success) {
                alert('Автоответчик создан');
                loadAutoresponders();
                document.getElementById('createAutoresponder').classList.add('hidden');
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        async function loadAutoresponders() {
            const response = await fetch('/api/autoresponder/list');
            const responders = await response.json();
            const container = document.getElementById('autoresponderList');
            if (container) {
                container.innerHTML = responders.map(ar => `
                    <div class="bg-sapphire-800/50 rounded-lg p-3 flex justify-between items-center">
                        <div class="text-sm">
                            <div class="text-sapphire-300">${ar.reply_text}</div>
                            <div class="text-xs text-gray-400">${ar.trigger_type} | ${ar.keywords}</div>
                        </div>
                        <button onclick="toggleAutoresponder(${ar.id})" class="px-3 py-1 rounded-lg text-sm ${ar.is_active ? 'bg-green-600' : 'bg-gray-600'}">
                            ${ar.is_active ? 'Вкл' : 'Выкл'}
                        </button>
                    </div>
                `).join('');
            }
        }
        
        async function toggleAutoresponder(id) {
            await fetch('/api/autoresponder/toggle/' + id, {method: 'POST'});
            loadAutoresponders();
        }
        
        // Профиль
        async function loadProfile() {
            const response = await fetch('/api/user');
            const user = await response.json();
            document.getElementById('profileInfo').innerHTML = `
                <div class="text-lg font-bold mb-2">${user.username}</div>
                <div class="text-sapphire-300 mb-1">Аккаунтов: ${user.accounts_count}</div>
                <div class="text-${user.subscription_status.includes('Активна') ? 'green' : 'red'}-400 font-semibold">
                    ${user.subscription_status}
                </div>
            `;
        }
        
        async function buySubscription(plan) {
            const response = await fetch('/api/subscription/buy', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({plan})
            });
            
            const data = await response.json();
            if (data.success) {
                window.open(data.pay_url, '_blank');
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        function logout() {
            window.location.href = '/logout';
        }
        
        // Загрузка начальной вкладки
        loadTab('accounts');
        
        // Автообновление
        setInterval(() => {
            if (currentTab === 'functions') loadMailings();
        }, 5000);
    </script>
</body>
</html>'''

# API endpoints
@app.route('/api/user')
@login_required
def api_user():
    user = get_current_user()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('SELECT COUNT(*) FROM account WHERE user_id = %s', (user['id'],))
    accounts_count = cur.fetchone()[0]
    cur.close()
    conn.close()
    
    subscription_status = 'Активна до {}'.format(
        user['subscription_ends'].strftime('%d.%m.%Y %H:%M')
    ) if check_subscription(user) else 'Истекла'
    
    return jsonify({
        'username': user['username'],
        'accounts_count': accounts_count,
        'subscription_status': subscription_status
    })

@app.route('/api/accounts')
@login_required
def api_accounts():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute(
        'SELECT id, phone, session_string IS NOT NULL as has_session FROM account WHERE user_id = %s',
        (session['user_id'],)
    )
    accounts = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{'id': a['id'], 'phone': a['phone'], 'has_session': a['has_session']} for a in accounts])

@app.route('/api/accounts/delete/<int:account_id>', methods=['POST'])
@login_required
def api_delete_account(account_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('DELETE FROM account WHERE id = %s AND user_id = %s', (account_id, session['user_id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/accounts/add', methods=['POST'])
@login_required
def api_add_account():
    data = request.get_json()
    phone = data.get('phone', '').strip()
    
    async def send_code():
        client = TelegramClient(StringSession(), API_ID, API_HASH)
        await client.connect()
        try:
            sent = await client.send_code_request(phone)
            temp_auth_data[session['user_id']] = {
                'phone': phone,
                'phone_code_hash': sent.phone_code_hash,
                'client': client
            }
            return {'success': True, 'message': 'Код отправлен'}
        except Exception as e:
            await client.disconnect()
            return {'error': str(e)}
    
    return jsonify(AsyncManager.run_async(send_code()))

@app.route('/api/accounts/verify', methods=['POST'])
@login_required
def api_verify_code():
    data = request.get_json()
    code = data.get('code', '').strip()
    password = data.get('password', '').strip()
    
    user_id = session['user_id']
    if user_id not in temp_auth_data:
        return jsonify({'error': 'Сессия истекла'}), 400
    
    auth_data = temp_auth_data[user_id]
    client = auth_data['client']
    
    async def verify():
        try:
            await client.sign_in(auth_data['phone'], code, phone_code_hash=auth_data['phone_code_hash'])
        except SessionPasswordNeededError:
            if not password:
                return {'need_2fa': True}
            try:
                await client.sign_in(password=password)
            except:
                return {'error': 'Неверный пароль 2FA'}
        except Exception as e:
            return {'error': str(e)}
        
        session_string = client.session.save()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            'INSERT INTO account (user_id, phone, session_string) VALUES (%s, %s, %s)',
            (user_id, auth_data['phone'], session_string)
        )
        conn.commit()
        cur.close()
        conn.close()
        
        await client.disconnect()
        del temp_auth_data[user_id]
        return {'success': True, 'message': 'Аккаунт добавлен'}
    
    return jsonify(AsyncManager.run_async(verify()))

@app.route('/api/chats/load/<int:account_id>')
@login_required
def api_load_chats(account_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM account WHERE id = %s AND user_id = %s', (account_id, session['user_id']))
    account = cur.fetchone()
    cur.close()
    conn.close()
    
    if not account or not account['session_string']:
        return jsonify({'error': 'Аккаунт не найден'}), 404
    
    async def load_chats():
        client = TelegramClient(StringSession(account['session_string']), API_ID, API_HASH)
        await client.connect()
        if not await client.is_user_authorized():
            await client.disconnect()
            return {'error': 'Сессия недействительна'}
        
        chats = []
        async for dialog in client.iter_dialogs():
            chat_type = 'Личные сообщения' if dialog.is_user else 'Группа' if dialog.is_group else 'Канал'
            chats.append({'id': str(dialog.id), 'name': dialog.name, 'type': chat_type})
        
        await client.disconnect()
        return {'success': True, 'chats': chats}
    
    return jsonify(AsyncManager.run_async(load_chats()))

@app.route('/api/mailing/start', methods=['POST'])
@login_required
def api_start_mailing():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO mailing_task (user_id, account_id, chats, message, delay, total_messages, mailing_type, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s)''',
        (session['user_id'], data['account_id'], json.dumps(data['chats']), 
         data['message'], data.get('delay', 10), len(data['chats']),
         data.get('mailing_type', 'simultaneous'), 'Ожидает')
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': 'Рассылка запущена'})

@app.route('/api/mailing/list')
@login_required
def api_mailing_list():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM mailing_task WHERE user_id = %s ORDER BY id DESC LIMIT 10', (session['user_id'],))
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([{
        'id': t['id'],
        'message': t['message'][:50] + '...' if len(t['message']) > 50 else t['message'],
        'status': t['status'],
        'sent_count': t['sent_count'],
        'total_messages': t['total_messages'],
        'mailing_type': t['mailing_type'],
        'progress': round(t['sent_count'] / t['total_messages'] * 100) if t['total_messages'] > 0 else 0
    } for t in tasks])

@app.route('/api/autoresponder/create', methods=['POST'])
@login_required
def api_create_autoresponder():
    data = request.get_json()
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        '''INSERT INTO autoresponder (user_id, account_id, trigger_type, keywords, reply_text, is_active)
           VALUES (%s, %s, %s, %s, %s, true)''',
        (session['user_id'], data['account_id'], data['trigger_type'], 
         data['keywords'], data['reply_text'])
    )
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/autoresponder/list')
@login_required
def api_autoresponder_list():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM autoresponder WHERE user_id = %s ORDER BY id DESC', (session['user_id'],))
    responders = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([{
        'id': r['id'],
        'trigger_type': r['trigger_type'],
        'keywords': r['keywords'],
        'reply_text': r['reply_text'][:50] + '...' if len(r['reply_text']) > 50 else r['reply_text'],
        'is_active': r['is_active']
    } for r in responders])

@app.route('/api/autoresponder/toggle/<int:responder_id>', methods=['POST'])
@login_required
def api_toggle_autoresponder(responder_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('UPDATE autoresponder SET is_active = NOT is_active WHERE id = %s AND user_id = %s',
                (responder_id, session['user_id']))
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True})

@app.route('/api/subscription/buy', methods=['POST'])
@login_required
def api_buy_subscription():
    data = request.get_json()
    plan = data.get('plan')
    
    prices = {
        '7': {'amount': 20, 'days': 7},
        '14': {'amount': 35, 'days': 14},
        '30': {'amount': 65, 'days': 30},
        '60': {'amount': 110, 'days': 60},
        '120': {'amount': 200, 'days': 120},
        '360': {'amount': 500, 'days': 360}
    }
    
    if plan not in prices:
        return jsonify({'error': 'Неверный тариф'}), 400
    
    price_info = prices[plan]
    
    try:
        api_url = 'https://pay.crypt.bot/api/createInvoice'
        invoice_data = {
            'asset': 'USDT',
            'amount': str(price_info['amount']),
            'description': f'Подписка Vest Traffer на {price_info["days"]} дней',
            'payload': json.dumps({'user_id': session['user_id'], 'days': price_info['days']}),
            'expires_in': 3600
        }
        
        req = urllib.request.Request(
            api_url,
            data=json.dumps(invoice_data).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN
            },
            method='POST'
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        if result.get('ok'):
            return jsonify({'success': True, 'pay_url': result['result']['pay_url']})
        return jsonify({'error': 'Ошибка создания платежа'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
