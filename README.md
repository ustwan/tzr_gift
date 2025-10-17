# 🎁 TZR Gift Bot

Telegram-бот для управления подарками в игре **Timezero Reloaded**.

## 📋 Возможности

- **🎁 Анализ подарков**: открытие подарков с подсчётом статистики и ML-аналитикой дропа
- **📋 Управление списком**: редактирование списка подарков, запрос с сервера
- **📤 Отправка подарков**: интерактивный выбор из доступных подарков (до 100 за раз)
- **🧹 Очистка инвентаря**: автоматическое удаление предметов из секций 0-3
- **📊 Экспорт данных**: выгрузка статистики в JSON
- **👥 Управление доступом**: система администраторов и пользователей

## 🚀 Быстрый старт (Docker)

### Предварительные требования

- Docker и Docker Compose
- Telegram Bot Token (получить у [@BotFather](https://t.me/BotFather))
- Доступ к серверу игры

### Установка

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/ustwan/tzr_gift.git
cd tzr_gift
```

2. **Создайте `settings.json`:**
```bash
cp settings.example.json settings.json
nano settings.json
```

Заполните параметры:
```json
{
  "server": {
    "host": "ваш_сервер.com",
    "port": 5555
  },
  "account": {
    "login": "ваш_логин",
    "password": "ваш_пароль"
  },
  "telegram": {
    "bot_token": "8318962550:AAG6GEDfwLyVrRwMe2tzJoV-JsKLFiTXdzs",
    "chat_id": ""
  }
}
```

3. **Создайте `users.json` с первым администратором:**
```bash
cp users.example.json users.json
nano users.json
```

Укажите свой Telegram ID (узнать можно у [@userinfobot](https://t.me/userinfobot)):
```json
{
  "admins": [
    123456789
  ],
  "users": []
}
```

4. **Создайте `present_list.json`:**
```bash
echo '{"presents": []}' > present_list.json
```

5. **Запустите Docker контейнер:**
```bash
docker-compose up -d
```

6. **Проверьте логи:**
```bash
docker-compose logs -f gift-bot
```

### Остановка/Перезапуск

```bash
# Остановить
docker-compose down

# Перезапустить
docker-compose restart

# Обновить код и перезапустить
git pull
docker-compose up -d --build
```

## 🐍 Установка без Docker (локально)

### Требования

- Python 3.13+
- pip

### Установка

1. **Клонируйте репозиторий:**
```bash
git clone https://github.com/ustwan/tzr_gift.git
cd tzr_gift
```

2. **Создайте виртуальное окружение:**
```bash
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate  # Windows
```

3. **Установите зависимости:**
```bash
pip install -r bot_requirements.txt
```

4. **Создайте конфигурационные файлы** (см. раздел Docker выше):
   - `settings.json`
   - `users.json`
   - `present_list.json`

5. **Запустите бота:**
```bash
python gift_bot.py
```

## 📖 Использование

### Для пользователей

1. Запустите бота: `/start`
2. Доступные команды:
   - **🎁 Анализ** — открыть подарки и посмотреть статистику
   - **📋 Список** — просмотр/редактирование списка подарков
   - **📤 Отправить** — отправка подарков
   - **🧹 Очистить** — очистка инвентаря (секции 0-3)
   - **📊 Экспорт** — выгрузка статистики

### Для администраторов

Дополнительные команды:
- `/adduser <telegram_id>` — добавить пользователя
- `/removeuser <telegram_id>` — удалить пользователя
- `/users` — список всех пользователей
- `/restart` — перезапустить бота
- `/help` — справка

**Кнопки меню:**
- **👥 Пользователи** — управление доступом
- **🔄 Перезапуск** — рестарт бота

## ⚙️ Конфигурация

### settings.json

```json
{
  "server": {
    "host": "адрес_сервера",     // Адрес игрового сервера
    "port": 5555                  // Порт сервера
  },
  "account": {
    "login": "логин",             // Логин от аккаунта
    "password": "пароль"          // Пароль
  },
  "telegram": {
    "bot_token": "токен_бота",    // Токен от @BotFather
    "chat_id": ""                 // Не обязательно
  }
}
```

### users.json

```json
{
  "admins": [123456789],          // Telegram ID администраторов
  "users": [987654321]            // Telegram ID обычных пользователей
}
```

### present_list.json

```json
{
  "presents": [
    {"name": "Halloween box", "id": "3"}
  ]
}
```

## 🔧 Обновление

### Docker

```bash
cd tzr_gift
git pull
docker-compose up -d --build
```

### Локально

```bash
cd tzr_gift
git pull
source venv/bin/activate  # если окружение не активировано
pip install -r bot_requirements.txt --upgrade
python gift_bot.py
```

## 🐛 Решение проблем

### Бот не отвечает

1. Проверьте логи:
```bash
docker-compose logs -f gift-bot  # Docker
# или
tail -f bot_latest.log  # локально
```

2. Убедитесь, что токен бота правильный
3. Проверьте доступ к серверу игры

### "Не удалось подключиться к серверу"

- Проверьте `host` и `port` в `settings.json`
- Убедитесь, что сервер доступен

### "Ошибка авторизации"

- Проверьте `login` и `password` в `settings.json`

### Бот не находит подарки

1. Выполните команду: **📋 Список → 🔄 Запросить с сервера**
2. Если не помогло — добавьте вручную: **📋 Список → ✏️ Редактировать**

### Очистка не удаляет все предметы

- Используйте команду `/check` для диагностики
- Убедитесь, что инвентарь очищен перед анализом подарков

## 📁 Структура проекта

```
tzr_gift/
├── gift_bot.py              # Основной файл бота
├── access_control.py        # Управление доступом
├── drop_analyzer.py         # ML-аналитика дропа
├── bot_requirements.txt     # Python зависимости
├── Dockerfile               # Docker образ
├── docker-compose.yml       # Docker Compose конфигурация
├── settings.example.json    # Пример настроек
├── users.example.json       # Пример списка пользователей
├── settings.json            # Настройки (не в git)
├── users.json               # Пользователи (не в git)
├── present_list.json        # Список подарков (не в git)
└── README.md                # Документация
```

## ⚠️ Важные замечания

1. **Всегда очищайте инвентарь перед анализом подарков** — это обеспечит корректный подсчёт дропа
2. **Максимум 100 подарков за раз** — ограничение сервера
3. **Бот работает только с секциями 0-3** — секция 100000 (перки/скиллы) игнорируется
4. **Не делитесь `settings.json` и `users.json`** — они содержат конфиденциальные данные

## 🤝 Поддержка

При возникновении проблем:
1. Проверьте раздел **Решение проблем**
2. Изучите логи бота
3. Используйте команду `/check` для диагностики

## 📜 Лицензия

MIT License

---

**Timezero Reloaded Gift Bot** — автоматизация управления подарками в игре 🎮
