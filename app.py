import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timedelta
from functools import wraps
import urllib.request
import urllib.error

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
    conn = psycopg2.connect(host=host, port=port, user=user, password=password, database=database)
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
            status VARCHAR(20) DEFAULT 'Ожидает',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            current_chat VARCHAR(255),
            errors JSONB DEFAULT '[]'
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
            is_active BOOLEAN DEFAULT true,
            response_count INTEGER DEFAULT 0,
            last_response TIMESTAMP
        )
    ''')
    
    cur.execute('ALTER TABLE mailing_task ADD COLUMN IF NOT EXISTS sent_count INTEGER DEFAULT 0')
    cur.execute('ALTER TABLE mailing_task ADD COLUMN IF NOT EXISTS current_chat VARCHAR(255)')
    cur.execute('ALTER TABLE mailing_task ADD COLUMN IF NOT EXISTS errors JSONB DEFAULT \'[]\'')
    cur.execute('ALTER TABLE mailing_task ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP')
    cur.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS subscription_ends TIMESTAMP DEFAULT NULL')
    cur.execute('ALTER TABLE autoresponder ADD COLUMN IF NOT EXISTS response_count INTEGER DEFAULT 0')
    cur.execute('ALTER TABLE autoresponder ADD COLUMN IF NOT EXISTS last_response TIMESTAMP')
    
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Vest Traffer - Автоматизация Telegram</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        
        * { font-family: 'Inter', sans-serif; }
        
        body {
            background: #000000;
            background-image: 
                radial-gradient(ellipse at top, rgba(59, 130, 246, 0.15), transparent 50%),
                radial-gradient(ellipse at bottom, rgba(37, 99, 235, 0.1), transparent 50%);
            min-height: 100vh;
        }
        
        .glass-effect {
            background: rgba(10, 15, 25, 0.75);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(59, 130, 246, 0.12);
        }
        
        .neon-border {
            border: 1px solid rgba(59, 130, 246, 0.25);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.08), inset 0 0 20px rgba(59, 130, 246, 0.03);
        }
        
        .glow-button {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
            border: 1px solid rgba(59, 130, 246, 0.5);
            position: relative;
            overflow: hidden;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            color: #e2e8f0;
            letter-spacing: 0.3px;
        }
        
        .glow-button::before {
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            background: linear-gradient(45deg,
                rgba(59, 130, 246, 0.6),
                rgba(255, 255, 255, 0.4),
                rgba(59, 130, 246, 0.6),
                rgba(147, 197, 253, 0.4));
            background-size: 400% 400%;
            animation: borderGlow 3s ease infinite;
            z-index: -1;
            border-radius: inherit;
            filter: blur(6px);
        }
        
        .glow-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(59, 130, 246, 0.3), 0 0 60px rgba(59, 130, 246, 0.1);
            border-color: rgba(59, 130, 246, 0.8);
        }
        
        .glow-button:active {
            transform: translateY(0px);
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2);
        }
        
        @keyframes borderGlow {
            0%, 100% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
        }
        
        .input-field {
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(59, 130, 246, 0.2);
            transition: all 0.3s ease;
            color: #e2e8f0;
        }
        
        .input-field:focus {
            border-color: rgba(59, 130, 246, 0.6);
            box-shadow: 0 0 25px rgba(59, 130, 246, 0.15), inset 0 0 10px rgba(59, 130, 246, 0.05);
            outline: none;
        }
        
        .input-field::placeholder {
            color: #64748b;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0px) rotate(0deg); }
            25% { transform: translateY(-12px) rotate(1deg); }
            75% { transform: translateY(-5px) rotate(-1deg); }
        }
        
        .float-animation {
            animation: float 5s ease-in-out infinite;
        }
        
        .gradient-text {
            background: linear-gradient(135deg, #3b82f6 0%, #60a5fa 30%, #93c5fd 60%, #60a5fa 100%);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            background-size: 200% auto;
            animation: gradientShift 4s linear infinite;
        }
        
        @keyframes gradientShift {
            0% { background-position: 0% center; }
            100% { background-position: 200% center; }
        }
        
        .card-hover {
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .card-hover:hover {
            transform: translateY(-6px);
            box-shadow: 0 20px 50px rgba(59, 130, 246, 0.15);
            border-color: rgba(59, 130, 246, 0.4);
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        @keyframes slideUp {
            from { transform: translateY(30px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        .modal-overlay {
            animation: fadeIn 0.25s ease;
        }
        
        .modal-content {
            animation: slideUp 0.3s ease;
        }
        
        @keyframes ping {
            75%, 100% { transform: scale(1.5); opacity: 0; }
        }
        
        .ping-animation {
            animation: ping 2s cubic-bezier(0, 0, 0.2, 1) infinite;
        }
    </style>
</head>
<body class="min-h-screen text-white">
    <header class="glass-effect p-4 sticky top-0 z-40">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-2xl md:text-3xl font-bold">
                <span class="gradient-text">Vest Traffer</span>
            </h1>
            <button onclick="showLogin()" class="glow-button px-6 md:px-8 py-2.5 md:py-3 rounded-xl font-semibold text-sm md:text-base relative">
                Войти
                <span class="absolute -top-1 -right-1 flex h-3 w-3">
                    <span class="animate-ping absolute inline-flex h-full w-full rounded-full bg-blue-400 opacity-75"></span>
                    <span class="relative inline-flex rounded-full h-3 w-3 bg-blue-500"></span>
                </span>
            </button>
        </div>
    </header>

    <div id="loginModal" class="hidden fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-4 modal-overlay">
        <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 max-w-md w-full modal-content">
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-xl md:text-2xl font-bold gradient-text">Вход в систему</h2>
                <button onclick="closeModal('loginModal')" class="text-gray-400 hover:text-white transition transform hover:rotate-90 duration-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            <input type="text" id="loginUsername" placeholder="Логин" class="input-field w-full rounded-xl p-3 md:p-4 mb-4 text-white placeholder-gray-500">
            <input type="password" id="loginPassword" placeholder="Пароль" class="input-field w-full rounded-xl p-3 md:p-4 mb-6 text-white placeholder-gray-500">
            <button onclick="login()" class="glow-button w-full py-3 md:py-4 rounded-xl font-semibold text-base md:text-lg">
                Войти
            </button>
            <p class="mt-6 text-center text-gray-400 text-sm md:text-base">
                Нет аккаунта?
                <a href="#" onclick="switchToRegister()" class="text-blue-400 hover:text-blue-300 transition ml-1">Зарегистрироваться</a>
            </p>
        </div>
    </div>

    <div id="registerModal" class="hidden fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-4 modal-overlay">
        <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 max-w-md w-full modal-content">
            <div class="flex justify-between items-center mb-6">
                <h2 class="text-xl md:text-2xl font-bold gradient-text">Регистрация</h2>
                <button onclick="closeModal('registerModal')" class="text-gray-400 hover:text-white transition transform hover:rotate-90 duration-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            <p class="text-center text-blue-400 mb-6 text-sm md:text-base">3 дня триала бесплатно!</p>
            <input type="text" id="regUsername" placeholder="Логин (мин. 3 символа)" class="input-field w-full rounded-xl p-3 md:p-4 mb-4 text-white placeholder-gray-500">
            <input type="password" id="regPassword" placeholder="Пароль (мин. 6 символов)" class="input-field w-full rounded-xl p-3 md:p-4 mb-6 text-white placeholder-gray-500">
            <button onclick="register()" class="glow-button w-full py-3 md:py-4 rounded-xl font-semibold text-base md:text-lg">
                Зарегистрироваться
            </button>
            <p class="mt-6 text-center text-gray-400 text-sm md:text-base">
                Уже есть аккаунт?
                <a href="#" onclick="switchToLogin()" class="text-blue-400 hover:text-blue-300 transition ml-1">Войти</a>
            </p>
        </div>
    </div>

    <main class="container mx-auto px-4 py-8 md:py-16">
        <div class="text-center mb-12 md:mb-20">
            <div class="float-animation mb-6 md:mb-8">
                <div class="w-20 h-20 md:w-24 md:h-24 mx-auto bg-gradient-to-br from-blue-600 via-blue-700 to-blue-900 rounded-2xl flex items-center justify-center neon-border">
                    <svg class="w-10 h-10 md:w-12 md:h-12 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M2 5a2 2 0 012-2h7a2 2 0 012 2v4a2 2 0 01-2 2H9l-3 3v-3H4a2 2 0 01-2-2V5z"/>
                        <path d="M15 7v2a4 4 0 01-4 4H9.828l-1.766 1.767c.28.149.599.233.938.233h2l3 3v-3h2a2 2 0 002-2V9a2 2 0 00-2-2h-1z"/>
                    </svg>
                </div>
            </div>
            <h2 class="text-3xl md:text-5xl lg:text-6xl font-bold mb-4 md:mb-6 px-2">
                <span class="gradient-text">Автоматизация Telegram</span>
            </h2>
            <p class="text-base md:text-lg lg:text-xl text-gray-400 mb-8 md:mb-10 max-w-xl md:max-w-2xl mx-auto px-4">
                Профессиональный инструмент для массовых рассылок и автоответов
            </p>
            <button onclick="showRegisterModal()" class="glow-button px-8 md:px-12 py-3.5 md:py-5 rounded-xl text-base md:text-lg lg:text-xl font-semibold">
                Начать бесплатно
            </button>
        </div>

        <div class="grid md:grid-cols-3 gap-4 md:gap-6 mb-16 md:mb-20">
            <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 card-hover">
                <div class="w-10 h-10 md:w-12 md:h-12 bg-gradient-to-br from-blue-600 to-blue-800 rounded-xl flex items-center justify-center mb-4">
                    <svg class="w-5 h-5 md:w-6 md:h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z"/>
                    </svg>
                </div>
                <h3 class="text-lg md:text-xl font-bold text-blue-400 mb-3">Массовые рассылки</h3>
                <p class="text-gray-400 text-sm md:text-base">Отправка сообщений в десятки чатов одновременно с настройкой задержек и типов рассылки</p>
            </div>

            <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 card-hover">
                <div class="w-10 h-10 md:w-12 md:h-12 bg-gradient-to-br from-blue-600 to-blue-800 rounded-xl flex items-center justify-center mb-4">
                    <svg class="w-5 h-5 md:w-6 md:h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                    </svg>
                </div>
                <h3 class="text-lg md:text-xl font-bold text-blue-400 mb-3">Автоответчики</h3>
                <p class="text-gray-400 text-sm md:text-base">Автоматические ответы по ключевым словам в личных сообщениях и группах</p>
            </div>

            <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 card-hover">
                <div class="w-10 h-10 md:w-12 md:h-12 bg-gradient-to-br from-blue-600 to-blue-800 rounded-xl flex items-center justify-center mb-4">
                    <svg class="w-5 h-5 md:w-6 md:h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/>
                    </svg>
                </div>
                <h3 class="text-lg md:text-xl font-bold text-blue-400 mb-3">Безопасность</h3>
                <p class="text-gray-400 text-sm md:text-base">Шифрование сессий и надёжная защита ваших аккаунтов Telegram</p>
            </div>
        </div>

        <div class="max-w-3xl mx-auto mb-16 md:mb-20">
            <h2 class="text-2xl md:text-3xl lg:text-4xl font-bold text-center mb-8 md:mb-12 gradient-text">
                Часто задаваемые вопросы
            </h2>
            <div class="space-y-3 md:space-y-4">
                <div class="glass-effect neon-border rounded-2xl p-5 md:p-6 card-hover">
                    <h3 class="text-base md:text-lg font-bold text-blue-400 mb-2">Какие лимиты на рассылки?</h3>
                    <p class="text-gray-400 text-sm md:text-base">До 50 чатов за одну рассылку. Рекомендуем задержку 10-30 секунд для избежания блокировок.</p>
                </div>
                <div class="glass-effect neon-border rounded-2xl p-5 md:p-6 card-hover">
                    <h3 class="text-base md:text-lg font-bold text-blue-400 mb-2">Безопасно ли хранить сессии?</h3>
                    <p class="text-gray-400 text-sm md:text-base">Сессии хранятся в зашифрованном виде в базе данных. Доступ имеет только наш воркер.</p>
                </div>
                <div class="glass-effect neon-border rounded-2xl p-5 md:p-6 card-hover">
                    <h3 class="text-base md:text-lg font-bold text-blue-400 mb-2">Как оплатить подписку?</h3>
                    <p class="text-gray-400 text-sm md:text-base">Оплата через Crypto Bot (USDT). Доступны тарифы от 7 до 360 дней.</p>
                </div>
                <div class="glass-effect neon-border rounded-2xl p-5 md:p-6 card-hover">
                    <h3 class="text-base md:text-lg font-bold text-blue-400 mb-2">Как работает рандомная рассылка?</h3>
                    <p class="text-gray-400 text-sm md:text-base">Сообщения отправляются в случайном порядке, что снижает риск блокировки.</p>
                </div>
                <div class="glass-effect neon-border rounded-2xl p-5 md:p-6 card-hover">
                    <h3 class="text-base md:text-lg font-bold text-blue-400 mb-2">Скорость обработки задач?</h3>
                    <p class="text-gray-400 text-sm md:text-base">Воркер проверяет новые задачи каждые 5 секунд. Рассылка стартует моментально.</p>
                </div>
            </div>
        </div>

        <footer class="text-center border-t border-blue-900/20 pt-8 pb-4">
            <div class="mb-4">
                <a href="https://t.me/VestTraffSupport" class="text-blue-400 hover:text-blue-300 transition text-sm md:text-base">
                    @VestTraffSupport
                </a>
            </div>
            <div class="text-gray-500 text-xs md:text-sm">
                Vest Traffer 2026
            </div>
        </footer>
    </main>

    <script>
        function showLogin() {
            document.getElementById('loginModal').classList.remove('hidden');
        }
        function showRegisterModal() {
            document.getElementById('registerModal').classList.remove('hidden');
        }
        function closeModal(id) {
            document.getElementById(id).classList.add('hidden');
        }
        function switchToRegister() {
            closeModal('loginModal');
            showRegisterModal();
        }
        function switchToLogin() {
            closeModal('registerModal');
            showLogin();
        }
        
        async function login() {
            const username = document.getElementById('loginUsername').value.trim();
            const password = document.getElementById('loginPassword').value.trim();
            if (!username || !password) { alert('Заполните все поля'); return; }
            
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
            const username = document.getElementById('regUsername').value.trim();
            const password = document.getElementById('regPassword').value.trim();
            if (!username || !password) { alert('Заполните все поля'); return; }
            if (username.length < 3) { alert('Логин должен быть не менее 3 символов'); return; }
            if (password.length < 6) { alert('Пароль должен быть не менее 6 символов'); return; }
            
            try {
                const response = await fetch('/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password})
                });
                const data = await response.json();
                if (data.success) {
                    alert(data.message);
                    switchToLogin();
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
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Vest Traffer - Панель управления</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&display=swap');
        
        * { font-family: 'Inter', sans-serif; }
        
        body {
            background: #000000;
            background-image: 
                radial-gradient(ellipse at top, rgba(59, 130, 246, 0.15), transparent 50%),
                radial-gradient(ellipse at bottom, rgba(37, 99, 235, 0.1), transparent 50%);
            min-height: 100vh;
        }
        
        .glass-effect {
            background: rgba(10, 15, 25, 0.75);
            backdrop-filter: blur(20px);
            -webkit-backdrop-filter: blur(20px);
            border: 1px solid rgba(59, 130, 246, 0.12);
        }
        
        .neon-border {
            border: 1px solid rgba(59, 130, 246, 0.25);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.08), inset 0 0 20px rgba(59, 130, 246, 0.03);
        }
        
        .glow-button {
            background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
            border: 1px solid rgba(59, 130, 246, 0.5);
            position: relative;
            overflow: hidden;
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            color: #e2e8f0;
            letter-spacing: 0.3px;
        }
        
        .glow-button::before {
            content: '';
            position: absolute;
            top: -2px;
            left: -2px;
            right: -2px;
            bottom: -2px;
            background: linear-gradient(45deg,
                rgba(59, 130, 246, 0.6),
                rgba(255, 255, 255, 0.4),
                rgba(59, 130, 246, 0.6),
                rgba(147, 197, 253, 0.4));
            background-size: 400% 400%;
            animation: borderGlow 3s ease infinite;
            z-index: -1;
            border-radius: inherit;
            filter: blur(6px);
        }
        
        .glow-button:hover {
            transform: translateY(-2px);
            box-shadow: 0 8px 30px rgba(59, 130, 246, 0.3), 0 0 60px rgba(59, 130, 246, 0.1);
            border-color: rgba(59, 130, 246, 0.8);
        }
        
        .glow-button:active {
            transform: translateY(0px);
            box-shadow: 0 4px 15px rgba(59, 130, 246, 0.2);
        }
        
        @keyframes borderGlow {
            0%, 100% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
        }
        
        .input-field {
            background: rgba(15, 23, 42, 0.9);
            border: 1px solid rgba(59, 130, 246, 0.2);
            transition: all 0.3s ease;
            color: #e2e8f0;
        }
        
        .input-field:focus {
            border-color: rgba(59, 130, 246, 0.6);
            box-shadow: 0 0 25px rgba(59, 130, 246, 0.15), inset 0 0 10px rgba(59, 130, 246, 0.05);
            outline: none;
        }
        
        .input-field::placeholder {
            color: #64748b;
        }
        
        .tab-button {
            position: relative;
            transition: all 0.3s ease;
        }
        
        .tab-button::after {
            content: '';
            position: absolute;
            bottom: -2px;
            left: 50%;
            transform: translateX(-50%);
            width: 0;
            height: 2px;
            background: linear-gradient(90deg, transparent, #3b82f6, #60a5fa, #3b82f6, transparent);
            transition: width 0.3s ease;
            border-radius: 2px;
        }
        
        .tab-button.active {
            color: #60a5fa;
        }
        
        .tab-button.active::after {
            width: 70%;
        }
        
        .progress-bar {
            background: linear-gradient(90deg, #1e3a8a, #3b82f6, #60a5fa, #3b82f6, #1e3a8a);
            background-size: 200% 100%;
            animation: shimmer 2.5s linear infinite;
            transition: width 0.5s ease;
            border-radius: 9999px;
        }
        
        @keyframes shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        
        @keyframes fadeIn {
            from { opacity: 0; }
            to { opacity: 1; }
        }
        
        @keyframes slideUp {
            from { transform: translateY(30px); opacity: 0; }
            to { transform: translateY(0); opacity: 1; }
        }
        
        .modal-overlay {
            animation: fadeIn 0.25s ease;
        }
        
        .modal-content {
            animation: slideUp 0.3s ease;
        }
        
        .gradient-text {
            background: linear-gradient(135deg, #3b82f6 0%, #60a5fa 30%, #93c5fd 60%, #60a5fa 100%);
            -webkit-background-clip: text;
            background-clip: text;
            -webkit-text-fill-color: transparent;
            background-size: 200% auto;
            animation: gradientShift 4s linear infinite;
        }
        
        @keyframes gradientShift {
            0% { background-position: 0% center; }
            100% { background-position: 200% center; }
        }
        
        .status-badge {
            font-size: 0.7rem;
            padding: 0.25rem 0.75rem;
            border-radius: 9999px;
            font-weight: 600;
            letter-spacing: 0.5px;
        }
        
        .scrollbar-thin::-webkit-scrollbar {
            width: 4px;
        }
        
        .scrollbar-thin::-webkit-scrollbar-track {
            background: rgba(15, 23, 42, 0.3);
            border-radius: 4px;
        }
        
        .scrollbar-thin::-webkit-scrollbar-thumb {
            background: rgba(59, 130, 246, 0.3);
            border-radius: 4px;
        }
        
        .animate-in {
            animation: slideUp 0.4s ease forwards;
        }
    </style>
</head>
<body class="text-white pb-24">
    <header class="glass-effect p-3 md:p-4 sticky top-0 z-40">
        <div class="container mx-auto">
            <h1 class="text-xl md:text-2xl font-bold gradient-text">Vest Traffer</h1>
        </div>
    </header>

    <main class="container mx-auto px-3 md:px-4 py-4 md:py-6" id="mainContent"></main>

    <nav class="fixed bottom-0 left-0 right-0 glass-effect border-t border-blue-900/30 z-40">
        <div class="container mx-auto flex justify-around py-2 md:py-3">
            <button onclick="loadTab('accounts')" class="tab-button flex flex-col items-center text-gray-400 transition pb-1" id="tab-accounts">
                <svg class="w-5 h-5 md:w-6 md:h-6 mb-1" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 2a4 4 0 100 8 4 4 0 000-8zM3 18v-2a5 5 0 015-5h4a5 5 0 015 5v2H3z"/>
                </svg>
                <span class="text-xs">Аккаунты</span>
            </button>
            <button onclick="loadTab('functions')" class="tab-button flex flex-col items-center text-gray-400 transition pb-1" id="tab-functions">
                <svg class="w-5 h-5 md:w-6 md:h-6 mb-1" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z"/>
                </svg>
                <span class="text-xs">Функции</span>
            </button>
            <button onclick="loadTab('profile')" class="tab-button flex flex-col items-center text-gray-400 transition pb-1" id="tab-profile">
                <svg class="w-5 h-5 md:w-6 md:h-6 mb-1" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                </svg>
                <span class="text-xs">Профиль</span>
            </button>
        </div>
    </nav>

    <div id="addAccountModal" class="hidden fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-4 modal-overlay">
        <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 max-w-md w-full modal-content">
            <div class="flex justify-between items-center mb-6">
                <h3 class="text-lg md:text-xl font-bold gradient-text">Добавление аккаунта</h3>
                <button onclick="closeAddAccountModal()" class="text-gray-400 hover:text-white transition transform hover:rotate-90 duration-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            <div id="addStep1">
                <label class="block mb-2 text-gray-300 text-sm md:text-base">Номер телефона</label>
                <input type="text" id="phoneNumber" placeholder="+79123456789" class="input-field w-full rounded-xl p-3 md:p-4 mb-4 text-white placeholder-gray-500">
                <button onclick="sendCode()" class="glow-button w-full py-3 md:py-4 rounded-xl font-semibold">Получить код</button>
            </div>
            <div id="addStep2" class="hidden">
                <label class="block mb-2 text-gray-300 text-sm md:text-base">Код из SMS</label>
                <input type="text" id="smsCode" placeholder="12345" class="input-field w-full rounded-xl p-3 md:p-4 mb-4 text-white placeholder-gray-500">
                <label class="block mb-2 text-gray-300 text-sm md:text-base">2FA пароль (если есть)</label>
                <input type="password" id="twofaPassword" placeholder="Оставьте пустым если нет" class="input-field w-full rounded-xl p-3 md:p-4 mb-4 text-white placeholder-gray-500">
                <button onclick="verifyCode()" class="glow-button w-full py-3 md:py-4 rounded-xl font-semibold">Подтвердить</button>
            </div>
        </div>
    </div>

    <div id="mailingDetailModal" class="hidden fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-4 modal-overlay">
        <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 max-w-2xl w-full max-h-[85vh] overflow-y-auto scrollbar-thin modal-content">
            <div class="flex justify-between items-center mb-6 sticky top-0 bg-black/50 backdrop-blur-sm p-2 rounded-xl z-10">
                <h3 class="text-lg md:text-xl font-bold gradient-text">Детали рассылки</h3>
                <button onclick="closeMailingDetail()" class="text-gray-400 hover:text-white transition transform hover:rotate-90 duration-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            <div id="mailingDetailContent"></div>
        </div>
    </div>

    <div id="buyModal" class="hidden fixed inset-0 bg-black/85 backdrop-blur-sm flex items-center justify-center z-50 p-4 modal-overlay">
        <div class="glass-effect neon-border rounded-2xl p-6 md:p-8 max-w-sm w-full modal-content">
            <div class="flex justify-between items-center mb-6">
                <h3 class="text-lg md:text-xl font-bold gradient-text">Выберите тариф</h3>
                <button onclick="closeBuyModal()" class="text-gray-400 hover:text-white transition transform hover:rotate-90 duration-300">
                    <svg class="w-6 h-6" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                    </svg>
                </button>
            </div>
            <div class="space-y-2 md:space-y-3">
                <button onclick="buySubscription('7')" class="glow-button w-full py-3 md:py-4 rounded-xl flex justify-between items-center px-4">
                    <span>7 дней</span>
                    <span class="font-bold text-blue-400">20₽</span>
                </button>
                <button onclick="buySubscription('14')" class="glow-button w-full py-3 md:py-4 rounded-xl flex justify-between items-center px-4">
                    <span>14 дней</span>
                    <span class="font-bold text-blue-400">35₽</span>
                </button>
                <button onclick="buySubscription('30')" class="glow-button w-full py-3 md:py-4 rounded-xl flex justify-between items-center px-4">
                    <span>30 дней</span>
                    <span class="font-bold text-blue-400">65₽</span>
                </button>
                <button onclick="buySubscription('60')" class="glow-button w-full py-3 md:py-4 rounded-xl flex justify-between items-center px-4">
                    <span>60 дней</span>
                    <span class="font-bold text-blue-400">110₽</span>
                </button>
                <button onclick="buySubscription('120')" class="glow-button w-full py-3 md:py-4 rounded-xl flex justify-between items-center px-4">
                    <span>120 дней</span>
                    <span class="font-bold text-blue-400">200₽</span>
                </button>
                <button onclick="buySubscription('360')" class="glow-button w-full py-3 md:py-4 rounded-xl flex justify-between items-center px-4">
                    <span>360 дней</span>
                    <span class="font-bold text-blue-400">500₽</span>
                </button>
            </div>
        </div>
    </div>

    <script>
        let currentTab = 'accounts';
        let currentFunction = 'mailing';
        let loadedChats = [];
        
        loadTab('accounts');
        
        async function loadTab(tab) {
            currentTab = tab;
            document.querySelectorAll('.tab-button').forEach(btn => btn.classList.remove('active'));
            document.getElementById('tab-' + tab).classList.add('active');
            
            const main = document.getElementById('mainContent');
            main.classList.remove('animate-in');
            void main.offsetWidth;
            main.classList.add('animate-in');
            
            switch(tab) {
                case 'accounts':
                    main.innerHTML = await getAccountsTabHTML();
                    await loadAccounts();
                    break;
                case 'functions':
                    main.innerHTML = await getFunctionsTabHTML();
                    await loadAccountsForSelect();
                    break;
                case 'profile':
                    main.innerHTML = await getProfileTabHTML();
                    await loadProfile();
                    break;
            }
        }
        
        async function getAccountsTabHTML() {
            return `
                <div>
                    <h2 class="text-xl md:text-2xl font-bold mb-4 md:mb-6 gradient-text">Менеджер аккаунтов</h2>
                    <button onclick="openAddAccountModal()" class="glow-button w-full py-3 md:py-4 rounded-xl font-semibold mb-6">
                        + Добавить аккаунт
                    </button>
                    <div id="accountsList" class="space-y-3"></div>
                </div>`;
        }
        
        async function getFunctionsTabHTML() {
            return `
                <div>
                    <h2 class="text-xl md:text-2xl font-bold mb-4 md:mb-6 gradient-text">Функции</h2>
                    <div class="flex gap-2 mb-6">
                        <button onclick="switchFunction('mailing')" id="btn-mailing" 
                                class="glow-button flex-1 py-3 rounded-xl font-semibold text-sm md:text-base">
                            Рассылка
                        </button>
                        <button onclick="switchFunction('autoresponder')" id="btn-autoresponder" 
                                class="flex-1 py-3 rounded-xl font-semibold text-sm md:text-base glass-effect">
                            Автоответчик
                        </button>
                    </div>
                    <div class="glass-effect neon-border rounded-2xl p-4 mb-4">
                        <label class="block mb-2 text-gray-300 text-sm md:text-base">Рабочий аккаунт</label>
                        <select id="accountSelect" class="input-field w-full rounded-xl p-3 text-white">
                            <option value="">Выберите аккаунт</option>
                        </select>
                    </div>
                    <div id="mailingSection">
                        <button onclick="toggleMailingCreate()" class="glow-button w-full py-3 md:py-4 rounded-xl font-semibold mb-4">
                            Создать рассылку
                        </button>
                        <div id="mailingCreateForm" class="hidden glass-effect neon-border rounded-2xl p-4 md:p-6 mb-4">
                            <h3 class="text-lg font-bold mb-4 text-blue-400">Новая рассылка</h3>
                            <button onclick="loadChats()" class="glow-button w-full py-3 rounded-xl mb-4">Загрузить чаты</button>
                            <div id="chatsList" class="max-h-48 overflow-y-auto space-y-2 mb-4 scrollbar-thin"></div>
                            <button onclick="selectFirst50()" class="text-blue-400 hover:text-blue-300 text-sm mb-4">Выбрать первые 50</button>
                            <div class="space-y-3">
                                <input type="number" id="delayInput" value="10" placeholder="Задержка (сек)" class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500">
                                <select id="mailingType" class="input-field w-full rounded-xl p-3 text-white">
                                    <option value="simultaneous">Одновременная по кругу</option>
                                    <option value="random">Рандомная</option>
                                </select>
                                <textarea id="messageText" rows="4" placeholder="Текст сообщения..." class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500"></textarea>
                                <button onclick="startMailing()" class="glow-button w-full py-3 rounded-xl font-semibold">Запустить рассылку</button>
                            </div>
                        </div>
                        <h3 class="text-lg font-bold mb-3 text-blue-400">Мои рассылки</h3>
                        <div id="mailingList" class="space-y-3"></div>
                    </div>
                    <div id="autoresponderSection" class="hidden">
                        <button onclick="toggleAutoresponderCreate()" class="glow-button w-full py-3 md:py-4 rounded-xl font-semibold mb-4">
                            Создать автоответчик
                        </button>
                        <div id="autoresponderCreateForm" class="hidden glass-effect neon-border rounded-2xl p-4 md:p-6 mb-4">
                            <h3 class="text-lg font-bold mb-4 text-blue-400">Новый автоответчик</h3>
                            <select id="arTriggerType" class="input-field w-full rounded-xl p-3 text-white mb-3">
                                <option value="pms">Только ЛС</option>
                                <option value="groups">Только группы</option>
                                <option value="all">Все сообщения</option>
                            </select>
                            <input type="text" id="arKeywords" value="-" placeholder="Ключевые слова (- для всех)" class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500 mb-3">
                            <textarea id="arReplyText" rows="4" placeholder="Текст ответа..." class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500 mb-3"></textarea>
                            <button onclick="createAutoresponder()" class="glow-button w-full py-3 rounded-xl font-semibold">Создать</button>
                        </div>
                        <h3 class="text-lg font-bold mb-3 text-blue-400">Мои автоответчики</h3>
                        <div id="autoresponderList" class="space-y-3"></div>
                    </div>
                </div>`;
        }
        
        async function getProfileTabHTML() {
            return `
                <div>
                    <h2 class="text-xl md:text-2xl font-bold mb-4 md:mb-6 gradient-text">Профиль</h2>
                    <div class="glass-effect neon-border rounded-2xl p-6 mb-6">
                        <div id="profileInfo" class="space-y-3"></div>
                    </div>
                    <button onclick="showBuyModal()" class="glow-button w-full py-4 rounded-xl font-semibold mb-4">
                        Купить подписку
                    </button>
                    <button onclick="logout()" class="w-full bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 py-4 rounded-xl font-semibold transition">
                        Выйти
                    </button>
                    <div class="mt-8 text-center">
                        <a href="https://t.me/VestTraffSupport" class="text-blue-400 hover:text-blue-300 transition text-sm md:text-base">
                            @VestTraffSupport
                        </a>
                        <div class="text-gray-500 text-xs md:text-sm mt-2">Vest Traffer 2026</div>
                    </div>
                </div>`;
        }
        
        function openAddAccountModal() {
            document.getElementById('addAccountModal').classList.remove('hidden');
            document.getElementById('addStep1').classList.remove('hidden');
            document.getElementById('addStep2').classList.add('hidden');
        }
        function closeAddAccountModal() {
            document.getElementById('addAccountModal').classList.add('hidden');
        }
        function closeMailingDetail() {
            document.getElementById('mailingDetailModal').classList.add('hidden');
        }
        function showBuyModal() {
            document.getElementById('buyModal').classList.remove('hidden');
        }
        function closeBuyModal() {
            document.getElementById('buyModal').classList.add('hidden');
        }
        
        function switchFunction(func) {
            currentFunction = func;
            document.getElementById('btn-mailing').className = func === 'mailing' ? 
                'glow-button flex-1 py-3 rounded-xl font-semibold text-sm md:text-base' : 
                'flex-1 py-3 rounded-xl font-semibold text-sm md:text-base glass-effect';
            document.getElementById('btn-autoresponder').className = func === 'autoresponder' ? 
                'glow-button flex-1 py-3 rounded-xl font-semibold text-sm md:text-base' : 
                'flex-1 py-3 rounded-xl font-semibold text-sm md:text-base glass-effect';
            document.getElementById('mailingSection').classList.toggle('hidden', func !== 'mailing');
            document.getElementById('autoresponderSection').classList.toggle('hidden', func !== 'autoresponder');
            if (func === 'mailing') loadMailings();
            if (func === 'autoresponder') loadAutoresponders();
        }
        
        async function sendCode() {
            const phone = document.getElementById('phoneNumber').value.trim();
            if (!phone) { alert('Введите номер телефона'); return; }
            const response = await fetch('/api/accounts/add', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({phone})
            });
            const data = await response.json();
            if (data.success) {
                document.getElementById('addStep1').classList.add('hidden');
                document.getElementById('addStep2').classList.remove('hidden');
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        async function verifyCode() {
            const code = document.getElementById('smsCode').value.trim();
            const password = document.getElementById('twofaPassword').value.trim();
            const response = await fetch('/api/accounts/verify', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({code, password})
            });
            const data = await response.json();
            if (data.success) {
                alert(data.message);
                closeAddAccountModal();
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
            document.getElementById('accountsList').innerHTML = accounts.length ? accounts.map(acc => `
                <div class="glass-effect neon-border rounded-xl p-4 flex justify-between items-center">
                    <div>
                        <div class="font-semibold text-sm md:text-base">${acc.phone}</div>
                        <div class="text-xs md:text-sm ${acc.has_session ? 'text-green-400' : 'text-yellow-400'}">
                            ${acc.has_session ? 'Авторизован' : 'Нет сессии'}
                        </div>
                    </div>
                    <button onclick="deleteAccount(${acc.id})" 
                            class="bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 px-3 md:px-4 py-2 rounded-xl text-xs md:text-sm transition">
                        Удалить
                    </button>
                </div>
            `).join('') : '<p class="text-gray-400 text-center py-8">Нет аккаунтов</p>';
        }
        
        async function deleteAccount(id) {
            if (confirm('Удалить аккаунт?')) {
                await fetch('/api/accounts/delete/' + id, {method: 'POST'});
                loadAccounts();
            }
        }
        
        async function loadAccountsForSelect() {
            const response = await fetch('/api/accounts');
            const accounts = await response.json();
            const select = document.getElementById('accountSelect');
            if (select) {
                select.innerHTML = '<option value="">Выберите аккаунт</option>' + 
                    accounts.filter(a => a.has_session).map(a => `<option value="${a.id}">${a.phone}</option>`).join('');
            }
        }
        
        function toggleMailingCreate() {
            document.getElementById('mailingCreateForm').classList.toggle('hidden');
        }
        
        async function loadChats() {
            const accountId = document.getElementById('accountSelect').value;
            if (!accountId) { alert('Выберите аккаунт'); return; }
            const response = await fetch('/api/chats/load/' + accountId);
            const data = await response.json();
            if (data.success) {
                loadedChats = data.chats;
                displayChats();
            } else {
                alert(data.error || 'Ошибка загрузки чатов');
            }
        }
        
        function displayChats() {
            document.getElementById('chatsList').innerHTML = loadedChats.map(chat => `
                <label class="flex items-center p-3 glass-effect rounded-xl cursor-pointer hover:border-blue-500/30 transition">
                    <input type="checkbox" value="${chat.id}" class="chat-checkbox mr-3">
                    <div>
                        <div class="text-sm">${chat.name}</div>
                        <div class="text-xs text-gray-500">${chat.type}</div>
                    </div>
                </label>
            `).join('');
        }
        
        function selectFirst50() {
            document.querySelectorAll('.chat-checkbox').forEach((cb, i) => cb.checked = i < 50);
        }
        
        async function startMailing() {
            const accountId = document.getElementById('accountSelect').value;
            const selectedChats = Array.from(document.querySelectorAll('.chat-checkbox:checked')).map(cb => cb.value);
            
            if (selectedChats.length < 1 || selectedChats.length > 50) {
                alert('Выберите от 1 до 50 чатов');
                return;
            }
            const message = document.getElementById('messageText').value.trim();
            if (!message) { alert('Введите текст сообщения'); return; }
            
            const response = await fetch('/api/mailing/start', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    account_id: accountId,
                    chats: selectedChats,
                    message,
                    delay: parseInt(document.getElementById('delayInput').value) || 10,
                    mailing_type: document.getElementById('mailingType').value
                })
            });
            
            const data = await response.json();
            if (data.success) {
                alert('Рассылка запущена!');
                loadMailings();
                toggleMailingCreate();
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        async function loadMailings() {
            const response = await fetch('/api/mailing/list');
            const tasks = await response.json();
            const container = document.getElementById('mailingList');
            if (container) {
                container.innerHTML = tasks.length ? tasks.map(task => `
                    <div class="glass-effect neon-border rounded-xl p-4 cursor-pointer hover:border-blue-500/40 transition" onclick="showMailingDetail(${task.id})">
                        <div class="flex justify-between items-start mb-2">
                            <div class="flex-1 mr-2">
                                <div class="text-sm font-semibold">${task.message}</div>
                                <div class="text-xs text-gray-500 mt-1">${task.mailing_type === 'random' ? 'Рандомная' : 'По кругу'} · Задержка ${task.delay || 10}с</div>
                            </div>
                            <span class="status-badge ${
                                task.status === 'В работе' ? 'bg-yellow-500/20 text-yellow-400 border border-yellow-500/30' : 
                                task.status === 'Завершено' ? 'bg-green-500/20 text-green-400 border border-green-500/30' :
                                task.status === 'Остановлено' ? 'bg-orange-500/20 text-orange-400 border border-orange-500/30' :
                                'bg-red-500/20 text-red-400 border border-red-500/30'
                            }">${task.status}</span>
                        </div>
                        <div class="w-full bg-gray-800/50 rounded-full h-2 mb-1">
                            <div class="progress-bar h-2 rounded-full" style="width: ${task.progress}%"></div>
                        </div>
                        <div class="text-xs text-gray-500">${task.sent_count}/${task.total_messages} (${task.progress}%)</div>
                    </div>
                `).join('') : '<p class="text-gray-400 text-center py-8">Нет рассылок</p>';
            }
        }
        
        async function showMailingDetail(taskId) {
            const response = await fetch('/api/mailing/detail/' + taskId);
            const task = await response.json();
            if (task.error) { alert(task.error); return; }
            
            document.getElementById('mailingDetailContent').innerHTML = `
                <div class="space-y-4">
                    <div class="glass-effect rounded-xl p-4">
                        <div class="text-xs text-gray-500 uppercase tracking-wider">Статус</div>
                        <div class="text-lg font-bold text-blue-400 mt-1">${task.status}</div>
                    </div>
                    <div class="glass-effect rounded-xl p-4">
                        <div class="text-xs text-gray-500 uppercase tracking-wider">Прогресс</div>
                        <div class="w-full bg-gray-800/50 rounded-full h-3 mt-2">
                            <div class="progress-bar h-3 rounded-full" style="width: ${task.progress}%"></div>
                        </div>
                        <div class="text-sm mt-2 font-semibold">${task.sent_count} / ${task.total_messages} (${task.progress}%)</div>
                    </div>
                    <div class="glass-effect rounded-xl p-4">
                        <div class="text-xs text-gray-500 uppercase tracking-wider">Сообщение</div>
                        <div class="text-sm mt-1 whitespace-pre-wrap">${task.message}</div>
                    </div>
                    <div class="grid grid-cols-2 gap-4">
                        <div class="glass-effect rounded-xl p-4">
                            <div class="text-xs text-gray-500 uppercase tracking-wider">Тип</div>
                            <div class="text-sm mt-1">${task.mailing_type === 'random' ? 'Рандомная' : 'По кругу'}</div>
                        </div>
                        <div class="glass-effect rounded-xl p-4">
                            <div class="text-xs text-gray-500 uppercase tracking-wider">Задержка</div>
                            <div class="text-sm mt-1">${task.delay} сек</div>
                        </div>
                    </div>
                    <div class="glass-effect rounded-xl p-4">
                        <div class="text-xs text-gray-500 uppercase tracking-wider mb-2">Чаты (${task.chats.length})</div>
                        <div class="text-xs max-h-40 overflow-y-auto scrollbar-thin space-y-1">
                            ${task.chats.map((c, i) => `
                                <div class="py-1.5 px-2 rounded-lg ${i < task.sent_count ? 'bg-green-500/10 text-green-400' : 'bg-gray-800/30 text-gray-500'}">
                                    ${i + 1}. ${c.name || c.id} ${i < task.sent_count ? '✓' : ''}
                                </div>
                            `).join('')}
                        </div>
                    </div>
                    <div class="flex gap-3">
                        ${task.status === 'В работе' ? `
                            <button onclick="controlMailing(${task.id}, 'pause')" 
                                    class="flex-1 bg-yellow-500/20 hover:bg-yellow-500/30 border border-yellow-500/30 py-3 rounded-xl text-yellow-400 font-semibold transition">
                                Пауза
                            </button>
                        ` : task.status === 'Остановлено' ? `
                            <button onclick="controlMailing(${task.id}, 'resume')" 
                                    class="flex-1 bg-green-500/20 hover:bg-green-500/30 border border-green-500/30 py-3 rounded-xl text-green-400 font-semibold transition">
                                Возобновить
                            </button>
                        ` : ''}
                        <button onclick="if(confirm('Удалить рассылку?')) controlMailing(${task.id}, 'delete')" 
                                class="flex-1 bg-red-500/20 hover:bg-red-500/30 border border-red-500/30 py-3 rounded-xl text-red-400 font-semibold transition">
                            Удалить
                        </button>
                    </div>
                </div>
            `;
            document.getElementById('mailingDetailModal').classList.remove('hidden');
        }
        
        async function controlMailing(taskId, action) {
            const response = await fetch('/api/mailing/control/' + taskId, {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({action})
            });
            const data = await response.json();
            if (data.success) {
                closeMailingDetail();
                loadMailings();
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        function toggleAutoresponderCreate() {
            document.getElementById('autoresponderCreateForm').classList.toggle('hidden');
        }
        
        async function createAutoresponder() {
            const accountId = document.getElementById('accountSelect').value;
            if (!accountId) { alert('Выберите аккаунт'); return; }
            const replyText = document.getElementById('arReplyText').value.trim();
            if (!replyText) { alert('Введите текст ответа'); return; }
            
            const response = await fetch('/api/autoresponder/create', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({
                    account_id: accountId,
                    trigger_type: document.getElementById('arTriggerType').value,
                    keywords: document.getElementById('arKeywords').value.trim() || '-',
                    reply_text: replyText
                })
            });
            const data = await response.json();
            if (data.success) {
                alert('Автоответчик создан!');
                loadAutoresponders();
                toggleAutoresponderCreate();
            } else {
                alert(data.error || 'Ошибка');
            }
        }
        
        async function loadAutoresponders() {
            const response = await fetch('/api/autoresponder/list');
            const responders = await response.json();
            const container = document.getElementById('autoresponderList');
            if (container) {
                container.innerHTML = responders.length ? responders.map(ar => `
                    <div class="glass-effect neon-border rounded-xl p-4">
                        <div class="flex justify-between items-start mb-2">
                            <div class="flex-1 mr-2">
                                <div class="text-sm">${ar.reply_text}</div>
                                <div class="text-xs text-gray-500 mt-1">${ar.trigger_type === 'pms' ? 'Только ЛС' : ar.trigger_type === 'groups' ? 'Только группы' : 'Все'} | ${ar.keywords}</div>
                            </div>
                            <button onclick="toggleAutoresponder(${ar.id})" 
                                    class="px-3 py-1 rounded-lg text-xs transition ${
                                        ar.is_active ? 'bg-green-500/20 text-green-400 border border-green-500/30' : 
                                        'bg-gray-800 text-gray-400 border border-gray-700'
                                    }">
                                ${ar.is_active ? 'Вкл' : 'Выкл'}
                            </button>
                        </div>
                        <div class="text-xs text-gray-500">Ответов: ${ar.response_count || 0}${ar.last_response ? ' · Последний: ' + new Date(ar.last_response).toLocaleString() : ''}</div>
                    </div>
                `).join('') : '<p class="text-gray-400 text-center py-8">Нет автоответчиков</p>';
            }
        }
        
        async function toggleAutoresponder(id) {
            await fetch('/api/autoresponder/toggle/' + id, {method: 'POST'});
            loadAutoresponders();
        }
        
        async function loadProfile() {
            const response = await fetch('/api/user');
            const user = await response.json();
            document.getElementById('profileInfo').innerHTML = `
                <div class="text-lg md:text-xl font-bold gradient-text">${user.username}</div>
                <div class="text-gray-400 text-sm md:text-base">Аккаунтов: ${user.accounts_count}</div>
                <div class="${user.subscription_status.includes('Активна') ? 'text-green-400' : 'text-red-400'} font-semibold text-sm md:text-base">
                    ${user.subscription_status}
                </div>
            `;
        }
        
        async function buySubscription(plan) {
            try {
                const response = await fetch('/api/subscription/buy', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({plan})
                });
                const data = await response.json();
                if (data.success && data.pay_url) {
                    window.open(data.pay_url, '_blank');
                    closeBuyModal();
                } else {
                    alert(data.error || 'Ошибка создания платежа');
                }
            } catch (e) {
                alert('Ошибка соединения с сервером');
            }
        }
        
        function logout() {
            window.location.href = '/logout';
        }
        
        setInterval(() => {
            if (currentTab === 'functions') {
                if (currentFunction === 'mailing') loadMailings();
                if (currentFunction === 'autoresponder') loadAutoresponders();
            }
        }, 3000);
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
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id''',
        (session['user_id'], data['account_id'], json.dumps(data['chats']), 
         data['message'], data.get('delay', 10), len(data['chats']),
         data.get('mailing_type', 'simultaneous'), 'Ожидает')
    )
    task_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': 'Рассылка запущена', 'task_id': task_id})

