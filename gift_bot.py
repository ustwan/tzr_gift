#!/usr/bin/env python3
"""
Telegram бот для работы с подарками в игре Timezero Reloaded
Полная версия с управлением списком, экспортом и ML анализом
"""

import asyncio
import json
import socket
import re
import time
import logging
import io
import os
import sys
from collections import defaultdict
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters
)

# Импорт модуля контроля доступа
from access_control import (
    require_access,
    require_admin,
    has_access,
    is_admin,
    add_user,
    remove_user,
    get_all_users
)

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Состояния для ConversationHandler
WAITING_GIFT_NAME, WAITING_GIFT_COUNT = range(2)

# ============================================================================
# КОНФИГУРАЦИЯ И УТИЛИТЫ
# ============================================================================

def load_settings():
    """Загрузка настроек"""
    try:
        with open("settings.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Ошибка загрузки settings.json: {e}")
        return {}

def load_present_list():
    """Загрузка списка подарков"""
    try:
        with open("present_list.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return ["Halloween box"]

def save_present_list(names):
    """Сохранение списка подарков"""
    with open("present_list.json", "w", encoding="utf-8") as f:
        json.dump(names, f, ensure_ascii=False, indent=2)

def save_drop_statistics(total_opened, loot):
    """Сохранение статистики для ML"""
    try:
        try:
            with open("drop_statistics.json", "r", encoding="utf-8") as f:
                stats = json.load(f)
        except:
            stats = {"sessions": []}
        
        # Убедимся что ключ sessions существует
        if "sessions" not in stats:
            stats["sessions"] = []
        
        session = {
            "timestamp": datetime.now().isoformat(),
            "total_opened": total_opened,
            "loot": dict(loot)
        }
        stats["sessions"].append(session)
        
        with open("drop_statistics.json", "w", encoding="utf-8") as f:
            json.dump(stats, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Ошибка сохранения статистики: {e}")

# ============================================================================
# СЕТЕВЫЕ ФУНКЦИИ
# ============================================================================

def parse_inventory_items(data, include_all_sections=False):
    """
    Парсинг предметов из XML
    
    include_all_sections: если True, включает ВСЕ секции (для диагностики)
    """
    result = []
    all_items = []  # Для диагностики
    
    for match in re.finditer(r'<O ([^>]+)\/>', data):
        attrs = match.group(1)
        id_ = re.search(r'id="([^"]+)"', attrs)
        txt = re.search(r'txt="([^"]+)"', attrs)
        section = re.search(r'section="(\d+)"', attrs)
        count = re.search(r'(?<!max_)count="(\d+)"', attrs)
        
        # Сохраняем все для диагностики
        if id_ and txt and section:
            all_items.append({
                "id": id_.group(1),
                "txt": txt.group(1),
                "section": section.group(1),
                "count": int(count.group(1)) if count else 1
            })
        
        # Возвращаем либо все секции, либо только 0-3
        if section:
            if include_all_sections or section.group(1) in {"0", "1", "2", "3"}:
                item = {
                    "id": id_.group(1) if id_ else "",
                    "txt": txt.group(1) if txt else "",
                    "section": section.group(1),
                    "count": int(count.group(1)) if count else 1
                }
                result.append(item)
    
    # Логируем статистику по секциям
    if all_items:
        sections_stat = defaultdict(int)
        for item in all_items:
            sections_stat[item['section']] += 1
        logger.info(f"Секции в инвентаре: {dict(sections_stat)}")
    
    return result

def get_inventory_items_socket(sock, include_all_sections=False):
    """Получить предметы из инвентаря"""
    getme_xml = '<GETME />\x00'
    sock.sendall(getme_xml.encode("utf-8"))
    
    data = b''
    sock.settimeout(1.3)
    for _ in range(8):
        try:
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
            if b'</MYPARAM>' in chunk:
                break
        except socket.timeout:
            break
    
    data = data.decode("utf-8", errors="ignore")
    return parse_inventory_items(data, include_all_sections=include_all_sections)

def open_gift_recursive(sock, gift_id, present_names):
    """Открывает подарок рекурсивно"""
    use_xml = f'<USE gift="{gift_id}" />\x00'
    sock.sendall(use_xml.encode("utf-8"))
    time.sleep(0.05)
    
    data = b''
    sock.settimeout(1.0)
    try:
        for _ in range(8):
            chunk = sock.recv(65536)
            if not chunk:
                break
            data += chunk
            if b'</GIFT>' in chunk:
                break
    except socket.timeout:
        pass
    
    data = data.decode("utf-8", errors="ignore")
    
    loot = []
    nested_opened = 0
    
    for match in re.finditer(r'<O ([^>]+)\/>', data):
        attrs = match.group(1)
        txt = re.search(r'txt="([^"]+)"', attrs)
        id_ = re.search(r'id="([^"]+)"', attrs)
        count = re.search(r'(?<!max_)count="(\d+)"', attrs)
        
        txt_val = txt.group(1) if txt else ""
        id_val = id_.group(1) if id_ else ""
        count_val = int(count.group(1)) if count else 1
        
        if txt_val in present_names:
            nested_loot, nested_count = open_gift_recursive(sock, id_val, present_names)
            loot.extend(nested_loot)
            nested_opened += nested_count
        else:
            loot.append((txt_val, count_val))
    
    return loot, 1 + nested_opened

def request_available_gifts():
    """Запрос списка доступных подарков с сервера"""
    settings = load_settings()
    
    try:
        host = settings.get("HOST")
        port = int(settings.get("port"))
        login1 = settings.get("LOGIN_1")
        key1 = settings.get("KEY_1")
        local_ip1 = settings.get("local_ip_1")
        client_ver1 = settings.get("client_ver_1")
        v1 = settings.get("ver_1")
        lang1 = settings.get("lang_1")
        
        if not all([host, port, login1, key1]):
            logger.error("Отсутствуют настройки в settings.json")
            raise Exception("Неполные настройки в settings.json (LOGIN_1, KEY_1, HOST, port)")
        
        logger.info(f"Запрос подарков: подключение к {host}:{port}")
        
        login_xml = f'<LOGIN v3="{local_ip1}" lang="{lang1}" v2="{client_ver1}" v="{v1}" p="{key1}" l="{login1}" />\x00'
        gh_xml = '<GH souvenir="808.5,808.21,802.0,899.0,905.0,873.0,900.0,901.0,0.89,943.0" />\x00'
        
        with socket.create_connection((host, port), timeout=5) as sock:
            logger.info("Подключение установлено, отправка LOGIN")
            sock.sendall(login_xml.encode("utf-8"))
            
            auth_resp = sock.recv(8192)
            logger.info(f"Ответ на LOGIN: {auth_resp[:200]}")
            
            logger.info("Отправка GH запроса")
            sock.sendall(gh_xml.encode("utf-8"))
            
            data = b""
            sock.settimeout(2)
            start_time = time.time()
            
            # Читаем данные до таймаута или пока не перестанут приходить
            while time.time() - start_time < 3:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                    logger.debug(f"Получен chunk: {len(chunk)} байт, всего: {len(data)}")
                    # Если получили меньше буфера - возможно данные закончились
                    # Но ждем еще немного на случай если придет еще
                    if len(chunk) < 4096:
                        time.sleep(0.3)  # Небольшая задержка
                except socket.timeout:
                    logger.debug("Таймаут чтения, выходим")
                    break
            
            logger.info(f"Получено {len(data)} байт данных")
            
            data_str = data.decode("utf-8", errors="ignore")
            logger.debug(f"Ответ GH: {data_str[:500]}")
            
            matches = re.findall(
                r'<O [^>]*?txt="([^"]+)"[^>]*?id="([^"]+)"|<O [^>]*?id="([^"]+)"[^>]*?txt="([^"]+)"',
                data_str
            )
            
            results = []
            for m in matches:
                if m[0] and m[1]:
                    results.append({"txt": m[0], "id": m[1]})
                elif m[2] and m[3]:
                    results.append({"txt": m[3], "id": m[2]})
            
            logger.info(f"Найдено подарков: {len(results)}")
            return results
            
    except socket.timeout as e:
        logger.error(f"Таймаут подключения к серверу: {e}")
        raise Exception(f"Таймаут подключения к {host}:{port}")
    except socket.error as e:
        logger.error(f"Ошибка сокета: {e}")
        raise Exception(f"Не удалось подключиться к серверу: {e}")
    except Exception as e:
        logger.error(f"Ошибка запроса подарков: {e}", exc_info=True)
        raise

# ============================================================================
# TELEGRAM КОМАНДЫ - ГЛАВНОЕ МЕНЮ
# ============================================================================

@require_access
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главное меню"""
    user_id = update.effective_user.id
    user_is_admin = is_admin(user_id)
    
    keyboard = [
        [
            InlineKeyboardButton("📦 Анализ", callback_data="analyze"),
            InlineKeyboardButton("📤 Отправить", callback_data="send"),
        ],
        [
            InlineKeyboardButton("🧹 Очистка", callback_data="clean"),
            InlineKeyboardButton("📋 Список", callback_data="list"),
        ],
        [
            InlineKeyboardButton("📊 ML Статистика", callback_data="stats"),
            InlineKeyboardButton("💾 Экспорт", callback_data="export"),
        ],
        [
            InlineKeyboardButton("ℹ️ Помощь", callback_data="help"),
        ],
    ]
    
    # Добавляем админ-кнопки
    if user_is_admin:
        keyboard.append([
            InlineKeyboardButton("👥 Пользователи", callback_data="manage_users"),
            InlineKeyboardButton("🔄 Перезапуск", callback_data="restart_bot"),
        ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    role_text = "👑 Администратор" if user_is_admin else "👤 Пользователь"
    
    text = (
        "🎁 <b>GiftApp Bot</b>\n"
        "<i>Для игры Timezero Reloaded</i>\n\n"
        f"Ваш статус: {role_text}\n\n"
        "Выберите действие:"
    )
    
    if update.message:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode="HTML")
    else:
        await update.callback_query.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")

# ============================================================================
# АНАЛИЗ ПОДАРКОВ
# ============================================================================

@require_access
async def analyze_presents(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Анализ и открытие всех подарков"""
    query = update.callback_query
    await query.answer()
    
    settings = load_settings()
    present_names = set(load_present_list())
    
    msg = await query.message.reply_text(
        "📦 <b>Анализ подарков</b>\n\n🔄 Подключение к серверу...",
        parse_mode="HTML"
    )
    
    try:
        host = settings.get("HOST")
        port = int(settings.get("port"))
        login2 = settings.get("LOGIN_2")
        key2 = settings.get("KEY_2")
        local_ip2 = settings.get("local_ip_2")
        client_ver2 = settings.get("client_ver_2")
        v2 = settings.get("ver_2")
        lang2 = settings.get("lang_2")
        
        login_xml = f'<LOGIN v3="{local_ip2}" lang="{lang2}" v2="{client_ver2}" v="{v2}" p="{key2}" l="{login2}" />\x00'
        
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(login_xml.encode("utf-8"))
            sock.recv(65536)
            
            loot = defaultdict(int)
            total_opened = 0
            iteration = 0
            already_opened_ids = set()
            
            while True:
                iteration += 1
                inv = get_inventory_items_socket(sock)
                gifts = [item for item in inv if item['txt'] in present_names and item['id'] not in already_opened_ids]
                
                if not gifts:
                    break
                
                await msg.edit_text(
                    f"📦 <b>Анализ подарков</b>\n\n"
                    f"🔄 Итерация {iteration}\n"
                    f"Найдено: {len(gifts)}\n"
                    f"Открыто: {total_opened}",
                    parse_mode="HTML"
                )
                
                for i, gift in enumerate(gifts):
                    gift_loot, opened_count = open_gift_recursive(sock, gift['id'], present_names)
                    
                    for item_name, item_count in gift_loot:
                        loot[item_name] += item_count
                    
                    total_opened += opened_count
                    already_opened_ids.add(gift['id'])
                    
                    update_interval = max(5, len(gifts) // 10)
                    if (i + 1) % update_interval == 0 or (i + 1) == len(gifts):
                        progress = int(((i + 1) / len(gifts)) * 100)
                        bar = "█" * (progress // 10) + "░" * (10 - progress // 10)
                        
                        await msg.edit_text(
                            f"📦 <b>Анализ подарков</b>\n\n"
                            f"🔄 Итерация {iteration}\n"
                            f"{bar} {progress}%\n"
                            f"Открыто: {i + 1}/{len(gifts)}\n"
                            f"Всего: {total_opened}",
                            parse_mode="HTML"
                        )
                    
                    time.sleep(0.3)
        
        result_text = (
            f"✅ <b>Анализ завершен!</b>\n\n"
            f"📦 Открыто подарков: <b>{total_opened}</b>\n\n"
            f"📊 <b>Получено ({len(loot)} типов):</b>\n"
        )
        
        sorted_loot = sorted(loot.items(), key=lambda x: (-x[1], x[0]))
        
        # Показываем до 50 предметов основным списком
        for item_name, item_count in sorted_loot[:50]:
            result_text += f"  • {item_name}: <code>{item_count}</code>\n"
        
        # Если больше 50 - показываем остальные компактно
        if len(loot) > 50:
            result_text += f"\n<b>Остальные предметы ({len(loot) - 50}):</b>\n"
            remaining = sorted_loot[50:]
            for item_name, item_count in remaining:
                result_text += f"  • {item_name}: {item_count}\n"
        
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        
        # Telegram имеет лимит 4096 символов на сообщение
        if len(result_text) > 4000:
            # Если текст слишком длинный - отправляем в два сообщения
            result_text_part1 = (
                f"✅ <b>Анализ завершен!</b>\n\n"
                f"📦 Открыто подарков: <b>{total_opened}</b>\n\n"
                f"📊 <b>Получено ({len(loot)} типов):</b>\n"
            )
            
            for item_name, item_count in sorted_loot:
                result_text_part1 += f"  • {item_name}: <code>{item_count}</code>\n"
            
            # Разбиваем на части по ~3500 символов
            max_len = 3500
            parts = []
            current_part = result_text_part1[:max_len]
            remaining_text = result_text_part1[max_len:]
            
            while remaining_text:
                parts.append(current_part)
                current_part = remaining_text[:max_len]
                remaining_text = remaining_text[max_len:]
            parts.append(current_part)
            
            # Отправляем первую часть (редактируем текущее сообщение)
            await msg.edit_text(parts[0], parse_mode="HTML")
            
            # Остальные части отправляем новыми сообщениями
            for part in parts[1:]:
                await update.effective_message.reply_text(part, parse_mode="HTML")
            
            # Последнее сообщение с кнопкой
            await update.effective_message.reply_text(
                "✅ <b>Анализ завершен</b>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
        else:
            await msg.edit_text(result_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
        save_drop_statistics(total_opened, loot)
        
    except Exception as e:
        logger.error(f"Ошибка анализа: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await msg.edit_text(
            f"❌ <b>Ошибка:</b>\n<code>{str(e)}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

# ============================================================================
# ОТПРАВКА ПОДАРКОВ
# ============================================================================

@require_access
async def send_gifts_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню отправки подарков с кнопками"""
    query = update.callback_query
    await query.answer()
    
    msg = await query.message.reply_text(
        "📤 <b>Загрузка списка подарков...</b>",
        parse_mode="HTML"
    )
    
    try:
        gifts = request_available_gifts()
        
        if not gifts:
            raise Exception("Список подарков пуст или сервер вернул пустой ответ")
        
        logger.info(f"Получено {len(gifts)} подарков для отправки")
        
        keyboard = []
        for gift in gifts[:10]:  # Топ-10 подарков
            keyboard.append([InlineKeyboardButton(
                f"🎁 {gift['txt']} (ID: {gift['id']})",
                callback_data=f"send_{gift['id']}"
            )])
        
        keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="menu")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await msg.edit_text(
            f"📤 <b>Выберите подарок:</b>\n\n"
            f"Найдено: {len(gifts)} подарков",
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
    
    except Exception as e:
        logger.error(f"Ошибка в send_gifts_menu: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await msg.edit_text(
            f"❌ <b>Ошибка загрузки подарков</b>\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"Проверьте настройки LOGIN_1 и KEY_1 в settings.json",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

async def send_gifts_choose_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выбор количества подарков"""
    query = update.callback_query
    gift_id = query.data.split("_")[1]
    
    await query.answer()
    
    context.user_data['send_gift_id'] = gift_id
    
    keyboard = [
        [
            InlineKeyboardButton("10", callback_data=f"sendcount_10"),
            InlineKeyboardButton("25", callback_data=f"sendcount_25"),
            InlineKeyboardButton("50", callback_data=f"sendcount_50"),
        ],
        [
            InlineKeyboardButton("100", callback_data=f"sendcount_100"),
            InlineKeyboardButton("✏️ Свое число", callback_data=f"sendcount_custom"),
        ],
        [InlineKeyboardButton("❌ Отмена", callback_data="menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await query.message.reply_text(
        f"📤 <b>Подарок ID: {gift_id}</b>\n\n"
        f"Выберите количество:\n"
        f"<i>(макс. 100 за раз)</i>",
        reply_markup=reply_markup,
        parse_mode="HTML"
    )

async def send_gifts_custom_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос своего количества"""
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "✏️ <b>Введите количество подарков</b>\n\n"
        "Отправьте число от 1 до 100:",
        parse_mode="HTML"
    )
    
    return WAITING_GIFT_COUNT

async def receive_custom_count(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение пользовательского количества"""
    try:
        count = int(update.message.text)
        
        if count < 1:
            await update.message.reply_text(
                "❌ Количество должно быть больше 0!\n\n"
                "Попробуйте еще раз или /start для отмены"
            )
            return WAITING_GIFT_COUNT
        
        if count > 100:
            await update.message.reply_text(
                "⚠️ <b>Превышен лимит!</b>\n\n"
                f"Вы указали: <b>{count}</b>\n"
                f"Максимум: <b>100</b> подарков за раз\n\n"
                f"Попробуйте снова или /start для отмены",
                parse_mode="HTML"
            )
            return WAITING_GIFT_COUNT
        
        gift_id = context.user_data.get('send_gift_id')
        await send_gifts_execute(update.message, gift_id, count)
        return ConversationHandler.END
        
    except ValueError:
        await update.message.reply_text(
            "❌ Введите корректное число!\n\n"
            "Попробуйте еще раз или /start для отмены"
        )
        return WAITING_GIFT_COUNT

async def send_gifts_execute(message, gift_id, count):
    """Выполнение отправки подарков"""
    settings = load_settings()
    
    msg = await message.reply_text(
        f"📤 <b>Отправка подарков</b>\n\n"
        f"ID: {gift_id}\n"
        f"Количество: {count}\n\n"
        f"🔄 Подключение...",
        parse_mode="HTML"
    )
    
    try:
        host = settings.get("HOST")
        port = int(settings.get("port"))
        login1 = settings.get("LOGIN_1")
        key1 = settings.get("KEY_1")
        local_ip1 = settings.get("local_ip_1")
        client_ver1 = settings.get("client_ver_1")
        v1 = settings.get("ver_1")
        lang1 = settings.get("lang_1")
        login2 = settings.get("LOGIN_2")
        
        login_xml = f'<LOGIN v3="{local_ip1}" lang="{lang1}" v2="{client_ver1}" v="{v1}" p="{key1}" l="{login1}" />\x00'
        
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(login_xml.encode("utf-8"))
            sock.recv(8192)
            
            errors = 0
            success = 0
            
            for i in range(count):
                send_xml = f'<GH d="0" t1="" p="0" login="{login2}" buysouvenir="{gift_id}" />\x00'
                sock.sendall(send_xml.encode("utf-8"))
                resp = sock.recv(8192).decode("utf-8", errors="ignore")
                
                code_match = re.search(r'code="(\d+)"', resp)
                if code_match and code_match.group(1) == "0":
                    success += 1
                else:
                    errors += 1
                
                update_interval = max(5, count // 20)
                if (i + 1) % update_interval == 0 or (i + 1) == count:
                    progress = int(((i + 1) / count) * 100)
                    bar = "█" * (progress // 10) + "░" * (10 - progress // 10)
                    
                    await msg.edit_text(
                        f"📤 <b>Отправка подарков</b>\n\n"
                        f"{bar} {progress}%\n"
                        f"Отправлено: {i + 1}/{count}\n"
                        f"✅ Успешно: {success}\n"
                        f"❌ Ошибок: {errors}",
                        parse_mode="HTML"
                    )
                
                time.sleep(0.07)
        
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await msg.edit_text(
            f"✅ <b>Отправка завершена!</b>\n\n"
            f"📤 Отправлено: {count}\n"
            f"✅ Успешно: {success}\n"
            f"❌ Ошибок: {errors}",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await msg.edit_text(
            f"❌ <b>Ошибка:</b>\n<code>{str(e)}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

# ============================================================================
# ОЧИСТКА ИНВЕНТАРЯ
# ============================================================================

@require_access
async def clean_inventory_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение очистки"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, очистить инвентарь", callback_data="clean_yes"),
            InlineKeyboardButton("❌ Отмена", callback_data="menu"),
        ]
    ]
    
    await query.message.reply_text(
        "⚠️ <b>ВНИМАНИЕ!</b>\n\n"
        "Будут удалены <b>ВСЕ</b> предметы из инвентаря (section 0-3):\n"
        "• Оружие, броня, одежда\n"
        "• Расходники, патроны\n"
        "• Подарки и коробки\n\n"
        "⚠️ НЕОБРАТИМО!\n\n"
        "Вы уверены?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def clean_inventory_execute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Выполнение очистки инвентаря (только section 0-3)"""
    query = update.callback_query
    await query.answer()
    
    settings = load_settings()
    
    msg = await query.message.reply_text(
        "🧹 <b>Очистка инвентаря</b>\n\n🔄 Подключение...",
        parse_mode="HTML"
    )
    
    try:
        host = settings.get("HOST")
        port = int(settings.get("port"))
        login2 = settings.get("LOGIN_2")
        key2 = settings.get("KEY_2")
        local_ip2 = settings.get("local_ip_2")
        client_ver2 = settings.get("client_ver_2")
        v2 = settings.get("ver_2")
        lang2 = settings.get("lang_2")
        
        login_xml = f'<LOGIN v3="{local_ip2}" lang="{lang2}" v2="{client_ver2}" v="{v2}" p="{key2}" l="{login2}" />\x00'
        
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(login_xml.encode("utf-8"))
            sock.recv(65536)
            
            total_deleted = 0
            iteration = 0
            MAX_ITERATIONS = 50  # Защита от бесконечного цикла
            previous_count = None
            deleted_ids = set()  # Отслеживание удаленных ID
            
            while iteration < MAX_ITERATIONS:
                iteration += 1
                # ТОЛЬКО section 0-3 (инвентарь игрока)
                inv = get_inventory_items_socket(sock, include_all_sections=False)
                
                logger.info(f"Итерация {iteration}: найдено {len(inv)} предметов в section 0-3")
                
                # Фильтруем уже удаленные ID
                inv = [item for item in inv if item['id'] not in deleted_ids]
                logger.info(f"После фильтрации deleted_ids: {len(inv)} предметов")
                
                if not inv:
                    logger.info("Инвентарь пуст, завершаем очистку")
                    break
                
                # Проверка на зацикливание
                if previous_count == len(inv):
                    logger.warning(f"Количество предметов не изменилось: {len(inv)}. Возможно, предметы не удаляются!")
                    await msg.edit_text(
                        f"⚠️ <b>Предупреждение</b>\n\n"
                        f"Предметы не удаляются с сервера.\n"
                        f"Итерация {iteration}: найдено {len(inv)} предметов.\n\n"
                        f"Удалено до этого: {total_deleted}",
                        parse_mode="HTML"
                    )
                    time.sleep(3)
                    # Пробуем еще 2 раза, потом выходим
                    if iteration > 3:
                        break
                
                previous_count = len(inv)
                
                await msg.edit_text(
                    f"🧹 <b>Очистка инвентаря</b>\n\n"
                    f"🔄 Итерация {iteration}/{MAX_ITERATIONS}\n"
                    f"Найдено: {len(inv)}\n"
                    f"Удалено: {total_deleted}",
                    parse_mode="HTML"
                )
                
                for i, item in enumerate(inv):
                    # ВСЕГДА указываем count в команде DROP!
                    drop_xml = f'<DROP id="{item["id"]}" count="{item["count"]}"/>\x00'
                    
                    logger.info(f"Удаляю: {item['txt']} (ID: {item['id']}, section: {item['section']}, count: {item['count']})")
                    logger.debug(f"DROP команда: {drop_xml.strip()}")
                    
                    sock.settimeout(0.5)
                    sock.sendall(drop_xml.encode("utf-8"))
                    
                    # Пытаемся получить ответ для диагностики
                    try:
                        response = sock.recv(1024)
                        if response:
                            response_str = response.decode("utf-8", errors="ignore")
                            logger.debug(f"Ответ сервера: {response_str[:100]}")
                    except socket.timeout:
                        pass
                    
                    time.sleep(0.2)
                    
                    # Отмечаем как удаленный
                    deleted_ids.add(item['id'])
                    total_deleted += 1
                    
                    update_interval = max(30, len(inv) // 20)
                    if (i + 1) % update_interval == 0 or (i + 1) == len(inv):
                        progress = int(((i + 1) / len(inv)) * 100)
                        bar = "█" * (progress // 10) + "░" * (10 - progress // 10)
                        
                        await msg.edit_text(
                            f"🧹 <b>Очистка инвентаря</b>\n\n"
                            f"🔄 Итерация {iteration}/{MAX_ITERATIONS}\n"
                            f"{bar} {progress}%\n"
                            f"Удалено: {i + 1}/{len(inv)}\n"
                            f"Всего: {total_deleted}",
                            parse_mode="HTML"
                        )
            
            # Проверка на достижение лимита итераций
            if iteration >= MAX_ITERATIONS:
                logger.warning(f"Достигнут лимит итераций: {MAX_ITERATIONS}")
                keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
                await msg.edit_text(
                    f"⚠️ <b>Очистка остановлена</b>\n\n"
                    f"Достигнут лимит итераций: {MAX_ITERATIONS}\n"
                    f"Удалено: {total_deleted}\n\n"
                    f"Возможно, некоторые предметы нельзя удалить.\n"
                    f"Попробуйте запустить очистку снова.",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="HTML"
                )
                return
        
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await msg.edit_text(
            f"✅ <b>Очистка завершена!</b>\n\n"
            f"🗑 Удалено: <b>{total_deleted}</b>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
        
    except Exception as e:
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await msg.edit_text(
            f"❌ <b>Ошибка:</b>\n<code>{str(e)}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

# ============================================================================
# УПРАВЛЕНИЕ СПИСКОМ ПОДАРКОВ
# ============================================================================

@require_access
async def present_list_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню списка подарков"""
    query = update.callback_query
    await query.answer()
    
    names = load_present_list()
    
    text = "📋 <b>Список типов подарков:</b>\n\n"
    for i, name in enumerate(names, 1):
        text += f"{i}. {name}\n"
    
    keyboard = [
        [
            InlineKeyboardButton("➕ Добавить", callback_data="list_add"),
            InlineKeyboardButton("➖ Удалить", callback_data="list_delete"),
        ],
        [
            InlineKeyboardButton("🔄 Запросить с сервера", callback_data="list_request"),
        ],
        [
            InlineKeyboardButton("🏠 Меню", callback_data="menu")
        ]
    ]
    
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

async def present_list_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавление подарка в список"""
    query = update.callback_query
    await query.answer()
    
    await query.message.reply_text(
        "✏️ <b>Добавление подарка</b>\n\n"
        "Введите название подарка:\n"
        "<i>(например: Halloween box)</i>",
        parse_mode="HTML"
    )
    
    return WAITING_GIFT_NAME

async def receive_gift_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Получение названия подарка"""
    name = update.message.text.strip()
    
    if not name:
        await update.message.reply_text("❌ Название не может быть пустым!\n\n/start для отмены")
        return WAITING_GIFT_NAME
    
    names = load_present_list()
    
    if name in names:
        await update.message.reply_text(
            f"⚠️ Подарок <b>{name}</b> уже в списке!",
            parse_mode="HTML"
        )
        return ConversationHandler.END
    
    names.append(name)
    save_present_list(names)
    
    keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
    await update.message.reply_text(
        f"✅ Подарок <b>{name}</b> добавлен в список!",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )
    
    return ConversationHandler.END

async def present_list_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удаление подарка из списка"""
    query = update.callback_query
    await query.answer()
    
    names = load_present_list()
    
    keyboard = []
    for name in names:
        keyboard.append([InlineKeyboardButton(
            f"🗑 {name}",
            callback_data=f"listdel_{name}"
        )])
    
    keyboard.append([InlineKeyboardButton("❌ Отмена", callback_data="list")])
    
    await query.message.reply_text(
        "🗑 <b>Выберите подарок для удаления:</b>",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def present_list_delete_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение удаления"""
    query = update.callback_query
    name = query.data.split("_", 1)[1]
    
    await query.answer()
    
    names = load_present_list()
    
    if name in names:
        names.remove(name)
        save_present_list(names)
        
        keyboard = [[InlineKeyboardButton("📋 К списку", callback_data="list")]]
        await query.message.reply_text(
            f"✅ Подарок <b>{name}</b> удален!",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    else:
        await query.message.reply_text("❌ Подарок не найден!")

async def present_list_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запрос списка с сервера"""
    query = update.callback_query
    await query.answer()
    
    msg = await query.message.reply_text(
        "🔄 <b>Запрос данных с сервера...</b>",
        parse_mode="HTML"
    )
    
    try:
        gifts = request_available_gifts()
        
        if not gifts:
            raise Exception("Сервер вернул пустой список подарков")
        
        logger.info(f"Получено {len(gifts)} подарков с сервера")
        
        # Показываем все подарки с ID
        text = f"🎁 <b>Доступные подарки на сервере:</b>\n\n"
        text += f"Найдено: {len(gifts)}\n\n"
        
        for gift in gifts[:20]:  # Показываем максимум 20
            text += f"🎁 <b>{gift['txt']}</b>\n"
            text += f"   ID: <code>{gift['id']}</code>\n\n"
        
        if len(gifts) > 20:
            text += f"<i>...и еще {len(gifts) - 20} подарков</i>\n\n"
        
        # Кнопки действий
        keyboard = [
            [InlineKeyboardButton("✅ Обновить список", callback_data="list_update_confirm")],
            [
                InlineKeyboardButton("📋 К списку", callback_data="list"),
                InlineKeyboardButton("🏠 Меню", callback_data="menu")
            ]
        ]
        
        await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
        # Сохраняем в контексте для обновления
        context.bot_data['available_gifts'] = gifts
        
    except Exception as e:
        logger.error(f"Ошибка в present_list_request: {e}", exc_info=True)
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await msg.edit_text(
            f"❌ <b>Ошибка запроса с сервера</b>\n\n"
            f"<code>{str(e)}</code>\n\n"
            f"Возможные причины:\n"
            f"• Сервер недоступен\n"
            f"• Неверный LOGIN_1 или KEY_1\n"
            f"• Проблемы с сетью\n\n"
            f"Проверьте settings.json",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

async def present_list_update_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обновление списка подарков с сервера"""
    query = update.callback_query
    await query.answer()
    
    gifts = context.bot_data.get('available_gifts', [])
    
    if not gifts:
        await query.message.reply_text("❌ Нет данных. Сначала запросите список.")
        return
    
    # Обновляем список названиями с сервера
    names = [gift['txt'] for gift in gifts]
    save_present_list(names)
    
    keyboard = [
        [InlineKeyboardButton("📋 К списку", callback_data="list")],
        [InlineKeyboardButton("🏠 Меню", callback_data="menu")]
    ]
    
    await query.message.reply_text(
        f"✅ <b>Список обновлен!</b>\n\n"
        f"Добавлено: {len(names)} подарков",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

# ============================================================================
# ML СТАТИСТИКА
# ============================================================================

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """ML статистика дропа"""
    query = update.callback_query if update.callback_query else None
    message = query.message if query else update.message
    
    if query:
        await query.answer()
    
    try:
        from drop_analyzer import DropAnalyzer
        analyzer = DropAnalyzer()
        
        stats = analyzer.get_total_stats()
        if not stats:
            keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
            await message.reply_text(
                "📊 <b>ML Статистика</b>\n\n"
                "❌ Нет данных.\n\n"
                "Откройте подарки через <b>Анализ</b>",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="HTML"
            )
            return
        
        probs = analyzer.calculate_probabilities()
        predictions = analyzer.predict_next_opening(100)
        
        text = (
            f"📊 <b>ML Анализ дропа</b>\n\n"
            f"📈 Сессий: {stats['sessions_count']}\n"
            f"📦 Открыто: {stats['total_gifts']}\n\n"
            f"<b>Топ-10 по вероятности:</b>\n\n"
        )
        
        sorted_probs = sorted(probs.items(), key=lambda x: x[1]['probability'], reverse=True)
        
        for item, data in sorted_probs[:10]:
            prob = data['probability']
            count = data['count']
            
            if prob >= 50:
                emoji = "🔴"
            elif prob >= 20:
                emoji = "🟠"
            elif prob >= 10:
                emoji = "🟡"
            else:
                emoji = "🟢"
            
            text += f"{emoji} <b>{item}</b>\n"
            text += f"   {count} шт | {prob:.1f}%\n"
        
        text += (
            f"\n<b>🔮 Прогноз на 100 подарков:</b>\n"
        )
        
        sorted_pred = sorted(predictions.items(), key=lambda x: x[1]['expected'], reverse=True)
        for item, data in sorted_pred[:5]:
            text += f"  • {item}: ~{data['expected']:.0f} шт\n"
        
        keyboard = [
            [InlineKeyboardButton("🔄 Обновить", callback_data="stats")],
            [InlineKeyboardButton("🏠 Меню", callback_data="menu")]
        ]
        
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
        
    except ImportError:
        text = (
            "📊 <b>ML Статистика</b>\n\n"
            "⚠️ Требуется numpy для ML анализа\n\n"
            "Установите: <code>pip install numpy</code>"
        )
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    except Exception as e:
        keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
        await message.reply_text(
            f"❌ <b>Ошибка:</b>\n<code>{str(e)}</code>",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

# ============================================================================
# ЭКСПОРТ ДАННЫХ
# ============================================================================

@require_access
async def export_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню экспорта"""
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("📊 Статистика дропа (JSON)", callback_data="export_stats")],
        [InlineKeyboardButton("📋 Список подарков (JSON)", callback_data="export_list")],
        [InlineKeyboardButton("📈 Полный отчет (TXT)", callback_data="export_report")],
        [InlineKeyboardButton("🏠 Меню", callback_data="menu")]
    ]
    
    await query.message.reply_text(
        "💾 <b>Экспорт данных</b>\n\n"
        "Выберите, что экспортировать:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

async def export_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт статистики дропа"""
    query = update.callback_query
    await query.answer()
    
    try:
        with open("drop_statistics.json", "r", encoding="utf-8") as f:
            data = f.read()
        
        document = io.BytesIO(data.encode('utf-8'))
        document.name = f"drop_stats_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        await query.message.reply_document(
            document=document,
            caption="📊 <b>Статистика дропа</b>",
            parse_mode="HTML"
        )
    except FileNotFoundError:
        await query.message.reply_text("❌ Нет данных для экспорта")
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка: {str(e)}")

async def export_present_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт списка подарков"""
    query = update.callback_query
    await query.answer()
    
    try:
        with open("present_list.json", "r", encoding="utf-8") as f:
            data = f.read()
        
        document = io.BytesIO(data.encode('utf-8'))
        document.name = f"present_list_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        await query.message.reply_document(
            document=document,
            caption="📋 <b>Список подарков</b>",
            parse_mode="HTML"
        )
    except Exception as e:
        await query.message.reply_text(f"❌ Ошибка: {str(e)}")

async def export_full_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Экспорт полного отчета"""
    query = update.callback_query
    await query.answer()
    
    try:
        from drop_analyzer import DropAnalyzer
        analyzer = DropAnalyzer()
        
        stats = analyzer.get_total_stats()
        if not stats:
            await query.message.reply_text("❌ Нет данных для отчета")
            return
        
        probs = analyzer.calculate_probabilities()
        predictions = analyzer.predict_next_opening(100)
        
        # Формируем текстовый отчет
        report = f"""
═══════════════════════════════════════
  ОТЧЕТ ПО ДРОПУ ИЗ ПОДАРКОВ
═══════════════════════════════════════

Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

ОБЩАЯ СТАТИСТИКА:
─────────────────────────────────────
Всего сессий: {stats['sessions_count']}
Открыто подарков: {stats['total_gifts']}
Уникальных предметов: {len(stats['total_items'])}

ВЕРОЯТНОСТИ ДРОПА:
─────────────────────────────────────
"""
        sorted_probs = sorted(probs.items(), key=lambda x: x[1]['probability'], reverse=True)
        
        for item, data in sorted_probs:
            report += f"{item}\n"
            report += f"  Количество: {data['count']}\n"
            report += f"  Вероятность: {data['probability']:.2f}%\n"
            report += f"  На подарок: {data['per_gift']:.4f}\n"
            report += f"  Редкость: {data['rarity']}\n\n"
        
        report += f"""
ПРОГНОЗ НА 100 ПОДАРКОВ:
─────────────────────────────────────
"""
        sorted_pred = sorted(predictions.items(), key=lambda x: x[1]['expected'], reverse=True)
        
        for item, data in sorted_pred:
            report += f"{item}: {data['expected']:.1f} (95% CI: {data['min_95']:.1f}-{data['max_95']:.1f})\n"
        
        report += f"""
═══════════════════════════════════════
Сгенерировано GiftApp Bot
═══════════════════════════════════════
"""
        
        document = io.BytesIO(report.encode('utf-8'))
        document.name = f"full_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        await query.message.reply_document(
            document=document,
            caption="📈 <b>Полный отчет</b>",
            parse_mode="HTML"
        )
        
    except Exception as e:
        logger.error(f"Ошибка экспорта: {e}", exc_info=True)
        await query.message.reply_text(f"❌ Ошибка: {str(e)}")

# ============================================================================
# ПОМОЩЬ И ИНФОРМАЦИЯ
# ============================================================================

async def show_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подробная справка по работе с ботом"""
    user_id = update.effective_user.id
    user_is_admin = is_admin(user_id)
    
    text = (
        "ℹ️ <b>Справка GiftApp Bot</b>\n"
        "<i>Для игры Timezero Reloaded</i>\n\n"
        
        "⚠️ <b>ВАЖНО ПЕРЕД НАЧАЛОМ:</b>\n"
        "1️⃣ Рекомендуется <b>очистить инвентарь</b> перед анализом подарков!\n"
        "   Используйте функцию 🧹 Очистка.\n\n"
        "2️⃣ <b>⚠️ ТОЛЬКО ОДИН ПОЛЬЗОВАТЕЛЬ ОДНОВРЕМЕННО!</b>\n"
        "   Бот использует один игровой аккаунт.\n"
        "   Дождитесь завершения операций других пользователей.\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>📋 ОСНОВНЫЕ ФУНКЦИИ:</b>\n\n"
        
        "📦 <b>Анализ подарков</b>\n"
        "Автоматически открывает ВСЕ подарки в инвентаре.\n"
        "• Поддержка вложенных подарков (рекурсия)\n"
        "• Прогресс-бар в реальном времени\n"
        "• Подробная статистика дропа\n"
        "• Данные сохраняются для ML анализа\n\n"
        
        "📤 <b>Отправить подарки</b>\n"
        "Отправка подарков получателю (LOGIN_2).\n"
        "• Выбор подарка из списка с ID\n"
        "• Количество: 10/25/50/100 или свое\n"
        "• Макс. 100 за раз (автопредупреждение)\n"
        "• Отображение успехов/ошибок\n\n"
        
        "🧹 <b>Очистка инвентаря</b>\n"
        "Удаляет ВСЕ предметы (section 0-3).\n"
        "• Итеративная обработка (600+ предметов)\n"
        "• Прогресс-бар\n"
        "• Подтверждение перед удалением\n"
        "• ⚠️ НЕОБРАТИМО!\n\n"
        
        "📋 <b>Управление списком</b>\n"
        "Типы предметов, считающихся подарками.\n"
        "• ➕ Добавить вручную\n"
        "• ➖ Удалить из списка\n"
        "• 🔄 Запросить с сервера (с ID!)\n"
        "• ✅ Обновить список\n\n"
        
        "📊 <b>ML Статистика</b>\n"
        "Машинное обучение для анализа дропа.\n"
        "• Вероятности выпадения\n"
        "• Прогноз на 100 подарков\n"
        "• Классификация редкости\n"
        "• Топ-предметы\n\n"
        
        "💾 <b>Экспорт данных</b>\n"
        "• JSON: статистика дропа\n"
        "• JSON: список подарков\n"
        "• TXT: полный отчет\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>🎮 КАК ПОЛЬЗОВАТЬСЯ:</b>\n\n"
        
        "1️⃣ Очистите инвентарь (🧹 Очистка)\n"
        "2️⃣ Отправьте себе подарки (📤 Отправить)\n"
        "3️⃣ Запустите анализ (📦 Анализ)\n"
        "4️⃣ Посмотрите статистику (📊 ML Статистика)\n"
        "5️⃣ Экспортируйте данные (💾 Экспорт)\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<b>⌨️ КОМАНДЫ:</b>\n\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/stats - ML статистика\n"
    )
    
    if user_is_admin:
        text += (
            "\n<b>👑 АДМИН-КОМАНДЫ:</b>\n\n"
            "/adduser &lt;ID&gt; - Добавить пользователя\n"
            "/removeuser &lt;ID&gt; - Удалить пользователя\n"
            "/addadmin &lt;ID&gt; - Добавить админа\n"
            "/users - Список пользователей\n"
            "/restart - Перезапуск бота\n\n"
            
            "<i>Пример: /adduser 123456789</i>\n\n"
        )
    
    text += (
        "\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔴 <b>РЕДКОСТЬ ДРОПА:</b>\n"
        "🔴 Легендарный (≥50%)\n"
        "🟠 Эпический (20-50%)\n"
        "🟡 Редкий (10-20%)\n"
        "🟢 Необычный (<10%)\n\n"
        
        "━━━━━━━━━━━━━━━━━━━━━\n\n"
        
        "<i>Создано для Timezero Reloaded</i>"
    )
    
    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="menu")]]
    
    # Проверяем тип вызова - callback query или обычное сообщение
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )
    else:
        await update.effective_message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="HTML"
        )

# ============================================================================
# УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ (АДМИНЫ)
# ============================================================================

@require_admin
async def add_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить пользователя (команда)"""
    if not context.args:
        await update.message.reply_text(
            "📝 <b>Использование:</b>\n\n"
            "<code>/adduser &lt;USER_ID&gt;</code>\n\n"
            "Пример:\n"
            "<code>/adduser 123456789</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        new_user_id = int(context.args[0])
        
        if add_user(new_user_id, "user"):
            await update.message.reply_text(
                f"✅ Пользователь <code>{new_user_id}</code> добавлен!",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Пользователь <code>{new_user_id}</code> уже в списке.",
                parse_mode="HTML"
            )
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID!")

@require_admin
async def remove_user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Удалить пользователя (команда)"""
    if not context.args:
        await update.message.reply_text(
            "📝 <b>Использование:</b>\n\n"
            "<code>/removeuser &lt;USER_ID&gt;</code>\n\n"
            "Пример:\n"
            "<code>/removeuser 123456789</code>\n\n"
            "⚠️ Нельзя удалить администратора!",
            parse_mode="HTML"
        )
        return
    
    try:
        user_id_to_remove = int(context.args[0])
        
        if is_admin(user_id_to_remove):
            await update.message.reply_text(
                "🔒 <b>Ошибка!</b>\n\n"
                "Нельзя удалить администратора!\n"
                "Только пользователей можно удалять.",
                parse_mode="HTML"
            )
            return
        
        if remove_user(user_id_to_remove):
            await update.message.reply_text(
                f"✅ Пользователь <code>{user_id_to_remove}</code> удален!",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Пользователь <code>{user_id_to_remove}</code> не найден.",
                parse_mode="HTML"
            )
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID!")

@require_admin
async def add_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Добавить администратора (команда)"""
    if not context.args:
        await update.message.reply_text(
            "📝 <b>Использование:</b>\n\n"
            "<code>/addadmin &lt;USER_ID&gt;</code>\n\n"
            "Пример:\n"
            "<code>/addadmin 123456789</code>",
            parse_mode="HTML"
        )
        return
    
    try:
        new_admin_id = int(context.args[0])
        
        if add_user(new_admin_id, "admin"):
            await update.message.reply_text(
                f"✅ Администратор <code>{new_admin_id}</code> добавлен!",
                parse_mode="HTML"
            )
        else:
            await update.message.reply_text(
                f"⚠️ Пользователь <code>{new_admin_id}</code> уже администратор.",
                parse_mode="HTML"
            )
    except ValueError:
        await update.message.reply_text("❌ Неверный формат ID!")

@require_admin
async def list_users_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показать всех пользователей"""
    users_data = get_all_users()
    
    text = "👥 <b>Список пользователей</b>\n\n"
    
    text += f"👑 <b>Администраторы ({len(users_data['admins'])}):</b>\n"
    for admin_id in users_data['admins']:
        text += f"  • <code>{admin_id}</code>\n"
    
    text += f"\n👤 <b>Пользователи ({len(users_data['users'])}):</b>\n"
    if users_data['users']:
        for user_id in users_data['users']:
            text += f"  • <code>{user_id}</code>\n"
    else:
        text += "  <i>Список пуст</i>\n"
    
    text += (
        "\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Команды управления:</b>\n"
        "/adduser &lt;ID&gt; - Добавить\n"
        "/removeuser &lt;ID&gt; - Удалить\n"
        "/addadmin &lt;ID&gt; - Сделать админом"
    )
    
    await update.message.reply_text(text, parse_mode="HTML")

@require_admin
async def manage_users_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню управления пользователями"""
    query = update.callback_query
    await query.answer()
    
    users_data = get_all_users()
    
    text = (
        "👥 <b>Управление пользователями</b>\n\n"
        f"👑 Администраторов: {len(users_data['admins'])}\n"
        f"👤 Пользователей: {len(users_data['users'])}\n\n"
        "Используйте команды:\n"
        "<code>/adduser ID</code> - Добавить\n"
        "<code>/removeuser ID</code> - Удалить\n"
        "<code>/addadmin ID</code> - Админ\n"
        "<code>/users</code> - Список всех"
    )
    
    keyboard = [[InlineKeyboardButton("🏠 Главное меню", callback_data="menu")]]
    
    await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")

@require_admin
async def restart_bot(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Перезапуск бота (только в Docker)"""
    query = update.callback_query
    await query.answer()
    
    # Подтверждение
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, перезапустить", callback_data="restart_confirm"),
            InlineKeyboardButton("❌ Отмена", callback_data="menu"),
        ]
    ]
    
    await query.message.reply_text(
        "🔄 <b>Перезапуск бота</b>\n\n"
        "Бот будет перезапущен.\n"
        "Загрузятся обновленные настройки.\n\n"
        "Продолжить?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="HTML"
    )

@require_admin
async def restart_bot_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтвержденный перезапуск"""
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        message = query.message
    else:
        message = update.message
    
    await message.reply_text(
        "🔄 <b>Перезапуск...</b>\n\n"
        "Бот будет доступен через 5-10 секунд.",
        parse_mode="HTML"
    )
    
    # Перезапуск (работает в Docker с restart policy)
    os.execv(sys.executable, ['python'] + sys.argv)

@require_access
async def check_inventory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка инвентаря (диагностика)"""
    msg = await update.message.reply_text(
        "🔍 <b>Проверка инвентаря...</b>",
        parse_mode="HTML"
    )
    
    settings = load_settings()
    
    try:
        host = settings.get("HOST")
        port = int(settings.get("port"))
        login2 = settings.get("LOGIN_2")
        key2 = settings.get("KEY_2")
        local_ip2 = settings.get("local_ip_2")
        client_ver2 = settings.get("client_ver_2")
        v2 = settings.get("ver_2")
        lang2 = settings.get("lang_2")
        
        login_xml = f'<LOGIN v3="{local_ip2}" lang="{lang2}" v2="{client_ver2}" v="{v2}" p="{key2}" l="{login2}" />\x00'
        
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.sendall(login_xml.encode("utf-8"))
            sock.recv(65536)
            
            # Получаем инвентарь
            getme_xml = '<GETME />\x00'
            sock.sendall(getme_xml.encode("utf-8"))
            
            data = b''
            sock.settimeout(1.3)
            for _ in range(8):
                try:
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                    if b'</MYPARAM>' in chunk:
                        break
                except socket.timeout:
                    break
            
            data = data.decode("utf-8", errors="ignore")
            
            # Парсим ВСЕ предметы
            all_items = []
            for match in re.finditer(r'<O ([^>]+)\/>', data):
                attrs = match.group(1)
                id_ = re.search(r'id="([^"]+)"', attrs)
                txt = re.search(r'txt="([^"]+)"', attrs)
                section = re.search(r'section="(\d+)"', attrs)
                count = re.search(r'(?<!max_)count="(\d+)"', attrs)
                
                if id_ and txt and section:
                    all_items.append({
                        "txt": txt.group(1),
                        "section": section.group(1),
                        "count": int(count.group(1)) if count else 1
                    })
            
            # Группируем по секциям
            by_section = defaultdict(list)
            for item in all_items:
                by_section[item['section']].append(item)
            
            text = "🔍 <b>Инвентарь:</b>\n\n"
            
            if not all_items:
                text += "✅ Инвентарь полностью пуст!\n"
            else:
                text += f"📊 Всего предметов: {len(all_items)}\n\n"
                
                for section in sorted(by_section.keys()):
                    items = by_section[section]
                    text += f"<b>Section {section}:</b> {len(items)} шт\n"
                    
                    # Показываем первые 5 предметов
                    for item in items[:5]:
                        text += f"  • {item['txt']}"
                        if item['count'] > 1:
                            text += f" x{item['count']}"
                        text += "\n"
                    
                    if len(items) > 5:
                        text += f"  <i>...и еще {len(items) - 5} предметов</i>\n"
                    text += "\n"
                
                # Предметы в section 0-3 (должны удаляться)
                cleanable = [item for item in all_items if item['section'] in {"0", "1", "2", "3"}]
                not_cleanable = [item for item in all_items if item['section'] not in {"0", "1", "2", "3"}]
                
                if cleanable:
                    text += f"⚠️ Осталось {len(cleanable)} предметов в section 0-3!\n"
                    text += "Эти предметы ДОЛЖНЫ удаляться.\n\n"
                
                if not_cleanable:
                    text += f"ℹ️ {len(not_cleanable)} предметов в других секциях.\n"
                    text += "Эти предметы НЕ удаляются (section ≠ 0-3).\n"
            
            keyboard = [[InlineKeyboardButton("🏠 Меню", callback_data="menu")]]
            await msg.edit_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML")
    
    except Exception as e:
        await msg.edit_text(f"❌ Ошибка: {str(e)}", parse_mode="HTML")

# ============================================================================
# ОБРАБОТЧИКИ КНОПОК
# ============================================================================

@require_access
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Главный обработчик кнопок"""
    query = update.callback_query
    
    if query.data == "menu":
        await query.answer()
        await start(update, context)
    elif query.data == "analyze":
        await analyze_presents(update, context)
    elif query.data == "send":
        await send_gifts_menu(update, context)
    elif query.data.startswith("send_") and not query.data.startswith("sendcount"):
        await send_gifts_choose_count(update, context)
    elif query.data.startswith("sendcount_"):
        count_str = query.data.split("_")[1]
        if count_str == "custom":
            await send_gifts_custom_count(update, context)
        else:
            await query.answer()
            count = int(count_str)
            gift_id = context.user_data.get('send_gift_id')
            await send_gifts_execute(query.message, gift_id, count)
    elif query.data == "clean":
        await clean_inventory_confirm(update, context)
    elif query.data == "clean_yes":
        await clean_inventory_execute(update, context)
    elif query.data == "list":
        await present_list_menu(update, context)
    elif query.data == "list_add":
        await present_list_add(update, context)
    elif query.data == "list_delete":
        await present_list_delete(update, context)
    elif query.data.startswith("listdel_"):
        await present_list_delete_confirm(update, context)
    elif query.data == "list_request":
        await present_list_request(update, context)
    elif query.data == "list_update_confirm":
        await present_list_update_confirm(update, context)
    elif query.data == "stats":
        await show_statistics(update, context)
    elif query.data == "export":
        await export_menu(update, context)
    elif query.data == "export_stats":
        await export_statistics(update, context)
    elif query.data == "export_list":
        await export_present_list(update, context)
    elif query.data == "export_report":
        await export_full_report(update, context)
    elif query.data == "manage_users":
        await manage_users_menu(update, context)
    elif query.data == "restart_bot":
        await restart_bot(update, context)
    elif query.data == "restart_confirm":
        await restart_bot_confirm(update, context)
    elif query.data == "help":
        await show_help(update, context)

# ============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# ============================================================================

def main():
    """Запуск бота"""
    TOKEN = "8318962550:AAG6GEDfwLyVrRwMe2tzJoV-JsKLFiTXdzs"
    
    application = Application.builder().token(TOKEN).build()
    
    # ConversationHandler для добавления подарка
    conv_add = ConversationHandler(
        entry_points=[CallbackQueryHandler(present_list_add, pattern="^list_add$")],
        states={
            WAITING_GIFT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_gift_name)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    # ConversationHandler для своего количества
    conv_count = ConversationHandler(
        entry_points=[CallbackQueryHandler(send_gifts_custom_count, pattern="^sendcount_custom$")],
        states={
            WAITING_GIFT_COUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_custom_count)],
        },
        fallbacks=[CommandHandler("start", start)],
    )
    
    # Регистрируем обработчики
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", show_help))
    application.add_handler(CommandHandler("stats", show_statistics))
    application.add_handler(CommandHandler("check", check_inventory))
    
    # Админ-команды
    application.add_handler(CommandHandler("adduser", add_user_command))
    application.add_handler(CommandHandler("removeuser", remove_user_command))
    application.add_handler(CommandHandler("addadmin", add_admin_command))
    application.add_handler(CommandHandler("users", list_users_command))
    application.add_handler(CommandHandler("restart", restart_bot_confirm))
    
    # ConversationHandlers
    application.add_handler(conv_add)
    application.add_handler(conv_count)
    
    # Обработчик кнопок
    application.add_handler(CallbackQueryHandler(button_handler))
    
    logger.info("🤖 Бот запущен!")
    print("\n" + "="*50)
    print("🤖 TELEGRAM BOT ЗАПУЩЕН!")
    print("="*50)
    print("📱 Найдите вашего бота в Telegram")
    print("📤 Отправьте /start для начала работы")
    print("="*50 + "\n")
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

