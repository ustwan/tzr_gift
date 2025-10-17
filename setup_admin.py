#!/usr/bin/env python3
"""
Скрипт настройки первого администратора
"""

import json
import sys

def setup_first_admin():
    """Настройка первого администратора"""
    print("\n" + "="*60)
    print("🔧 НАСТРОЙКА ПЕРВОГО АДМИНИСТРАТОРА")
    print("="*60)
    print()
    print("Чтобы узнать ваш Telegram ID:")
    print("1. Найдите бота @userinfobot в Telegram")
    print("2. Отправьте ему /start")
    print("3. Скопируйте ваш ID (число)")
    print()
    print("="*60)
    print()
    
    try:
        admin_id = input("Введите ваш Telegram ID: ").strip()
        admin_id = int(admin_id)
        
        # Загружаем или создаем users.json
        try:
            with open("users.json", "r") as f:
                users = json.load(f)
        except:
            users = {"admins": [], "users": []}
        
        # Добавляем админа
        if admin_id not in users["admins"]:
            users["admins"].append(admin_id)
            
            # Сохраняем
            with open("users.json", "w", encoding="utf-8") as f:
                json.dump(users, f, ensure_ascii=False, indent=2)
            
            print()
            print("✅ Администратор успешно добавлен!")
            print(f"ID: {admin_id}")
            print()
            print("Теперь вы можете:")
            print("1. Запустить бота: python gift_bot.py")
            print("   или: docker-compose up -d")
            print("2. Написать боту /start в Telegram")
            print("3. Добавлять других пользователей через /adduser")
            print()
        else:
            print()
            print("⚠️  Этот ID уже в списке администраторов!")
            print()
        
    except ValueError:
        print()
        print("❌ Ошибка: введите корректное число!")
        print()
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n\n❌ Отменено")
        sys.exit(0)

if __name__ == "__main__":
    setup_first_admin()

