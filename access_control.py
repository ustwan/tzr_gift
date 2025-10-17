#!/usr/bin/env python3
"""
Модуль контроля доступа для Telegram бота
Управление администраторами и пользователями
"""

import json
import logging
from functools import wraps

logger = logging.getLogger(__name__)

USERS_FILE = "users.json"

# ============================================================================
# ФУНКЦИИ РАБОТЫ С ПОЛЬЗОВАТЕЛЯМИ
# ============================================================================

def load_users():
    """Загрузка списка пользователей"""
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        # Создаем файл с пустыми списками
        default_users = {"admins": [], "users": []}
        save_users(default_users)
        return default_users
    except Exception as e:
        logger.error(f"Ошибка загрузки users.json: {e}")
        return {"admins": [], "users": []}

def save_users(users_data):
    """Сохранение списка пользователей"""
    try:
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(users_data, f, ensure_ascii=False, indent=2)
        logger.info("Пользователи сохранены")
    except Exception as e:
        logger.error(f"Ошибка сохранения users.json: {e}")

def is_admin(user_id):
    """Проверка, является ли пользователь администратором"""
    users = load_users()
    return user_id in users.get("admins", [])

def is_user(user_id):
    """Проверка, является ли пользователь в списке разрешенных"""
    users = load_users()
    return user_id in users.get("users", [])

def has_access(user_id):
    """Проверка доступа (админ или пользователь)"""
    return is_admin(user_id) or is_user(user_id)

def add_user(user_id, role="user"):
    """Добавить пользователя"""
    users = load_users()
    
    if role == "admin":
        if user_id not in users["admins"]:
            users["admins"].append(user_id)
            save_users(users)
            return True
    else:
        if user_id not in users["users"]:
            users["users"].append(user_id)
            save_users(users)
            return True
    
    return False

def remove_user(user_id):
    """Удалить пользователя (не админа!)"""
    users = load_users()
    
    if user_id in users["users"]:
        users["users"].remove(user_id)
        save_users(users)
        return True
    
    return False

def get_all_users():
    """Получить всех пользователей"""
    return load_users()

# ============================================================================
# ДЕКОРАТОРЫ ДЛЯ ПРОВЕРКИ ДОСТУПА
# ============================================================================

def require_access(func):
    """Декоратор: требуется доступ (админ или пользователь)"""
    @wraps(func)
    async def wrapper(update, context):
        user_id = update.effective_user.id
        
        if not has_access(user_id):
            await update.effective_message.reply_text(
                "🔒 <b>Доступ запрещен</b>\n\n"
                "У вас нет доступа к этому боту.\n\n"
                "Обратитесь к администратору.",
                parse_mode="HTML"
            )
            return
        
        return await func(update, context)
    
    return wrapper

def require_admin(func):
    """Декоратор: требуются права администратора"""
    @wraps(func)
    async def wrapper(update, context):
        user_id = update.effective_user.id
        
        if not is_admin(user_id):
            await update.effective_message.reply_text(
                "🔒 <b>Недостаточно прав</b>\n\n"
                "Эта функция доступна только администраторам.",
                parse_mode="HTML"
            )
            return
        
        return await func(update, context)
    
    return wrapper

