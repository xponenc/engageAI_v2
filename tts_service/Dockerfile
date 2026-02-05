FROM python:3.11-slim

# Piper бинарник + модель
RUN apt-get update && apt-get install -y wget && \
    wget https://github.com/rhasspy/piper/releases/download/v1.2.0/piper_amd64.tar.gz && \
    tar xzf piper_amd64.tar.gz && rm piper_amd64.tar.gz && \
    apt-get clean

WORKDIR /app
COPY requirements.txt .
RUN pip install fastapi uvicorn

COPY app.py .
COPY voices /app/voices
EXPOSE 5000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "5000"]
