# Universal Telegram Gateway

Лёгкий FastAPI‑шлюз, принимающий Telegram‑webhook запросы и проксирующий их во внутренний кластер ботов.  
Сервис автоматически поднимает webhook для всех зарегистрированных ботов, проверяет секреты, валидирует конфигурацию и обеспечивает надёжную доставку апдейтов с retry‑механизмом.

---

## Возможности

- Приём Telegram‑обновлений через `/webhook/{bot_name}`.
- Проверка `X-Telegram-Bot-Api-Secret-Token`.
- Проксирование апдейтов во внутренний кластер ботов через `internal/update`.
- Retry‑механизм с задержкой.
- Автоматическая установка webhook при запуске Gateway.
- Централизованная Pydantic‑конфигурация всех ботов.
- Валидация уникальных имён и внутренних ключей ботов.
- Логирование всех этапов: загрузка конфигурации, webhook‑установка, проксирование апдейтов.

---

## Структура проекта

```
api_gateway/
│
├── config.py                # Загрузка и валидация конфигурации Gateway + ботов
├── core_webhook.py          # FastAPI приложение + lifespan + webhook setup
│
├── routers/
│   ├── webhook_setup.py     # Основной обработчик Telegram webhook
│   └── telegram_router/
│       └── registration.py  # Внутренний endpoint регистрации пользователя
│
├── utils/
│   └── setup_logger.py      # Логирование
│
└── logs/
    └── api_gateway/         # Логи Gateway
```

---

## Установка

### 1. Установите зависимости:

```bash
pip install -r requirements.txt
```

### 2. Создайте `.env` файла Gateway:

```env
FAST_API_IP=127.0.0.1
FAST_API_PORT=8001

WEBHOOK_SECRET=mysecret
WEBHOOK_HOST=https://mygateway.com

INTERNAL_BOT_API_IP=127.0.0.1
INTERNAL_BOT_API_PORT=9000
```

### 3. Опишите ботов:

```env
BOT_NAME_1=EnglishBot
BOT_TOKEN_1=123456:ABC
BOT_INTERNAL_KEY_1=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

BOT_NAME_2=GrammarBot
BOT_TOKEN_2=987654:ZYXWVU
BOT_INTERNAL_KEY_2=yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy
```

> Каждый `BOT_INTERNAL_KEY_*` должен быть уникальным и длиной не менее 32.

---

## Запуск

```bash
uvicorn core_webhook:app --host $FAST_API_IP --port $FAST_API_PORT
```

### При старте Gateway:

- проходит валидация конфигурации,
- происходит автоматическая установка webhook для всех ботов,
- в лог выводятся доступные боты и установленные webhook.

---

## API

### Telegram Webhook

```
POST /webhook/{bot_name}
```

**Headers:**

```
X-Telegram-Bot-Api-Secret-Token: <WEBHOOK_SECRET>
```

**Body:**

JSON update от Telegram.

**Поведение:**

- Внутри создаётся фоновая задача отправки апдейта.
- Апдейт проксируется в кластер ботов с retry‑механизмом.
- Telegram сразу получает `{ "ok": true }`.

---

### Внутренние сервисы (пример)

```
POST /registration
Headers:
  X-Internal-Key: <internal_key>
```

Используется для внутренних механизмов привязки Telegram‑ID к пользователю.

---

## Логи

Путь:

```
logs/api_gateway/gateway.log
```

Логируются:

- загрузка конфигурации,
- ошибки валидации,
- установка webhook,
- приходящие апдейты,
- проксирование и retry.

---

## Безопасность

- Webhook Telegram проверяет `X-Telegram-Bot-Api-Secret-Token`.
- Внутренние запросы используют `X-Internal-Key`.
- Все внутренние ключи уникальны.
- Retry‑механизм обеспечивает доставку даже при временных ошибках.
