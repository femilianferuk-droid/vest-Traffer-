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
    <title>Vest Traffer</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        * { font-family: 'Inter', sans-serif; }
        
        body {
            background: linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0a0a0f 100%);
        }
        
        .glass-effect {
            background: rgba(13, 17, 23, 0.8);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(59, 130, 246, 0.1);
        }
        
        .neon-border {
            border: 1px solid rgba(59, 130, 246, 0.3);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.1), inset 0 0 20px rgba(59, 130, 246, 0.05);
        }
        
        .glow-button {
            background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
            border: 1px solid rgba(59, 130, 246, 0.4);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.2);
            transition: all 0.3s ease;
        }
        
        .glow-button:hover {
            box-shadow: 0 0 30px rgba(59, 130, 246, 0.4), 0 0 60px rgba(59, 130, 246, 0.2);
            transform: translateY(-2px);
        }
        
        .input-field {
            background: rgba(13, 17, 23, 0.9);
            border: 1px solid rgba(59, 130, 246, 0.2);
            transition: all 0.3s ease;
        }
        
        .input-field:focus {
            border-color: rgba(59, 130, 246, 0.5);
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.2);
            outline: none;
        }
        
        @keyframes float {
            0%, 100% { transform: translateY(0px); }
            50% { transform: translateY(-10px); }
        }
        
        .float-animation {
            animation: float 3s ease-in-out infinite;
        }
    </style>
