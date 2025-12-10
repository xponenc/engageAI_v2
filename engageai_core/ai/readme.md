pip install pydantic-settings python-dotenv tenacity httpx aiohttp

# Для работы с LangChain
pip install langchain-core langchain-openai langchain-community

# Для работы с кэшированием
pip install redis

# Для работы с локальными моделями
# Hugging Face модели:
pip install transformers torch

# Llama.cpp модели:
pip install llama-cpp-python

# Для работы с OpenAI API (при использовании облака)
pip install openai

# Если у вас есть GPU с поддержкой CUDA (для ускорения)
# Для Hugging Face:
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

# Для Llama.cpp с поддержкой CUDA:
CMAKE_ARGS="-DLLAMA_CUBLAS=on" pip install llama-cpp-python --no-cache-dir

.env

# Базовые настройки
DEBUG=True
SECRET_KEY=your-django-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1

# Настройки базы данных
DATABASE_URL=sqlite:///db.sqlite3

# Настройки LLMFactory - OpenAI
OPENAI_API_KEY=sk-your-openai-api-key-here
USE_LOCAL_MODELS=false
LLM_MODEL_NAME=gpt-4o
LLM_FALLBACK_MODEL=gpt-4o-mini
LLM_TEMPERATURE=0.7
LLM_MAX_TOKENS=1000

# Кэширование
USE_LLM_CACHE=true
REDIS_URL=redis://localhost:6379/0
CACHE_TTL=3600

# Трекинг затрат
ENABLE_COST_TRACKING=true

# Медиа-генерация
MEDIA_GENERATION_ENABLED=true
DALLE_MODEL=dall-e-3
TTS_MODEL=tts-1
MEDIA_ROOT=media/
GENERATED_IMAGES_DIR=generated/images/
GENERATED_AUDIO_DIR=generated/audio/

# Rate limiting
MAX_RETRIES=3
BASE_RETRY_DELAY=1.0
MAX_RETRY_DELAY=10.0

# Таймауты
REQUEST_TIMEOUT=30
MEDIA_GENERATION_TIMEOUT=60

#Для использования локальных моделей (Hugging Face):

# Базовые настройки
DEBUG=True
SECRET_KEY=your-django-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1

# Настройки базы данных
DATABASE_URL=sqlite:///db.sqlite3

# Настройки LLMFactory - локальные модели
USE_LOCAL_MODELS=true
LOCAL_MODEL_PATH=/path/to/your/model  # Например: /models/mistral-7b-instruct-v0.2
LOCAL_MODEL_TYPE=huggingface
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=512

# Кэширование
USE_LLM_CACHE=true
REDIS_URL=redis://localhost:6379/0
CACHE_TTL=3600

# Отключаем функции, недоступные для локальных моделей
ENABLE_COST_TRACKING=false
MEDIA_GENERATION_ENABLED=false

# Rate limiting
MAX_RETRIES=3
BASE_RETRY_DELAY=1.0
MAX_RETRY_DELAY=10.0

# Таймауты
REQUEST_TIMEOUT=60  # Увеличиваем таймаут для локальных моделей

#Для использования локальных моделей (Llama.cpp):
# Базовые настройки
DEBUG=True
SECRET_KEY=your-django-secret-key
ALLOWED_HOSTS=localhost,127.0.0.1

# Настройки базы данных
DATABASE_URL=sqlite:///db.sqlite3

# Настройки LLMFactory - Llama.cpp
USE_LOCAL_MODELS=true
LOCAL_MODEL_PATH=/path/to/your/model.gguf  # Например: /models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
LOCAL_MODEL_TYPE=llama-cpp
LLM_TEMPERATURE=0.3
LLM_MAX_TOKENS=512

# Кэширование
USE_LLM_CACHE=true
REDIS_URL=redis://localhost:6379/0
CACHE_TTL=3600

# Отключаем функции, недоступные для локальных моделей
ENABLE_COST_TRACKING=false
MEDIA_GENERATION_ENABLED=false

# Rate limiting
MAX_RETRIES=3
BASE_RETRY_DELAY=1.0
MAX_RETRY_DELAY=10.0

# Таймауты
REQUEST_TIMEOUT=60  # Увеличиваем таймаут для локальных моделей


# Гибридный подход:
# Используем локальные модели для базовых запросов
USE_LOCAL_MODELS=true
LOCAL_MODEL_PATH=/models/mistral-7b-instruct-v0.2.Q4_K_M.gguf
LOCAL_MODEL_TYPE=llama-cpp

# Но включаем OpenAI для генерации медиа
OPENAI_API_KEY=sk-your-key
MEDIA_GENERATION_ENABLED=true