import os

import requests
import time
import json


def transcribe_audio(file_path, server_url="http://localhost:8010", language="en", model="base"):
    """
    Транскрибирует аудиофайл через faster-whisper-server

    Args:
        file_path: путь к аудиофайлу
        server_url: URL сервера
        language: язык аудио (например, 'en' для английского)
        model: модель Whisper (tiny, base, small, medium, large-v1, large-v2, large-v3)

    Returns:
        dict: результат транскрипции или None в случае ошибки
    """
    try:
        with open(file_path, "rb") as audio_file:
            # Создаем multipart/form-data запрос
            files = {
                'file': (file_path, audio_file, 'audio/wav')
            }

            # Параметры запроса
            data = {
                'model': model,
                'language': language,
                'response_format': 'json',  # или 'srt', 'vtt', 'txt'
                'temperature': '0.0',
                # 'prompt': 'Специальные термины',  # опционально
                # 'timestamp_granularities': ['word'],  # для временных меток слов
                # 'without_timestamps': 'false',  # если нужны временные метки
            }

            # Удаляем пустые параметры
            data = {k: v for k, v in data.items() if v is not None}

            start_time = time.time()

            # Отправляем запрос
            response = requests.post(
                f"{server_url}/v1/audio/transcriptions",
                files=files,
                data=data,
                timeout=300  # 5 минут
            )

            processing_time = time.time() - start_time

            if response.status_code == 200:
                result = response.json()
                print(f"✓ Обработано за {processing_time:.2f} секунд")
                return result
            else:
                print(f"✗ Ошибка сервера: {response.status_code}")
                print(f"Ответ сервера: {response.text}")
                return None

    except requests.exceptions.Timeout:
        print("⏰ Таймаут: сервер не ответил вовремя")
    except FileNotFoundError:
        print(f"📁 Файл не найден: {file_path}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

    return None


# Пример использования с разными параметрами
def transcribe_with_options():
    # Вариант 1: Простая транскрипция
    result = transcribe_audio(
        file_path="recording.wav",
        server_url="http://localhost:8010",
        language="en",
        model="base"
    )

    if result:
        print("📝 Транскрипция:")
        print(result.get("text", "Текст не найден"))

    return result


# Расширенная версия с поддержкой всех параметров
def transcribe_audio_advanced(
        file_path,
        server_url="http://localhost:8010",
        model="base",
        language=None,
        prompt=None,
        response_format="json",
        temperature=0.0,
        timestamp_granularities=None,
        stream=False,
        hotwords=None,
        without_timestamps=False
):
    """
    Расширенная функция транскрипции со всеми параметрами из документации

    Args:
        timestamp_granularities: список типов временных меток ['word', 'segment']
        hotwords: список ключевых слов для улучшения распознавания
        without_timestamps: если True, не возвращает временные метки
    """
    try:
        with open(file_path, "rb") as audio_file:
            # Подготовка файла
            files = {
                'file': (file_path, audio_file, 'audio/wav')
            }

            # Подготовка данных
            data = {
                'model': model,
            }

            # Добавляем опциональные параметры если они заданы
            if language:
                data['language'] = language
            if prompt:
                data['prompt'] = prompt
            if response_format:
                data['response_format'] = response_format
            if temperature is not None:
                data['temperature'] = str(temperature)
            if timestamp_granularities:
                # Преобразуем список в строку формата JSON
                data['timestamp_granularities'] = json.dumps(timestamp_granularities)
            if stream:
                data['stream'] = 'true'
            if hotwords:
                data['hotwords'] = hotwords
            if without_timestamps:
                data['without_timestamps'] = 'true'

            print(f"📤 Отправка запроса с параметрами: {data}")

            start_time = time.time()

            response = requests.post(
                f"{server_url}/v1/audio/transcriptions",
                files=files,
                data=data,
                timeout=300
            )

            processing_time = time.time() - start_time

            if response.status_code == 200:
                # Обработка разных форматов ответа
                if response_format == 'json':
                    result = response.json()
                elif response_format in ['srt', 'vtt', 'txt']:
                    result = {'text': response.text}
                else:
                    result = response.text

                print(f"✅ Обработано за {processing_time:.2f} секунд")
                return result
            else:
                print(f"❌ Ошибка {response.status_code}: {response.text}")
                return None

    except Exception as e:
        print(f"❌ Исключение: {e}")
        import traceback
        traceback.print_exc()
        return None


# Функция для записи и немедленной транскрипции
def record_and_transcribe(duration=10, sample_rate=16000):
    """
    Записывает аудио с микрофона и сразу транскрибирует
    """
    import pyaudio
    import wave
    import io
    import tempfile
    import os

    # Запись аудио
    CHUNK = 1024
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = sample_rate

    try:
        p = pyaudio.PyAudio()

        stream = p.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=RATE,
            input=True,
            frames_per_buffer=CHUNK
        )

        print(f"🎤 Запись {duration} секунд...")
        frames = []

        for i in range(0, int(RATE / CHUNK * duration)):
            data = stream.read(CHUNK)
            frames.append(data)
            # Прогресс
            if i % 10 == 0:
                print(f"\rПрогресс: {int(i / (RATE / CHUNK * duration) * 100)}%", end="")

        print("\n✅ Запись завершена")

        stream.stop_stream()
        stream.close()
        p.terminate()

        # Сохраняем во временный файл
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
            with wave.open(tmp_file.name, 'wb') as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(p.get_sample_size(FORMAT))
                wf.setframerate(RATE)
                wf.writeframes(b''.join(frames))

            print("📤 Отправка на транскрипцию...")

            # Транскрибируем с расширенными параметрами
            result = transcribe_audio_advanced(
                file_path=tmp_file.name,
                model="base",
                language="en",
                timestamp_granularities=['word']  # получаем временные метки слов
            )

        # Удаляем временный файл
        os.unlink(tmp_file.name)

        if result:
            if isinstance(result, dict) and 'text' in result:
                print(result)
                print("\n📝 Результат транскрипции:")
                print("-" * 50)
                print(result['text'])
                print("-" * 50)

                # Если есть временные метки слов
                if 'words' in result or 'segments' in result:
                    print("\n⏰ Временные метки:")
                    if 'words' in result:
                        for word in result['words'][:10]:  # покажем первые 10 слов
                            print(f"  {word['word']}: {word['start']:.2f}-{word['end']:.2f}")

            return result
        else:
            print("❌ Не удалось выполнить транскрипцию")
            return None

    except Exception as e:
        print(f"❌ Ошибка при записи/транскрипции: {e}")
        return None


