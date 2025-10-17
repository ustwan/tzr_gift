# 🚀 Инструкция по развертыванию TZR Gift Bot

## Вариант 1: Docker (рекомендуется) 🐳

### Шаг 1: Установите Docker

**Linux (Ubuntu/Debian):**
```bash
sudo apt update
sudo apt install docker.io docker-compose -y
sudo systemctl start docker
sudo systemctl enable docker
```

**macOS:**
```bash
brew install docker docker-compose
# Или скачайте Docker Desktop: https://www.docker.com/products/docker-desktop
```

**Windows:**
Скачайте Docker Desktop: https://www.docker.com/products/docker-desktop

### Шаг 2: Клонируйте проект

```bash
git clone https://github.com/ustwan/tzr_gift.git
cd tzr_gift
```

### Шаг 3: Настройте конфигурацию

**Создайте settings.json:**
```bash
cp settings.example.json settings.json
nano settings.json
```

Заполните:
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
    "bot_token": "токен_от_BotFather",
    "chat_id": ""
  }
}
```

**Создайте users.json:**
```bash
cp users.example.json users.json
nano users.json
```

Укажите ваш Telegram ID (узнайте у @userinfobot):
```json
{
  "admins": [123456789],
  "users": []
}
```

**Создайте present_list.json:**
```bash
echo '{"presents": []}' > present_list.json
```

### Шаг 4: Запустите бота

```bash
docker-compose up -d
```

### Шаг 5: Проверьте работу

```bash
# Смотрим логи
docker-compose logs -f gift-bot

# Проверяем статус
docker-compose ps
```

Откройте Telegram и напишите боту `/start`

### Управление контейнером

```bash
# Остановить
docker-compose down

# Перезапустить
docker-compose restart

# Обновить и перезапустить
git pull
docker-compose up -d --build
```

---

## Вариант 2: VPS без Docker 🖥️

### Шаг 1: Подключитесь к VPS

```bash
ssh user@your-vps-ip
```

### Шаг 2: Установите Python 3.13+

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install python3 python3-pip python3-venv -y
```

### Шаг 3: Клонируйте проект

```bash
cd ~
git clone https://github.com/ustwan/tzr_gift.git
cd tzr_gift
```

### Шаг 4: Создайте виртуальное окружение

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r bot_requirements.txt
```

### Шаг 5: Настройте конфигурацию

```bash
cp settings.example.json settings.json
nano settings.json

cp users.example.json users.json
nano users.json

echo '{"presents": []}' > present_list.json
```

### Шаг 6: Запустите бота

**Вариант A: В tmux/screen (простой способ)**
```bash
# Установите tmux
sudo apt install tmux -y

# Запустите сессию
tmux new -s gift_bot

# Активируйте окружение и запустите бота
source venv/bin/activate
python gift_bot.py

# Выйдите из tmux (бот продолжит работу)
# Нажмите: Ctrl+B, затем D

# Вернуться в сессию:
tmux attach -t gift_bot
```

**Вариант B: Systemd service (рекомендуется для VPS)**
```bash
sudo nano /etc/systemd/system/gift-bot.service
```

Вставьте:
```ini
[Unit]
Description=TZR Gift Bot
After=network.target

[Service]
Type=simple
User=your-username
WorkingDirectory=/home/your-username/tzr_gift
ExecStart=/home/your-username/tzr_gift/venv/bin/python gift_bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Замените `your-username` на ваше имя пользователя.

Запустите:
```bash
sudo systemctl daemon-reload
sudo systemctl enable gift-bot
sudo systemctl start gift-bot

# Проверьте статус
sudo systemctl status gift-bot

# Логи
sudo journalctl -u gift-bot -f
```

---

## Вариант 3: Локально (для тестирования) 💻

### Windows

1. **Установите Python 3.13:**
   - Скачайте с https://www.python.org/downloads/
   - При установке отметьте "Add Python to PATH"

2. **Откройте PowerShell:**
```powershell
cd C:\Users\YourName\Downloads
git clone https://github.com/ustwan/tzr_gift.git
cd tzr_gift

python -m venv venv
.\venv\Scripts\activate
pip install -r bot_requirements.txt

copy settings.example.json settings.json
copy users.example.json users.json
notepad settings.json  # Отредактируйте
notepad users.json     # Отредактируйте

echo {"presents": []} > present_list.json

python gift_bot.py
```

### macOS

```bash
cd ~/Downloads
git clone https://github.com/ustwan/tzr_gift.git
cd tzr_gift

python3 -m venv venv
source venv/bin/activate
pip install -r bot_requirements.txt

cp settings.example.json settings.json
cp users.example.json users.json
nano settings.json  # Отредактируйте
nano users.json     # Отредактируйте

echo '{"presents": []}' > present_list.json

python gift_bot.py
```

---

## 🔍 Проверка работы

После запуска:

1. Откройте Telegram
2. Найдите вашего бота по username
3. Напишите `/start`
4. Должно появиться меню с кнопками

Если бот не отвечает — проверьте логи!

---

## 🛠️ Решение проблем

### "Не удалось подключиться к серверу"
- Проверьте `host` и `port` в `settings.json`
- Убедитесь что сервер доступен: `telnet your-server.com 5555`

### "Ошибка авторизации"
- Проверьте `login` и `password` в `settings.json`

### Бот не отвечает
1. Проверьте логи (см. выше)
2. Убедитесь что токен бота правильный
3. Проверьте что ваш Telegram ID в `users.json`

### Порты заняты (Docker)
Измените порты в `docker-compose.yml` если нужно

---

## 📊 Мониторинг

### Docker
```bash
# Логи
docker-compose logs -f gift-bot

# Статус
docker-compose ps

# Использование ресурсов
docker stats
```

### Systemd
```bash
# Логи
sudo journalctl -u gift-bot -f

# Статус
sudo systemctl status gift-bot

# Перезапуск
sudo systemctl restart gift-bot
```

### Локально
Логи сохраняются в `bot_latest.log`

---

## 🔐 Безопасность

1. **Не делитесь файлами конфигурации!**
   - `settings.json` содержит пароли
   - `users.json` — список доступа

2. **На VPS используйте firewall:**
```bash
sudo ufw allow 22    # SSH
sudo ufw enable
```

3. **Регулярно обновляйте код:**
```bash
cd tzr_gift
git pull
# Перезапустите бота
```

---

**Готово! Ваш бот работает! 🎉**

При проблемах смотрите [README.md](README.md) или логи бота.

