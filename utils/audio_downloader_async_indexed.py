"""
Ремайк https://github.com/thousandlemons/English-words-pronunciation-mp3-audio-download
"""
import asyncio


import json
import logging
import os
from typing import Set

import aiohttp

# ================= CONFIG =================
DATA_FILE = "audio_data.json"
INDEX_FILE = "index.jsonl"
OUTPUT_DIR = "download"

CONCURRENCY = 40
TIMEOUT = 15
RETRIES = 3
MP3_EXT = ".mp3"
# =========================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


# ---------- utils ----------
def safe_filename(word: str) -> str:
    return (
        word.lower()
        .strip()
        .replace(" ", "_")
        .replace("/", "_")
    )


def load_downloaded_words(index_file: str) -> Set[str]:
    """
    Читает index.jsonl построчно и возвращает множество
    уже успешно скачанных слов
    """
    downloaded = set()

    if not os.path.exists(index_file):
        return downloaded

    with open(index_file, encoding="utf-8") as f:
        for line in f:
            try:
                obj = json.loads(line)
                downloaded.add(obj["word"])
            except Exception:
                continue

    return downloaded


def append_index(word: str, filename: str) -> None:
    """
    Атомарно дописывает одну строку в index.jsonl
    """
    with open(INDEX_FILE, "a", encoding="utf-8") as f:
        f.write(
            json.dumps(
                {"word": word, "file": filename},
                ensure_ascii=False,
            )
            + "\n"
        )


# ---------- downloader ----------
async def download_word(
    session: aiohttp.ClientSession,
    sem: asyncio.Semaphore,
    word: str,
    url: str,
) -> None:
    filename = safe_filename(word) + MP3_EXT
    path = os.path.join(OUTPUT_DIR, filename)

    async with sem:
        for attempt in range(1, RETRIES + 1):
            try:
                async with session.get(url, timeout=TIMEOUT) as resp:
                    resp.raise_for_status()
                    data = await resp.read()

                with open(path, "wb") as f:
                    f.write(data)

                append_index(word, filename)
                logger.info("OK %s", word)
                return

            except Exception as e:
                if attempt == RETRIES:
                    logger.error("FAIL %s: %s", word, e)
                else:
                    await asyncio.sleep(0.5 * attempt)


# ---------- main ----------
async def main() -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    with open(DATA_FILE, encoding="utf-8") as f:
        data: dict[str, str] = json.load(f)

    downloaded_words = load_downloaded_words(INDEX_FILE)
    logger.info("Already downloaded: %d", len(downloaded_words))

    sem = asyncio.Semaphore(CONCURRENCY)
    timeout = aiohttp.ClientTimeout(total=TIMEOUT)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [
            download_word(session, sem, word, url)
            for word, url in data.items()
            if word not in downloaded_words
        ]

        logger.info("To download: %d", len(tasks))
        await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
