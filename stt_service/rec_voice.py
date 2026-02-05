import pyaudio
import wave
import threading
import time


def record_audio(filename, duration=10, sample_rate=16000):
    """
    Запись аудио с микрофона
    :param filename: имя файла для сохранения (например, 'recording.wav')
    :param duration: длительность записи в секундах
    :param sample_rate: частота дискретизации (16000 рекомендуется для Whisper)
    """

    # Параметры записи
    CHUNK = 1024  # Размер буфера
    FORMAT = pyaudio.paInt16  # Формат аудио (16-bit PCM)
    CHANNELS = 1  # Моно
    SAMPLE_RATE = sample_rate

    p = pyaudio.PyAudio()

    # Получить список доступных устройств
    print("Доступные аудиоустройства:")
    for i in range(p.get_device_count()):
        dev_info = p.get_device_info_by_index(i)
        print(f"{i}: {dev_info['name']} (входов: {dev_info['maxInputChannels']})")

    # Открыть поток для записи
    stream = p.open(format=FORMAT,
                    channels=CHANNELS,
                    rate=SAMPLE_RATE,
                    input=True,
                    frames_per_buffer=CHUNK,
                    input_device_index=None)  # Использовать устройство по умолчанию

    print(f"Запись начата... (будет записано {duration} секунд)")

    frames = []

    # Запись аудио
    for i in range(0, int(SAMPLE_RATE / CHUNK * duration)):
        data = stream.read(CHUNK)
        frames.append(data)

        # Прогресс-бар
        if i % 10 == 0:
            progress = (i * CHUNK) / (SAMPLE_RATE * duration) * 100
            print(f"\rПрогресс: {progress:.1f}%", end="")

    print("\nЗапись завершена!")

    # Остановить и закрыть поток
    stream.stop_stream()
    stream.close()
    p.terminate()

    # Сохранить в WAV файл
    with wave.open(filename, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(p.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b''.join(frames))

    print(f"Файл сохранен как: {filename}")


# Записать 10 секунд аудио
record_audio("recording.wav", duration=10)