@app.route('/api/mailing/list')
@login_required
def api_mailing_list():
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM mailing_task WHERE user_id = %s ORDER BY id DESC LIMIT 20', (session['user_id'],))
    tasks = cur.fetchall()
    cur.close()
    conn.close()
    
    return jsonify([{
        'id': t['id'],
        'message': t['message'][:50] + '...' if len(t['message']) > 50 else t['message'],
        'status': t['status'],
        'sent_count': t['sent_count'] or 0,
        'total_messages': t['total_messages'],
        'mailing_type': t['mailing_type'],
        'delay': t['delay'] or 10,
        'progress': round((t['sent_count'] or 0) / t['total_messages'] * 100) if t['total_messages'] > 0 else 0
    } for t in tasks])

@app.route('/api/mailing/detail/<int:task_id>')
@login_required
def api_mailing_detail(task_id):
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM mailing_task WHERE id = %s AND user_id = %s', (task_id, session['user_id']))
    task = cur.fetchone()
    cur.close()
    conn.close()
    
    if not task:
        return jsonify({'error': 'Рассылка не найдена'})
    
    chats_data = json.loads(task['chats']) if task['chats'] else []
    chats_with_status = []
    for i, chat_id in enumerate(chats_data):
        chat_name = chat_id
        if isinstance(chat_id, dict):
            chat_name = chat_id.get('name', chat_id.get('id', str(chat_id)))
        chats_with_status.append({
            'id': str(chat_id) if not isinstance(chat_id, dict) else chat_id.get('id', str(chat_id)),
            'name': chat_name
        })
    
    return jsonify({
        'id': task['id'],
        'message': task['message'],
        'status': task['status'],
        'sent_count': task['sent_count'] or 0,
        'total_messages': task['total_messages'],
        'mailing_type': task['mailing_type'],
        'delay': task['delay'] or 10,
        'progress': round((task['sent_count'] or 0) / task['total_messages'] * 100) if task['total_messages'] > 0 else 0,
        'chats': chats_with_status
    })