</head>
<body class="min-h-screen text-white">
    <!-- Header -->
    <header class="glass-effect p-4">
        <div class="container mx-auto flex justify-between items-center">
            <h1 class="text-3xl font-bold bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                Vest Traffer
            </h1>
            <button onclick="showLogin()" class="glow-button px-8 py-3 rounded-xl font-semibold">
                Войти
            </button>
        </div>
    </header>

    <!-- Login Modal -->
    <div id="loginModal" class="hidden fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div class="glass-effect neon-border rounded-2xl p-8 max-w-md w-full">
            <h2 class="text-2xl font-bold mb-6 text-center bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                Вход в систему
            </h2>
            <input type="text" id="loginUsername" placeholder="Логин" class="input-field w-full rounded-xl p-4 mb-4 text-white placeholder-gray-500">
            <input type="password" id="loginPassword" placeholder="Пароль" class="input-field w-full rounded-xl p-4 mb-6 text-white placeholder-gray-500">
            <button onclick="login()" class="glow-button w-full py-4 rounded-xl font-semibold text-lg">
                Войти
            </button>
            <p class="mt-6 text-center text-gray-400">
                Нет аккаунта? 
                <a href="#" onclick="showRegister()" class="text-blue-400 hover:text-blue-300 transition">Зарегистрироваться</a>
            </p>
            <button onclick="closeModal('loginModal')" class="mt-4 w-full bg-gray-800 hover:bg-gray-700 py-3 rounded-xl transition">
                Закрыть
            </button>
        </div>
    </div>

    <!-- Register Modal -->
    <div id="registerModal" class="hidden fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div class="glass-effect neon-border rounded-2xl p-8 max-w-md w-full">
            <h2 class="text-2xl font-bold mb-2 text-center bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                Регистрация
            </h2>
            <p class="text-center text-blue-400 mb-6">3 дня триала бесплатно</p>
            <input type="text" id="regUsername" placeholder="Логин (мин. 3 символа)" class="input-field w-full rounded-xl p-4 mb-4 text-white placeholder-gray-500">
            <input type="password" id="regPassword" placeholder="Пароль (мин. 6 символов)" class="input-field w-full rounded-xl p-4 mb-6 text-white placeholder-gray-500">
            <button onclick="register()" class="glow-button w-full py-4 rounded-xl font-semibold text-lg">
                Зарегистрироваться
            </button>
            <p class="mt-6 text-center text-gray-400">
                Уже есть аккаунт? 
                <a href="#" onclick="showLogin()" class="text-blue-400 hover:text-blue-300 transition">Войти</a>
            </p>
            <button onclick="closeModal('registerModal')" class="mt-4 w-full bg-gray-800 hover:bg-gray-700 py-3 rounded-xl transition">
                Закрыть
            </button>
        </div>
    </div>

    <!-- Main Content -->
    <main class="container mx-auto px-4 py-16">
        <!-- Hero Section -->
        <div class="text-center mb-20">
            <div class="float-animation mb-8">
                <div class="w-24 h-24 mx-auto bg-gradient-to-r from-blue-500 to-blue-700 rounded-2xl flex items-center justify-center neon-border">
                    <svg class="w-12 h-12 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M2 5a2 2 0 012-2h7a2 2 0 012 2v4a2 2 0 01-2 2H9l-3 3v-3H4a2 2 0 01-2-2V5z"/>
                        <path d="M15 7v2a4 4 0 01-4 4H9.828l-1.766 1.767c.28.149.599.233.938.233h2l3 3v-3h2a2 2 0 002-2V9a2 2 0 00-2-2h-1z"/>
                    </svg>
                </div>
            </div>
            <h2 class="text-5xl md:text-7xl font-bold mb-6 bg-gradient-to-r from-blue-400 via-blue-500 to-blue-600 bg-clip-text text-transparent">
                Автоматизация Telegram
            </h2>
            <p class="text-xl text-gray-400 mb-10 max-w-2xl mx-auto">
                Профессиональный инструмент для массовых рассылок и автоответов
            </p>
            <button onclick="showRegister()" class="glow-button px-12 py-5 rounded-xl text-xl font-semibold">
                Начать бесплатно
            </button>
        </div>

        <!-- Features Grid -->
        <div class="grid md:grid-cols-3 gap-6 mb-20">
            <div class="glass-effect neon-border rounded-2xl p-8 hover:transform hover:scale-105 transition duration-300">
                <div class="w-12 h-12 bg-gradient-to-r from-blue-500 to-blue-700 rounded-xl flex items-center justify-center mb-4">
                    <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path d="M10.894 2.553a1 1 0 00-1.788 0l-7 14a1 1 0 001.169 1.409l5-1.429A1 1 0 009 15.571V11a1 1 0 112 0v4.571a1 1 0 00.725.962l5 1.428a1 1 0 001.17-1.408l-7-14z"/>
                    </svg>
                </div>
                <h3 class="text-xl font-bold text-blue-400 mb-3">Массовые рассылки</h3>
                <p class="text-gray-400">Отправка в десятки чатов одновременно с настройкой задержек</p>
            </div>

            <div class="glass-effect neon-border rounded-2xl p-8 hover:transform hover:scale-105 transition duration-300">
                <div class="w-12 h-12 bg-gradient-to-r from-blue-500 to-blue-700 rounded-xl flex items-center justify-center mb-4">
                    <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                    </svg>
                </div>
                <h3 class="text-xl font-bold text-blue-400 mb-3">Автоответчики</h3>
                <p class="text-gray-400">Автоматические ответы по ключевым словам в ЛС и группах</p>
            </div>

            <div class="glass-effect neon-border rounded-2xl p-8 hover:transform hover:scale-105 transition duration-300">
                <div class="w-12 h-12 bg-gradient-to-r from-blue-500 to-blue-700 rounded-xl flex items-center justify-center mb-4">
                    <svg class="w-6 h-6 text-white" fill="currentColor" viewBox="0 0 20 20">
                        <path fill-rule="evenodd" d="M5 9V7a5 5 0 0110 0v2a2 2 0 012 2v5a2 2 0 01-2 2H5a2 2 0 01-2-2v-5a2 2 0 012-2zm8-2v2H7V7a3 3 0 016 0z" clip-rule="evenodd"/>
                    </svg>
                </div>
                <h3 class="text-xl font-bold text-blue-400 mb-3">Безопасность</h3>
                <p class="text-gray-400">Шифрование сессий и защита ваших аккаунтов</p>
            </div>
        </div>

        <!-- FAQ Section -->
        <div class="max-w-4xl mx-auto mb-20">
            <h2 class="text-4xl font-bold text-center mb-12 bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                Часто задаваемые вопросы
            </h2>
            
            <div class="space-y-4">
                <div class="glass-effect neon-border rounded-2xl p-6">
                    <h3 class="text-lg font-bold text-blue-400 mb-2">Какие лимиты на рассылки?</h3>
                    <p class="text-gray-400">До 50 чатов за одну рассылку. Рекомендуем задержку 10-30 секунд между сообщениями для избежания блокировок.</p>
                </div>

                <div class="glass-effect neon-border rounded-2xl p-6">
                    <h3 class="text-lg font-bold text-blue-400 mb-2">Безопасно ли хранить сессии?</h3>
                    <p class="text-gray-400">Сессии хранятся в зашифрованном виде. Доступ имеет только наш воркер. Данные не передаются третьим лицам.</p>
                </div>

                <div class="glass-effect neon-border rounded-2xl p-6">
                    <h3 class="text-lg font-bold text-blue-400 mb-2">Как оплатить подписку?</h3>
                    <p class="text-gray-400">Оплата через Crypto Bot (USDT). Доступны тарифы от 7 до 360 дней. Подписка активируется автоматически.</p>
                </div>

                <div class="glass-effect neon-border rounded-2xl p-6">
                    <h3 class="text-lg font-bold text-blue-400 mb-2">Что такое рандомная рассылка?</h3>
                    <p class="text-gray-400">Сообщения отправляются в случайном порядке. Это помогает избежать паттернов и снижает риск блокировки.</p>
                </div>

                <div class="glass-effect neon-border rounded-2xl p-6">
                    <h3 class="text-lg font-bold text-blue-400 mb-2">Как быстро обрабатываются задачи?</h3>
                    <p class="text-gray-400">Воркер проверяет новые задачи каждые 5 секунд. Рассылка начинается мгновенно после создания.</p>
                </div>
            </div>
        </div>

        <!-- Footer -->
        <footer class="text-center border-t border-blue-900/30 pt-8">
            <div class="mb-4">
                <a href="https://t.me/VestTraffSupport" class="text-blue-400 hover:text-blue-300 transition">
                    @VestTraffSupport
                </a>
            </div>
            <div class="text-gray-500">
                Vest Traffer 2026
            </div>
        </footer>
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
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
        
        * { font-family: 'Inter', sans-serif; }
        
        body {
            background: linear-gradient(135deg, #0a0a0f 0%, #0d1117 50%, #0a0a0f 100%);
            min-height: 100vh;
        }
        
        .glass-effect {
            background: rgba(13, 17, 23, 0.8);
            backdrop-filter: blur(20px);
            border: 1px solid rgba(59, 130, 246, 0.1);
        }
        
        .neon-border {
            border: 1px solid rgba(59, 130, 246, 0.3);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.1), inset 0 0 20px rgba(59, 130, 246, 0.05);
        }
        
        .glow-button {
            background: linear-gradient(135deg, #1e3a8a 0%, #2563eb 100%);
            border: 1px solid rgba(59, 130, 246, 0.4);
            box-shadow: 0 0 20px rgba(59, 130, 246, 0.2);
            transition: all 0.3s ease;
        }
        
        .glow-button:hover {
            box-shadow: 0 0 30px rgba(59, 130, 246, 0.4), 0 0 60px rgba(59, 130, 246, 0.2);
            transform: translateY(-2px);
        }
        
        .glow-button:active {
            transform: translateY(0px);
        }
        
        .input-field {
            background: rgba(13, 17, 23, 0.9);
            border: 1px solid rgba(59, 130, 246, 0.2);
            transition: all 0.3s ease;
        }
        
        .input-field:focus {
            border-color: rgba(59, 130, 246, 0.5);
            box-shadow: 0 0 15px rgba(59, 130, 246, 0.2);
            outline: none;
        }
        
        .tab-button {
            position: relative;
            overflow: hidden;
        }
        
        .tab-button::after {
            content: '';
            position: absolute;
            bottom: 0;
            left: 50%;
            transform: translateX(-50%);
            width: 0;
            height: 2px;
            background: linear-gradient(90deg, #3b82f6, #60a5fa);
            transition: width 0.3s ease;
        }
        
        .tab-button.active::after {
            width: 80%;
        }
        
        .tab-button.active {
            color: #60a5fa;
        }
        
        .progress-bar {
            background: linear-gradient(90deg, #1e3a8a, #3b82f6, #60a5fa);
            background-size: 200% 100%;
            animation: shimmer 2s infinite;
        }
        
        @keyframes shimmer {
            0% { background-position: 200% 0; }
            100% { background-position: -200% 0; }
        }
        
        @keyframes pulse-glow {
            0%, 100% { box-shadow: 0 0 5px rgba(59, 130, 246, 0.2); }
            50% { box-shadow: 0 0 20px rgba(59, 130, 246, 0.4); }
        }
        
        .pulse-animation {
            animation: pulse-glow 2s infinite;
        }
    </style>
</head>
<body class="text-white pb-24">
    <!-- Header -->
    <header class="glass-effect p-4">
        <div class="container mx-auto">
            <h1 class="text-2xl font-bold bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                Vest Traffer
            </h1>
        </div>
    </header>

    <!-- Main Content -->
    <main class="container mx-auto px-4 py-6" id="mainContent">
        <!-- Content loads dynamically -->
    </main>

    <!-- Bottom Navigation -->
    <nav class="fixed bottom-0 left-0 right-0 glass-effect border-t border-blue-900/30">
        <div class="container mx-auto flex justify-around py-3">
            <button onclick="loadTab('accounts')" class="tab-button flex flex-col items-center text-gray-400 transition pb-1" id="tab-accounts">
                <svg class="w-6 h-6 mb-1" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 2a4 4 0 100 8 4 4 0 000-8zM3 18v-2a5 5 0 015-5h4a5 5 0 015 5v2H3z"/>
                </svg>
                <span class="text-xs">Аккаунты</span>
            </button>
            <button onclick="loadTab('functions')" class="tab-button flex flex-col items-center text-gray-400 transition pb-1" id="tab-functions">
                <svg class="w-6 h-6 mb-1" fill="currentColor" viewBox="0 0 20 20">
                    <path d="M10 3a1 1 0 011 1v5h5a1 1 0 110 2h-5v5a1 1 0 11-2 0v-5H4a1 1 0 110-2h5V4a1 1 0 011-1z"/>
                </svg>
                <span class="text-xs">Функции</span>
            </button>
            <button onclick="loadTab('profile')" class="tab-button flex flex-col items-center text-gray-400 transition pb-1" id="tab-profile">
                <svg class="w-6 h-6 mb-1" fill="currentColor" viewBox="0 0 20 20">
                    <path fill-rule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clip-rule="evenodd"/>
                </svg>
                <span class="text-xs">Профиль</span>
            </button>
        </div>
    </nav>

    <!-- Buy Subscription Modal -->
    <div id="buyModal" class="hidden fixed inset-0 bg-black/80 backdrop-blur-sm flex items-center justify-center z-50 p-4">
        <div class="glass-effect neon-border rounded-2xl p-6 max-w-sm w-full">
            <h3 class="text-xl font-bold mb-4 text-center bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                Выберите тариф
            </h3>
            <div class="space-y-2">
                <button onclick="buySubscription('7')" class="glow-button w-full py-3 rounded-xl flex justify-between px-4">
                    <span>7 дней</span>
                    <span>20₽</span>
                </button>
                <button onclick="buySubscription('14')" class="glow-button w-full py-3 rounded-xl flex justify-between px-4">
                    <span>14 дней</span>
                    <span>35₽</span>
                </button>
                <button onclick="buySubscription('30')" class="glow-button w-full py-3 rounded-xl flex justify-between px-4">
                    <span>30 дней</span>
                    <span>65₽</span>
                </button>
                <button onclick="buySubscription('60')" class="glow-button w-full py-3 rounded-xl flex justify-between px-4">
                    <span>60 дней</span>
                    <span>110₽</span>
                </button>
                <button onclick="buySubscription('120')" class="glow-button w-full py-3 rounded-xl flex justify-between px-4">
                    <span>120 дней</span>
                    <span>200₽</span>
                </button>
                <button onclick="buySubscription('360')" class="glow-button w-full py-3 rounded-xl flex justify-between px-4">
                    <span>360 дней</span>
                    <span>500₽</span>
                </button>
            </div>
            <button onclick="closeBuyModal()" class="mt-4 w-full bg-gray-800 hover:bg-gray-700 py-3 rounded-xl transition">
                Отмена
            </button>
        </div>
    </div>

    <script>
        let currentTab = 'accounts';
        let currentFunction = 'mailing'; // mailing или autoresponder
        let loadedChats = [];
        
        // Инициализация
        loadTab('accounts');
        
        async function loadTab(tab) {
            currentTab = tab;
            
            // Обновление стилей кнопок
            document.querySelectorAll('.tab-button').forEach(btn => {
                btn.classList.remove('active');
            });
            document.getElementById('tab-' + tab).classList.add('active');
            
            const main = document.getElementById('mainContent');
            
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
                    <h2 class="text-2xl font-bold mb-6 bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                        Менеджер аккаунтов
                    </h2>
                    <button onclick="showAddAccount()" class="glow-button w-full py-4 rounded-xl font-semibold mb-6">
                        + Добавить аккаунт
                    </button>
                    <div id="accountsList" class="space-y-3"></div>
                    
                    <!-- Add Account Form -->
                    <div id="addAccountForm" class="hidden glass-effect neon-border rounded-2xl p-6 mt-4">
                        <h3 class="text-lg font-bold mb-4 text-blue-400">Добавление аккаунта</h3>
                        <div id="step1">
                            <label class="block mb-2 text-gray-300">Номер телефона</label>
                            <input type="text" id="phoneNumber" placeholder="+79123456789" 
                                   class="input-field w-full rounded-xl p-4 mb-4 text-white placeholder-gray-500">
                            <button onclick="sendCode()" class="glow-button w-full py-3 rounded-xl font-semibold">
                                Получить код
                            </button>
                        </div>
                        <div id="step2" class="hidden">
                            <label class="block mb-2 text-gray-300">Код из SMS</label>
                            <input type="text" id="smsCode" placeholder="12345" 
                                   class="input-field w-full rounded-xl p-4 mb-4 text-white placeholder-gray-500">
                            <label class="block mb-2 text-gray-300">2FA пароль (если есть)</label>
                            <input type="password" id="twofaPassword" placeholder="Оставьте пустым если нет" 
                                   class="input-field w-full rounded-xl p-4 mb-4 text-white placeholder-gray-500">
                            <button onclick="verifyCode()" class="glow-button w-full py-3 rounded-xl font-semibold">
                                Подтвердить
                            </button>
                        </div>
                        <button onclick="hideAddAccount()" class="mt-4 w-full bg-gray-800 hover:bg-gray-700 py-3 rounded-xl transition">
                            Отмена
                        </button>
                    </div>
                </div>`;
        }
        
        async function getFunctionsTabHTML() {
            return `
                <div>
                    <h2 class="text-2xl font-bold mb-6 bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                        Функции
                    </h2>
                    
                    <!-- Function Selector -->
                    <div class="flex gap-2 mb-6">
                        <button onclick="switchFunction('mailing')" id="btn-mailing" 
                                class="glow-button flex-1 py-3 rounded-xl font-semibold">
                            Рассылка
                        </button>
                        <button onclick="switchFunction('autoresponder')" id="btn-autoresponder" 
                                class="flex-1 py-3 rounded-xl font-semibold glass-effect">
                            Автоответчик
                        </button>
                    </div>
                    
                    <!-- Account Select -->
                    <div class="glass-effect neon-border rounded-2xl p-4 mb-4">
                        <label class="block mb-2 text-gray-300">Рабочий аккаунт</label>
                        <select id="accountSelect" class="input-field w-full rounded-xl p-3 text-white">
                            <option value="">Выберите аккаунт</option>
                        </select>
                    </div>
                    
                    <!-- Mailing Section -->
                    <div id="mailingSection">
                        <button onclick="toggleMailingCreate()" class="glow-button w-full py-4 rounded-xl font-semibold mb-4">
                            Создать рассылку
                        </button>
                        
                        <div id="mailingCreateForm" class="hidden glass-effect neon-border rounded-2xl p-6 mb-4">
                            <h3 class="text-lg font-bold mb-4 text-blue-400">Новая рассылка</h3>
                            <button onclick="loadChats()" class="glow-button w-full py-3 rounded-xl mb-4">
                                Загрузить чаты
                            </button>
                            <div id="chatsList" class="max-h-48 overflow-y-auto space-y-2 mb-4"></div>
                            <button onclick="selectFirst50()" class="text-blue-400 hover:text-blue-300 text-sm mb-4">
                                Выбрать первые 50
                            </button>
                            <div class="space-y-3">
                                <input type="number" id="delayInput" value="10" placeholder="Задержка (сек)" 
                                       class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500">
                                <select id="mailingType" class="input-field w-full rounded-xl p-3 text-white">
                                    <option value="simultaneous">Одновременная по кругу</option>
                                    <option value="random">Рандомная</option>
                                </select>
                                <textarea id="messageText" rows="4" placeholder="Текст сообщения..."
                                          class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500"></textarea>
                                <button onclick="startMailing()" class="glow-button w-full py-3 rounded-xl font-semibold">
                                    Запустить рассылку
                                </button>
                            </div>
                        </div>
                        
                        <h3 class="text-lg font-bold mb-3 text-blue-400">Мои рассылки</h3>
                        <div id="mailingList" class="space-y-3"></div>
                    </div>
                    
                    <!-- Autoresponder Section -->
                    <div id="autoresponderSection" class="hidden">
                        <button onclick="toggleAutoresponderCreate()" class="glow-button w-full py-4 rounded-xl font-semibold mb-4">
                            Создать автоответчик
                        </button>
                        
                        <div id="autoresponderCreateForm" class="hidden glass-effect neon-border rounded-2xl p-6 mb-4">
                            <h3 class="text-lg font-bold mb-4 text-blue-400">Новый автоответчик</h3>
                            <select id="arTriggerType" class="input-field w-full rounded-xl p-3 text-white mb-3">
                                <option value="pms">Только ЛС</option>
                                <option value="groups">Только группы</option>
                                <option value="all">Все сообщения</option>
                            </select>
                            <input type="text" id="arKeywords" value="-" placeholder="Ключевые слова (- для всех)" 
                                   class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500 mb-3">
                            <textarea id="arReplyText" rows="4" placeholder="Текст ответа..."
                                      class="input-field w-full rounded-xl p-3 text-white placeholder-gray-500 mb-3"></textarea>
                            <button onclick="createAutoresponder()" class="glow-button w-full py-3 rounded-xl font-semibold">
                                Создать
                            </button>
                        </div>
                        
                        <h3 class="text-lg font-bold mb-3 text-blue-400">Мои автоответчики</h3>
                        <div id="autoresponderList" class="space-y-3"></div>
                    </div>
                </div>`;
        }
        
        async function getProfileTabHTML() {
            return `
                <div>
                    <h2 class="text-2xl font-bold mb-6 bg-gradient-to-r from-blue-400 to-blue-600 bg-clip-text text-transparent">
                        Профиль
                    </h2>
                    <div class="glass-effect neon-border rounded-2xl p-6 mb-6">
                        <div id="profileInfo" class="space-y-3"></div>
                    </div>
                    
                    <button onclick="showBuyModal()" class="glow-button w-full py-4 rounded-xl font-semibold mb-4 pulse-animation">
                        Купить подписку
                    </button>
                    
                    <button onclick="logout()" class="w-full bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 py-4 rounded-xl font-semibold transition">
                        Выйти
                    </button>
                    
                    <div class="mt-8 text-center">
                        <a href="https://t.me/VestTraffSupport" class="text-blue-400 hover:text-blue-300 transition">
                            @VestTraffSupport
                        </a>
                        <div class="text-gray-500 text-sm mt-2">
                            Vest Traffer 2026
                        </div>
                    </div>
                </div>`;
        }
        
        // Function switching
        function switchFunction(func) {
            currentFunction = func;
            document.getElementById('btn-mailing').className = func === 'mailing' ? 
                'glow-button flex-1 py-3 rounded-xl font-semibold' : 
                'flex-1 py-3 rounded-xl font-semibold glass-effect';
            document.getElementById('btn-autoresponder').className = func === 'autoresponder' ? 
                'glow-button flex-1 py-3 rounded-xl font-semibold' : 
                'flex-1 py-3 rounded-xl font-semibold glass-effect';
            
            document.getElementById('mailingSection').classList.toggle('hidden', func !== 'mailing');
            document.getElementById('autoresponderSection').classList.toggle('hidden', func !== 'autoresponder');
            
            if (func === 'mailing') loadMailings();
            if (func === 'autoresponder') loadAutoresponders();
        }
        
        // Account functions
        function showAddAccount() {
            document.getElementById('addAccountForm').classList.remove('hidden');
            document.getElementById('step1').classList.remove('hidden');
            document.getElementById('step2').classList.add('hidden');
        }
        
        function hideAddAccount() {
            document.getElementById('addAccountForm').classList.add('hidden');
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
                <div class="glass-effect neon-border rounded-xl p-4 flex justify-between items-center">
                    <div>
                        <div class="font-semibold">${acc.phone}</div>
                        <div class="text-sm ${acc.has_session ? 'text-green-400' : 'text-yellow-400'}">
                            ${acc.has_session ? 'Авторизован' : 'Нет сессии'}
                        </div>
                    </div>
                    <button onclick="deleteAccount(${acc.id})" 
                            class="bg-red-600/20 hover:bg-red-600/30 border border-red-500/30 px-4 py-2 rounded-xl text-sm transition">
                        Удалить
                    </button>
                </div>
            `).join('') || '<p class="text-gray-400 text-center">Нет аккаунтов</p>';
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
                    accounts.filter(a => a.has_session).map(a => 
                        `<option value="${a.id}">${a.phone}</option>`
                    ).join('');
            }
        }
        
        // Mailing functions
        function toggleMailingCreate() {
            document.getElementById('mailingCreateForm').classList.toggle('hidden');
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
                displayChats();
            } else {
                alert(data.error || 'Ошибка загрузки чатов');
            }
        }
        
        function displayChats() {
            const container = document.getElementById('chatsList');
            container.innerHTML = loadedChats.map(chat => `
                <label class="flex items-center p-3 glass-effect rounded-xl">
                    <input type="checkbox" value="${chat.id}" class="chat-checkbox mr-3">
                    <div>
                        <div class="text-sm">${chat.name}</div>
                        <div class="text-xs text-gray-500">${chat.type}</div>
                    </div>
                </label>
            `).join('');
        }
        
        function selectFirst50() {
            const checkboxes = document.querySelectorAll('.chat-checkbox');
            checkboxes.forEach((cb, i) => {
                cb.checked = i < 50;
            });
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
            
            if (!message) {
                alert('Введите текст сообщения');
                return;
            }
            
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
                    <div class="glass-effect neon-border rounded-xl p-4">
                        <div class="flex justify-between text-sm mb-2">
                            <span class="text-gray-300">${task.message}</span>
                            <span class="${
                                task.status === 'В работе' ? 'text-yellow-400' : 
                                task.status === 'Завершено' ? 'text-green-400' : 'text-red-400'
                            }">${task.status}</span>
                        </div>
                        <div class="w-full bg-gray-800 rounded-full h-2 mb-1">
                            <div class="progress-bar h-2 rounded-full transition-all duration-500" 
                                 style="width: ${task.progress}%"></div>
                        </div>
                        <div class="text-xs text-gray-500">${task.sent_count}/${task.total_messages}</div>
                    </div>
                `).join('') : '<p class="text-gray-400 text-center">Нет рассылок</p>';
            }
        }
        
        // Autoresponder functions
        function toggleAutoresponderCreate() {
            document.getElementById('autoresponderCreateForm').classList.toggle('hidden');
        }
        
        async function createAutoresponder() {
            const accountId = document.getElementById('accountSelect').value;
            if (!accountId) {
                alert('Выберите аккаунт');
                return;
            }
            
            const triggerType = document.getElementById('arTriggerType').value;
            const keywords = document.getElementById('arKeywords').value || '-';
            const replyText = document.getElementById('arReplyText').value;
            
            if (!replyText) {
                alert('Введите текст ответа');
                return;
            }
            
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
                    <div class="glass-effect neon-border rounded-xl p-4 flex justify-between items-center">
                        <div class="text-sm flex-1 mr-2">
                            <div class="text-gray-300">${ar.reply_text}</div>
                            <div class="text-xs text-gray-500 mt-1">${ar.trigger_type} | ${ar.keywords}</div>
                        </div>
                        <button onclick="toggleAutoresponder(${ar.id})" 
                                class="px-4 py-2 rounded-xl text-sm transition ${
                                    ar.is_active ? 'bg-green-600/20 border border-green-500/30 text-green-400' : 
                                    'bg-gray-800 border border-gray-700 text-gray-400'
                                }">
                            ${ar.is_active ? 'Вкл' : 'Выкл'}
                        </button>
                    </div>
                `).join('') : '<p class="text-gray-400 text-center">Нет автоответчиков</p>';
            }
        }
        
        async function toggleAutoresponder(id) {
            await fetch('/api/autoresponder/toggle/' + id, {method: 'POST'});
            loadAutoresponders();
        }
        
        // Profile functions
        async function loadProfile() {
            const response = await fetch('/api/user');
            const user = await response.json();
            document.getElementById('profileInfo').innerHTML = `
                <div class="text-xl font-bold text-blue-400">${user.username}</div>
                <div class="text-gray-400">Аккаунтов: ${user.accounts_count}</div>
                <div class="${user.subscription_status.includes('Активна') ? 'text-green-400' : 'text-red-400'} font-semibold">
                    ${user.subscription_status}
                </div>
            `;
        }
        
        function showBuyModal() {
            document.getElementById('buyModal').classList.remove('hidden');
        }
        
        function closeBuyModal() {
            document.getElementById('buyModal').classList.add('hidden');
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
        
        // Auto-refresh
        setInterval(() => {
            if (currentTab === 'functions') {
                if (currentFunction === 'mailing') loadMailings();
                if (currentFunction === 'autoresponder') loadAutoresponders();
            }
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
    try:
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
        
        # Создание платежа через Crypto Bot API
        invoice_data = json.dumps({
            'asset': 'USDT',
            'amount': str(price_info['amount']),
            'description': f'Подписка Vest Traffer на {price_info["days"]} дней',
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
            return jsonify({'error': 'Ошибка создания платежа: ' + str(result)}), 500
            
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        print(f"Crypto Bot API error: {error_body}")
        return jsonify({'error': 'Ошибка платежной системы. Попробуйте позже.'}), 500
    except Exception as e:
        print(f"Payment error: {str(e)}")
        return jsonify({'error': 'Внутренняя ошибка сервера'}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
