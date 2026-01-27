"""
Модуль, ответственный за формирование промптов и списка сообщений для LLM.

Основные принципы:
- Один PromptBuilder → одна стратегия формирования промпта
- Легко можно создать разные реализации (например, с RAG, с разными форматами истории)
- Поддерживает как chat-формат (список сообщений), так и plain text (для старых локальных моделей)
- Не зависит от провайдера — возвращает универсальные структуры
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from ..interfaces import PromptBuilder


class DefaultPromptBuilder(PromptBuilder):
    """
    Основная (дефолтная) реализация построителя промптов.

    Особенности:
    - Ограничивает историю последними N сообщениями (по умолчанию 5)
    - Добавляет медиа-контекст в системный промпт (описание файлов/URL)
    - Поддерживает как chat-формат, так и plain text
    - Можно легко расширять: добавить шаблоны, RAG, few-shot примеры и т.д.
    """

    def __init__(
        self,
        history_limit: int = 5,
        media_context_format: Literal["description", "inline"] = "description",
        add_json_instruction: bool = True,
    ):
        """
        Args:
            history_limit: сколько последних пар сообщение-ответ включать в контекст
            media_context_format: как вставлять информацию о медиа
                "description" → в системный промпт как текст
                "inline" → в сообщение пользователя (если модель мультимодальная)
            add_json_instruction: добавлять ли явную инструкцию "ответь в JSON"
        """
        self.history_limit = history_limit
        self.media_context_format = media_context_format
        self.add_json_instruction = add_json_instruction

    def build_messages(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None,
        last_n: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Формирует список сообщений в формате, совместимом с OpenAI / большинством LLM API:

        [
            {"role": "system", "content": "..."},
            {"role": "user", "content": "..."},
            {"role": "assistant", "content": "..."},
            ...
            {"role": "user", "content": "текущее сообщение"}
        ]

        Args:
            system_prompt: основной системный промпт (инструкция поведения)
            user_message: текущее сообщение пользователя
            conversation_history: список предыдущих взаимодействий
                каждый элемент: {"user_message": "...", "agent_response": "..." или dict}
            media_context: список медиа-файлов/URL для контекста
            last_n: переопределение лимита истории (если нужно)

        Returns:
            Список сообщений
        """
        messages: List[Dict[str, str]] = []

        # 1. Системный промпт + медиа-контекст
        full_system = system_prompt.strip()

        if media_context and self.media_context_format == "description":
            media_desc = self._format_media_context(media_context)
            if media_desc:
                full_system += "\n\n" + media_desc

        # Добавляем инструкцию про JSON, если требуется
        if self.add_json_instruction:
            full_system += (
                "\n\nВАЖНО: Ответь строго в формате JSON. "
                "Не добавляй никакой дополнительный текст вне JSON-структуры. "
            )

        messages.append({"role": "system", "content": full_system})

        # 2. История диалога (последние N пар)
        limit = last_n if last_n is not None else self.history_limit
        if conversation_history:
            for entry in conversation_history[-limit:]:
                # Сообщение пользователя
                user_text = entry.get("user_message", "").strip()
                if user_text:
                    messages.append({"role": "user", "content": user_text})

                # Ответ агента
                agent_resp = entry.get("agent_response")
                if agent_resp:
                    if isinstance(agent_resp, dict):
                        # Если это уже структурированный ответ
                        agent_text = agent_resp.get("message", "")
                    elif isinstance(agent_resp, str):
                        agent_text = agent_resp
                    else:
                        agent_text = str(agent_resp)

                    if agent_text.strip():
                        messages.append({"role": "assistant", "content": agent_text.strip()})

        # 3. Текущее сообщение пользователя
        current_user_content = user_message.strip()

        # Если есть медиа и формат "inline" → можно добавить в user-сообщение
        # (но это имеет смысл только для мультимодальных моделей, например gpt-4o)
        if media_context and self.media_context_format == "inline":
            media_inline = self._format_media_inline(media_context)
            if media_inline:
                current_user_content = media_inline + "\n\n" + current_user_content

        if current_user_content:
            messages.append({"role": "user", "content": current_user_content})

        return messages

    def build_full_prompt_text(
        self,
        system_prompt: str,
        user_message: str,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        media_context: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        Альтернативный вариант — единая строка (для моделей без chat-формата,
        старых локальных моделей, llama.cpp в простом режиме и т.д.)

        Формат примерно такой:
        [System prompt + media]

        [История]
        Студент: ...
        Репетитор: ...

        Сообщение студента:
        {user_message}

        Ответь строго в формате JSON...
        """
        parts = []

        # Системный + медиа
        full_system = system_prompt.strip()
        if media_context:
            media_desc = self._format_media_context(media_context)
            if media_desc:
                full_system += "\n\n" + media_desc
        parts.append(full_system)

        # История
        if conversation_history:
            parts.append("\nИстория диалога:")
            for entry in conversation_history[-self.history_limit:]:
                user_text = entry.get("user_message", "").strip()
                if user_text:
                    parts.append(f"Студент: {user_text}")

                agent_resp = entry.get("agent_response")
                agent_text = ""
                if isinstance(agent_resp, dict):
                    agent_text = agent_resp.get("message", "")
                elif isinstance(agent_resp, str):
                    agent_text = agent_resp
                if agent_text.strip():
                    parts.append(f"Репетитор: {agent_text.strip()}")

        # Текущее сообщение
        parts.append(f"\nСообщение студента:\n{user_message.strip()}")

        # Финальная инструкция (если включена)
        if self.add_json_instruction:
            parts.append(
                "\nОтветь строго в формате JSON как указано в системной инструкции. "
                "Не добавляй никакой пояснительный текст вне JSON."
            )

        return "\n\n".join(filter(None, parts))

    def _format_media_context(self, media_context: List[Dict[str, Any]]) -> str:
        """Форматирует описание медиа для вставки в системный промпт"""
        if not media_context:
            return ""

        lines = ["Контекст прикреплённых медиафайлов:"]
        for media in media_context:
            media_type = media.get("type", "unknown")
            url = media.get("url", "")
            desc = media.get("description", "")
            line = f"- Тип: {media_type}"
            if url:
                line += f", URL: {url}"
            if desc:
                line += f", описание: {desc}"
            lines.append(line)
        return "\n".join(lines)

    def _format_media_inline(self, media_context: List[Dict[str, Any]]) -> str:
        """
        Формат для вставки в user-сообщение (для vision-моделей).
        Пока простая заглушка — в будущем можно сделать content: [{"type": "text"}, {"type": "image_url"}]
        """
        # Для начала просто текст — полная мультимодальность требует content-list
        return self._format_media_context(media_context)


# Удобный экспорт дефолтной реализации
default_prompt_builder = DefaultPromptBuilder(
    history_limit=5,
    media_context_format="description",  # или "inline" для gpt-4o-vision
    add_json_instruction=True,
)