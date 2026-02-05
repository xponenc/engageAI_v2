import requests
import time


def simple_transcribe(file_path, server_url="http://localhost:8010"):
    """Упрощенная функция для транскрипции файла"""
    try:
        with open(file_path, "rb") as audio_file:
            response = requests.post(
                f"{server_url}/v1/audio/transcriptions",
                files={"file": audio_file},
                data={
                    "model": "base",
                    "language": "en",
                    "response_format": "json"
                },
                timeout=300
            )

            if response.status_code == 200:
                return response.json()
            else:
                print(f"Error: {response.status_code}")
                return None
    except Exception as e:
        print(f"Exception: {e}")
        return None


# Быстрое использование
if __name__ == "__main__":
    result = simple_transcribe("recording.wav")
    if result:
        print(result["text"])