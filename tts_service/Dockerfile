FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    espeak-ng \
    ffmpeg \
    wget \
    unzip \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir piper-tts

# скачиваем модель
RUN mkdir -p /models && \
    wget -O /models/en_US-lessac-medium.onnx \
      https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx && \
    wget -O /models/en_US-lessac-medium.onnx.json \
      https://github.com/rhasspy/piper/releases/download/v1.2.0/en_US-lessac-medium.onnx.json

EXPOSE 5002

CMD ["python", "-m", "piper", "--model", "/models/en_US-lessac-medium", "--server", "--port", "5002"]
