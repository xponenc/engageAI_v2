# Clustered Bots Service

Лёгкий кластерный сервер для запуска нескольких Telegram-ботов под единым FastAPI-сервисом.  
Каждый бот хранится в отдельной папке, имеет собственную конфигурацию и набор хэндлеров.  
Gateway проекта отправляет апдейты на единый endpoint `/internal/update`, а сервис маршрутизирует их нужному боту.

---

## Возможности

- Динамическая загрузка ботов из подпапок (`bots/<bot_name>/`) без ручной регистрации.
- Автоматическое подключение хэндлеров:
  - обычные — по алфавиту;
  - fallback-хэндлеры — последними (`z_*.py` или `*fallback*`);
  - если fallback отсутствует — создаётся echo-router.
- Асинхронная обработка апдейтов через `dp.feed_update` с retry-механизмом.
- Фоновая обработка через FastAPI BackgroundTasks (дополнительно — Celery).
- Изоляция ботов (токен + `BOT_INTERNAL_KEY` у каждого).
- Логирование загрузки, ошибок и маршрутизации.

---

## Структура проекта

```
bots/
│
├── bots_engine.py         # кластерный сервер
├── tasks.py               # Celery-обработчик (опционально)
│
├── <bot_name>/            # отдельный бот
│   ├── config.py          # BOT_NAME / BOT_TOKEN / BOT_INTERNAL_KEY
│   ├── handlers/          # файлы Router'ов
│   ├── filters/           # фильтры (опция)
│   ├── services/          # API-утилиты
│   └── .env               # секреты конкретного бота
│
└── utils/
    └── setup_logger.py
```

---

## Установка

### 1. Установка зависимостей

```bash
pip install -r requirements.txt
```

### 2. Создание `.env` для сервиса

```env
INTERNAL_BOT_API_IP=127.0.0.1
INTERNAL_BOT_API_PORT=8010
```

### 3. Создание `.env` для каждого бота

```env
BOT_NAME=EnglishBot
BOT_TOKEN=<telegram_token>
BOT_INTERNAL_KEY=<random_secret_string>
```

---

## Запуск

```bash
uvicorn bots_engine:app     --host $INTERNAL_BOT_API_IP     --port $INTERNAL_BOT_API_PORT     --reload
```

При старте:

- сканируются подпапки в `bots/`,
- загружаются конфигурации,
- подключаются Router’ы,
- в лог выводятся активные боты.

---

## Внутренний API

### POST /internal/update

Получает апдейт от Gateway и в фоне передаёт его соответствующему боту.

**Headers:**

```
X-Internal-Key: <BOT_INTERNAL_KEY>
```

**Body:**

```json
{
  "bot_name": "EnglishBot",
  "update": { ... }
}
```

Ответ:

```json
{ "accepted": true }
```

---

## Логи

Путь: `logs/bots/bots.log`

Логируется:

- загрузка ботов,
- подключение Router’ов,
- ошибки хэндлеров,
- retry feed_update.

---

## Добавление нового бота

1. Создать папку:

```
bots/my_new_bot/
```

2. Добавить `config.py`:

```python
BOT_NAME = "MyBot"
BOT_TOKEN = "123:ABC"
BOT_INTERNAL_KEY = "xxx"
```

3. Добавить папку `handlers/`:

```
handlers/start.py
handlers/z_fallback.py
```

4. Перезапустить сервер — бот будет загружен автоматически.
5ю celery -A bots.celery_app worker --loglevel=INFO --pool=solo --queues=telegram_updates,drf_save