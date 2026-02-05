import requests
import time
import json

time.sleep(3)
print("Тестируем Wyoming API...")

# Wyoming протокол ожидает STREAM
headers = {
    "Content-Type": "application/json",
    "Accept": "audio/wav"
}

try:
    resp = requests.post(
        "http://localhost:5000/synthesize",
        json={"text": "hello"},
        headers=headers,
        stream=True,
        timeout=10
    )
    resp.raise_for_status()

    with open("hello.wav", "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)

    print("✅ hello.wav готов!")
except Exception as e:
    print(f"❌ {e}")