# Проверка доступности сервера
def check_server_status(server_url="http://localhost:8010"):
    """
    Проверяет доступность сервера транскрипции
    """
    try:
        response = requests.get(f"{server_url}/docs", timeout=5)
        if response.status_code == 200:
            print(f"✅ Сервер доступен: {server_url}")
            return True
        else:
            print(f"⚠️  Сервер ответил с кодом: {response.status_code}")
            return False
    except requests.exceptions.ConnectionError:
        print(f"❌ Не удалось подключиться к серверу: {server_url}")
        return False
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return False


# Основной скрипт
if __name__ == "__main__":
    print("🔍 Проверка подключения к серверу...")

    if check_server_status():
        print("\nВыберите режим:")
        print("1. Транскрибировать существующий файл")
        print("2. Записать с микрофона и транскрибировать")

        choice = input("\nВведите номер (1 или 2): ").strip()

        if choice == "1":
            file_path = input("Введите путь к аудиофайлу: ").strip()
            if os.path.exists(file_path):
                result = transcribe_audio_advanced(
                    file_path=file_path,
                    model="base",
                    language="en",
                    timestamp_granularities=['word']
                )
                if result and 'text' in result:
                    print("\n📝 Текст:")
                    print(result['text'])
            else:
                print("❌ Файл не найден!")

        elif choice == "2":
            try:
                duration = int(input("Длительность записи (секунд): ").strip() or "10")
                record_and_transcribe(duration=duration)
            except ValueError:
                print("❌ Некорректная длительность!")
        else:
            print("❌ Неверный выбор!")
    else:
        print("⚠️  Убедитесь, что сервер запущен:")
        print("   docker-compose up -d")
