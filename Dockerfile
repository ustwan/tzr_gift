# Используем официальный Python образ
FROM python:3.11-slim

# Метаданные
LABEL maintainer="GiftApp Bot"
LABEL description="Telegram bot для работы с игровыми подарками"

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы зависимостей
COPY bot_requirements.txt requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Копируем необходимые файлы бота
COPY gift_bot.py .
COPY drop_analyzer.py .
COPY access_control.py .
COPY settings.json .
COPY present_list.json .
COPY users.json .

# Создаем директорию для данных
RUN mkdir -p /app/data

# Переменные окружения (можно переопределить в docker-compose)
ENV BOT_TOKEN=""
ENV LOG_LEVEL="INFO"

# Запуск бота
CMD ["python", "-u", "gift_bot.py"]