@app.route('/api/mailing/control/<int:task_id>', methods=['POST'])
@login_required
def api_control_mailing(task_id):
    data = request.get_json()
    action = data.get('action')
    
    conn = get_db_connection()
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cur.execute('SELECT * FROM mailing_task WHERE id = %s AND user_id = %s', (task_id, session['user_id']))
    task = cur.fetchone()
    
    if not task:
        cur.close()
        conn.close()
        return jsonify({'error': 'Рассылка не найдена'})
    
    if action == 'pause' and task['status'] == 'В работе':
        cur.execute("UPDATE mailing_task SET status = 'Остановлено' WHERE id = %s", (task_id,))
        message = 'Рассылка остановлена'
    elif action == 'resume' and task['status'] == 'Остановлено':
        cur.execute("UPDATE mailing_task SET status = 'Ожидает' WHERE id = %s", (task_id,))
        message = 'Рассылка возобновлена'
    elif action == 'delete':
        cur.execute('DELETE FROM mailing_task WHERE id = %s', (task_id,))
        message = 'Рассылка удалена'
    else:
        cur.close()
        conn.close()
        return jsonify({'error': 'Неверное действие'})
    
    conn.commit()
    cur.close()
    conn.close()
    return jsonify({'success': True, 'message': message})

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
        'is_active': r['is_active'],
        'response_count': r['response_count'] or 0,
        'last_response': r['last_response'].isoformat() if r['last_response'] else None
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
    try:
        data = request.get_json()
        plan = data.get('plan')
        
        prices = {
            '7': {'amount': '20', 'days': 7},
            '14': {'amount': '35', 'days': 14},
            '30': {'amount': '65', 'days': 30},
            '60': {'amount': '110', 'days': 60},
            '120': {'amount': '200', 'days': 120},
            '360': {'amount': '500', 'days': 360}
        }
        
        if plan not in prices:
            return jsonify({'error': 'Неверный тариф'}), 400
        
        price_info = prices[plan]
        
        invoice_data = json.dumps({
            'asset': 'USDT',
            'amount': price_info['amount'],
            'description': f'Vest Traffer - {price_info["days"]} дней',
            'payload': json.dumps({
                'user_id': session['user_id'],
                'days': price_info['days']
            }),
            'allow_comments': False,
            'allow_anonymous': False,
            'expires_in': 3600
        }).encode('utf-8')
        
        req = urllib.request.Request(
            'https://pay.crypt.bot/api/createInvoice',
            data=invoice_data,
            headers={
                'Content-Type': 'application/json',
                'Crypto-Pay-API-Token': CRYPTO_BOT_TOKEN
            },
            method='POST'
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
        
        if result.get('ok'):
            return jsonify({
                'success': True,
                'pay_url': result['result']['pay_url']
            })
        else:
            error_msg = result.get('error', {}).get('name', 'Unknown error')
            return jsonify({'error': f'Ошибка Crypto Bot: {error_msg}'}), 500
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"Crypto Bot API Error: {error_body}")
        try:
            error_data = json.loads(error_body)
            error_msg = error_data.get('error', {}).get('name', str(e))
        except:
            error_msg = str(e)
        return jsonify({'error': f'Ошибка платежной системы: {error_msg}'}), 500
    except Exception as e:
        print(f"Payment Error: {str(e)}")
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
