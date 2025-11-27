# engageAI — Экосистема нейро-репетитора английского языка

Мощная модульная платформа обучения английскому языку с использованием LLM, Telegram-ботов, персонализированного обучения, геймификации и прогресс-трекинга.  
Архитектура проекта разделена на независимые сервисы, каждый из которых выполняет свою роль.

---

# Архитектура

Проект состоит из трёх основных модулей:

1. **Django + DRF Backend**  
   Пользователи, уровни, прогресс, уроки, интеграция LLM, бизнес-логика.
    > пакет engageai_core

2. **API Gateway (FastAPI)**  
   Приём Telegram webhook и безопасная маршрутизация апдейтов во внутренний кластер ботов.
    > пакет api_gateway
3. **Кластер Telegram-ботов (FastAPI + Aiogram)**  
   Множество независимых Telegram-ботов, каждый со своей логикой, токеном и внутренним ключом.
    > пакет bots
---

## Структура проекта

```
engageAI/
│
├── engageAI/ # Django + DRF ядро
├── api_gateway/ # FastAPI Gateway (webhooks)
├── bots/ # кластер Telegram-ботов
├── utils/
└── docs/
```


---

## Установка

### 1. Установите зависимости:

```bash
pip install -r requirements.txt
```

### 2. Создайте `.env` файла Gateway:
Проект использует несколько env-файлов для разных модулей.

#### 2.1. .env Django / DRF (основной сервис)

Используется для:

LLM (OpenAI API),

базы данных,

взаимодействия с кластером ботов,

внутренних ключей ботов,

email-уведомлений.

```env
# LLM
OPENAI_API_KEY=

# DATABASE
DB_HOST=localhost
DB_PORT=5432
DB_NAME=
DB_USER=
DB_PASSWORD=

# Internal Bot API (куда Django может отправлять запросы ботам)
INTERNAL_BOT_API_IP=127.0.0.1
INTERNAL_BOT_API_PORT=8002

# Email
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_HOST=
EMAIL_PORT=

# Внутренние ключи ботов (используются для запросов Bots → DRF)
BOT_SYSTEM_KEY_1=supersecret111
BOT_SYSTEM_KEY_2=supersecret222
```

Django settings.py
```
import os

INTERNAL_BOTS = {
    key.replace("BOT_SYSTEM_KEY_", ""): value
    for key, value in os.environ.items()
    if key.startswith("BOT_SYSTEM_KEY_")
}
```

#### 2.1. .env API Gateway (FastAPI)
Gateway принимает webhook от Telegram и перенаправляет апдейты ботам.
см readme.md пакета api_gateway

#### 2.3. .env каждого Telegram-бота (bots)
Каждый бот — отдельная папка + свой .env.
см readme.md пакета bots

### 3. Внутренние ключи Bots → DRF (важно)

> В Django .env:

```env
BOT_SYSTEM_KEY_1=<секрет>
BOT_SYSTEM_KEY_2=<секрет>
```

> В Django settings:

```
INTERNAL_BOTS = {
    key.replace("BOT_SYSTEM_KEY_", ""): value
    for key, value in os.environ.items()
    if key.startswith("BOT_SYSTEM_KEY_")
}
```

> В боте:

```env
DRF_INTERNAL_KEY=<тот же секрет>
```

> Бот отправляет:

```env
X-Internal-Key: <DRF_INTERNAL_KEY>
```

DRF проверяет, что он имеет право выполнять запрос.

---

## 4. Запуск проекта

Django Backend
```
python manage.py migrate
python manage.py runserver
```

API Gateway
```
uvicorn core_webhook:app --host $FAST_API_IP --port $FAST_API_PORT

```

Кластер Telegram-ботов
```
uvicorn bots_engine:app --host 127.0.0.1 --port 8002

```

Redis
```
Поднять локальный Docker c Redis порт 6379
```
