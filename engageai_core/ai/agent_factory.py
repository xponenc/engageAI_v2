# # engageai_core/ai/agent_factory.py
# import json
# import os
# import uuid
# from typing import Dict, Any, List
#
# from django.conf import settings
#
# from engageai_core.ai.prompts.system_prompts import get_agent_prompt
# from engageai_core.ai.prompts.examples import DIAGNOSTIC_EXAMPLES, CURATOR_EXAMPLES
# from engageai_core.ai.prompts.templates import format_platform_message
#
#
# class AgentFactory:
#     """
#     Фабрика для создания ответов от AI-агентов
#     """
#
#     async def create_agent_response(self, agent_type: str, user_state: Dict[str, Any],
#                                     user_message: str, media_files=None, platform: str = "web") -> Dict[str, Any]:
#         """
#         Генерирует ответ от агента на основе промпта и контекста
#
#         Args:
#             agent_type: Тип агента (diagnostic, curator, teacher)
#             user_state: Текущее состояние пользователя
#             user_message: Сообщение от пользователя
#             media_files: медиа-данные
#             platform: Платформа для форматирования ответа
#
#         Returns:
#             Структурированный ответ от агента
#         """
#         system_prompt = get_agent_prompt(agent_type, user_state)
#
#         if media_files:
#             media_context = "\nКонтекст медиафайлов:"
#             for media in media_files:
#                 media_context += f"\n- Тип: {media['type']}, URL: {media['url']}"
#                 # Для изображений можно добавить анализ контента для LLM
#                 # if media['type'] == 'image':
#                 #     media_context += f"\n  (Изображение содержит: {self._analyze_image(media['path'])})"
#             system_prompt += media_context
#
#         # Добавляем few-shot примеры для улучшения качества
#         examples = self._get_examples(agent_type)
#         if examples:
#             system_prompt += "\n\nПримеры диалогов:\n" + self._format_examples(examples)
#
#         # Формируем полный промпт с историей диалога
#         conversation_history = self._format_history(user_state.get('history', []))
#
#         full_prompt = f"""
# {system_prompt}
#
# История диалога:
# {conversation_history}
#
# Сообщение студента:
# {user_message}
#
# Ответь строго в формате JSON как указано в инструкции.
# """
#         # Получаем ответ от LLM
#         raw_response = await self._generate_llm_response(full_prompt)
#
#         # Парсим структурированный ответ
#         structured_response = self._parse_structured_response(raw_response)
#
#         # Проверяем, нужно ли генерировать медиа
#         media_files = []
#         if 'generate_media' in structured_response.get('agent_state', {}):
#             media_instructions = structured_response['agent_state']['generate_media']
#             media_files = await self._generate_media_files(media_instructions)
#             structured_response['media_files'] = media_files
#
#         # Форматируем сообщение для конкретной платформы
#         if "message" in structured_response:
#             structured_response["message"] = format_platform_message(
#                 platform=platform,
#                 message_data=structured_response
#             )
#
#         return structured_response
#
#     async def _generate_llm_response(self, prompt: str) -> str:
#         """
#         Генерирует ответ от LLM
#
#         TODO: Интеграция с OpenAI API
#         """
#         # Для MVP используем mock-ответ
#         mock_responses = {
#             "diagnostic": {
#                 "message": "Здравствуйте! Я ваш персональный AI-репетитор по английскому языку. Чтобы создать идеальный план обучения, расскажите — для чего вам нужен английский: для работы, путешествий, общения или карьерного роста?",
#                 "agent_state": {
#                     "estimated_level": None,
#                     "confidence": 1,
#                     "engagement_change": 1,
#                     "next_question_type": "goals"
#                 }
#             },
#             "curator": {
#                 "message": "Отлично! На основе вашего уровня и целей я подготовил персональный план обучения. Готовы начать?",
#                 "agent_state": {
#                     "engagement_change": 2
#                 }
#             }
#         }
#
#         # В реальной реализации здесь будет вызов OpenAI API
#         import random
#         return json.dumps(random.choice(list(mock_responses.values())))
#
#     async def _generate_media_files(self, instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
#         """
#         Генерирует медиафайлы на основе инструкций от агента
#         """
#         generated_files = []
#
#         for instruction in instructions:
#             media_type = instruction.get('type')
#             prompt = instruction.get('prompt', '')
#
#             if media_type == 'image':
#                 # Генерация изображения с использованием DALL-E
#                 image_data = await self._generate_image_with_dalle(prompt)
#                 if image_data:
#                     # Сохраняем файл
#                     file_name = f"ai_image_{uuid.uuid4()}.png"
#                     file_path = os.path.join(settings.MEDIA_ROOT, 'generated', file_name)
#                     os.makedirs(os.path.dirname(file_path), exist_ok=True)
#
#                     with open(file_path, 'wb') as f:
#                         f.write(image_data)
#
#                     # Возвращаем информацию о файле
#                     generated_files.append({
#                         'url': f"{settings.MEDIA_URL}generated/{file_name}",
#                         'type': 'image',
#                         'mime_type': 'image/png',
#                         'path': file_path,
#                         'size': len(image_data)
#                     })
#
#             elif media_type == 'audio':
#                 # Генерация аудио с использованием TTS
#                 audio_data = await self._generate_audio_with_tts(prompt)
#                 if audio_data:
#                     # Сохраняем файл
#                     file_name = f"ai_audio_{uuid.uuid4()}.mp3"
#                     file_path = os.path.join(settings.MEDIA_ROOT, 'generated', file_name)
#                     os.makedirs(os.path.dirname(file_path), exist_ok=True)
#
#                     with open(file_path, 'wb') as f:
#                         f.write(audio_data)
#
#                     generated_files.append({
#                         'url': f"{settings.MEDIA_URL}generated/{file_name}",
#                         'type': 'audio',
#                         'mime_type': 'audio/mpeg',
#                         'path': file_path,
#                         'size': len(audio_data)
#                     })
#
#         return generated_files
#
#     async def _generate_image_with_dalle(self, prompt):
#         """Генерирует изображение с помощью DALL-E API"""
#         try:
#             response = await self.client.images.generate(
#                 model="dall-e-3",
#                 prompt=prompt,
#                 size="1024x1024",
#                 quality="standard",
#                 n=1,
#             )
#             image_url = response.data[0].url
#
#             # Загружаем изображение
#             import requests
#             img_data = requests.get(image_url).content
#             return img_data
#         except Exception as e:
#             print(f"Ошибка генерации изображения: {e}")
#             return None
#
#     async def _generate_audio_with_tts(self, text):
#         """Генерирует аудио с помощью TTS API"""
#         try:
#             response = await self.client.audio.speech.create(
#                 model="tts-1",
#                 voice="alloy",
#                 input=text
#             )
#             return response.content
#         except Exception as e:
#             print(f"Ошибка генерации аудио: {e}")
#             return None
#
#     def _get_examples(self, agent_type: str) -> list:
#         """Возвращает примеры для конкретного типа агента"""
#         if agent_type == 'diagnostic':
#             return DIAGNOSTIC_EXAMPLES
#         elif agent_type == 'curator':
#             return CURATOR_EXAMPLES
#         return []
#
#     def _format_examples(self, examples: list) -> str:
#         """Форматирует примеры для промпта"""
#         formatted = ""
#         for example in examples:
#             formatted += f"Контекст: {example['context']}\n"
#             formatted += f"Вход: {example['input']}\n"
#             formatted += f"Выход: {json.dumps(example['output'], ensure_ascii=False)}\n\n"
#         return formatted
#
#     def _format_history(self, history: list) -> str:
#         """Форматирует историю диалога для промпта"""
#         if not history:
#             return "Диалог только начинается."
#
#         formatted = ""
#         for entry in history[-5:]:  # последние 5 сообщений для контекста
#             formatted += f"Студент: {entry['user_message']}\n"
#             if isinstance(entry['agent_response'], dict):
#                 formatted += f"Репетитор: {entry['agent_response'].get('message', '...')}\n\n"
#             else:
#                 formatted += f"Репетитор: {entry['agent_response']}\n\n"
#         return formatted
#
#     def _parse_structured_response(self, raw_response: str) -> Dict[str, Any]:
#         """Парсит структурированный ответ от LLM"""
#         try:
#             # Извлекаем JSON из ответа
#             start_idx = raw_response.find('{')
#             end_idx = raw_response.rfind('}') + 1
#
#             if start_idx == -1 or end_idx == 0:
#                 raise ValueError("No JSON structure found in LLM response")
#
#             json_str = raw_response[start_idx:end_idx]
#             return json.loads(json_str)
#
#         except Exception as e:
#             # Логируем ошибку и возвращаем фолбэк
#             print(f"Error parsing LLM response: {e}")
#             return {
#                 "message": "Извините, я не совсем понял ваш ответ. Можете повторить?",
#                 "agent_state": {
#                     "engagement_change": -1
#                 }
#             }


# engageai_core/ai/agent_factory.py
import json
import os
import uuid
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

# Django импорты
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage

# Локальные импорты
from ai.prompts.system_prompts import get_agent_prompt
from ai.prompts.examples import DIAGNOSTIC_EXAMPLES, CURATOR_EXAMPLES
from ai.prompts.templates import format_platform_message
from ai.llm.llm_factory import llm_factory, GenerationResult  # Новый импорт

logger = logging.getLogger(__name__)  # Добавляем логирование


class AgentFactory:
    """
    Фабрика для создания ответов от AI-агентов

    Ключевые изменения для интеграции с LLMFactory:
    1. Полная замена вызовов OpenAI API на использование LLMFactory
    2. Поддержка как облачных, так и локальных моделей
    3. Улучшенная обработка ошибок и fallback-механизмы
    4. Расширенная метрика использования и логирование

    Особенности для локальных моделей:
    - Отключение генерации медиа при использовании локальных моделей
    - Упрощенные промпты для лучшей совместимости
    - Автоматический fallback на текстовые ответы при ошибках
    """

    def __init__(self):
        """Инициализация AgentFactory с поддержкой локальных моделей"""
        self.llm_factory = llm_factory  # Используем глобальную фабрику
        logger.info(f"AgentFactory initialized with configuration: {self.llm_factory.config.model_dump_public()}")

    async def create_agent_response(
            self,
            agent_type: str,
            user_state: Dict[str, Any],
            user_message: str,
            media_files: Optional[List[Dict[str, Any]]] = None,
            platform: str = "web"
    ) -> Dict[str, Any]:
        """
        Основной метод генерации ответа агента с полной поддержкой локальных моделей
        """
        try:
            # 1. Формирование системного промпта
            system_prompt = get_agent_prompt(agent_type, user_state)

            # 2. Обработка медиафайлов
            media_context = None
            if media_files and not self.llm_factory.config.use_local_models:
                media_context = await self._prepare_media_context(media_files)
                if media_context:
                    system_prompt = self._add_media_context_to_prompt(system_prompt, media_context)

            # 3. Добавление примеров для улучшения качества
            examples = self._get_examples(agent_type)
            if examples and not self.llm_factory.config.use_local_models:  # Для локальных моделей упрощаем промпт
                system_prompt = self._add_examples_to_prompt(system_prompt, examples)

            # 4. Формирование истории диалога
            conversation_history = self._format_history(user_state.get('history', []))

            # 5. Генерация ответа через LLMFactory
            generation_result = await self.llm_factory.generate_json_response(
                system_prompt=system_prompt,
                user_message=user_message,
                conversation_history=conversation_history,
                media_context=media_context
            )

            # 6. Обработка генерации медиа (только для OpenAI)
            media_files = []
            if not self.llm_factory.config.use_local_models and self._should_generate_media(generation_result.response):
                media_instructions = generation_result.response.agent_state.get('generate_media', [])
                media_files = await self._generate_media_files(media_instructions)
                generation_result.response.metadata['media_files'] = media_files

            # 7. Форматирование для платформы
            formatted_message = self._format_response_for_platform(
                generation_result.response,
                platform
            )

            # 8. Формирование финального ответа
            final_response = self._build_final_response(
                generation_result,
                formatted_message,
                media_files
            )

            # 9. Логирование результатов
            self._log_generation_results(agent_type, generation_result, media_files)

            return final_response

        except Exception as e:
            logger.exception(f"Critical error in agent response generation: {str(e)}")
            return self._get_fallback_response(agent_type, e)

    async def _prepare_media_context(self, media_files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Подготавливает контекст медиафайлов для промпта

        Важно: Для локальных моделей этот метод может быть упрощен или пропущен,
        так как анализ изображений не поддерживается
        """
        media_context = []

        for media in media_files:
            context = {
                'type': media['type'],
                'url': media['url'],
                'path': media.get('path')
            }

            # Анализ изображений ДОСТУПЕН ТОЛЬКО ДЛЯ OPENAI
            if media['type'] == 'image' and media.get('path') and not self.llm_factory.config.use_local_models:
                try:
                    # Пока закомментировано, так как требует отдельной реализации
                    # image_analysis = await analyze_image_content(media['path'])
                    # context['analysis'] = image_analysis
                    context['analysis'] = "Анализ изображения недоступен в текущей версии"
                except Exception as e:
                    logger.warning(f"Failed to analyze image {media['path']}: {str(e)}")

            media_context.append(context)

        return media_context

    async def _generate_media_files(self, instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Генерация медиафайлов ТОЛЬКО для OpenAI моделей

        Для локальных моделей возвращает пустой список
        """
        if self.llm_factory.config.use_local_models:
            logger.warning("Media generation is not supported with local models")
            return []

        generated_files = []

        for instruction in instructions:
            try:
                media_type = instruction.get('type')
                prompt = instruction.get('prompt', '')

                if not media_type or not prompt:
                    logger.warning(f"Skipping media generation due to missing type or prompt: {instruction}")
                    continue

                logger.info(f"Generating {media_type} with prompt: {prompt[:100]}...")

                # Генерация медиа через LLMFactory
                media_result = await self.llm_factory.generate_media_response(
                    media_type=media_type,
                    prompt=prompt
                )

                if not media_result.get('success'):
                    logger.error(f"Media generation failed for {media_type}: {media_result.get('error')}")
                    continue

                # Сохранение файла
                file_info = await self._save_generated_media(
                    media_type=media_type,
                    media_data=media_result.get('data'),
                    prompt=prompt,
                    metadata=instruction
                )

                if file_info:
                    generated_files.append({
                        **file_info,
                        'generation_cost': media_result.get('cost', 0.0),
                        'original_prompt': prompt
                    })
                    logger.info(f"Successfully generated and saved {media_type}: {file_info['url']}")

            except Exception as e:
                logger.error(f"Error generating media file: {str(e)}")
                continue

        return generated_files

    def _add_media_context_to_prompt(self, system_prompt: str, media_context: List[Dict[str, Any]]) -> str:
        """
        Добавляет контекст медиа в системный промпт
        """
        media_prompt = "\n\nКонтекст медиафайлов, загруженных студентом:"

        for i, media in enumerate(media_context, 1):
            media_prompt += f"\n\nМедиафайл #{i}:"
            media_prompt += f"\nТип: {media['type']}"
            media_prompt += f"\nURL: {media['url']}"

            if media['type'] == 'image' and 'analysis' in media:
                media_prompt += f"\nАнализ изображения: {media['analysis']}"

        return system_prompt + media_prompt

    def _add_examples_to_prompt(self, system_prompt: str, examples: list) -> str:
        """
        Добавляет few-shot примеры в системный промпт
        """
        examples_prompt = "\n\nПримеры диалогов для лучшего понимания контекста:"
        examples_prompt += "\n" + self._format_examples(examples)

        return system_prompt + examples_prompt

    def _should_generate_media(self, response: 'LLMResponse') -> bool:
        """
        Проверяет, нужно ли генерировать медиа
        """
        agent_state = response.agent_state or {}
        generate_media = agent_state.get('generate_media')

        if generate_media and isinstance(generate_media, list) and len(generate_media) > 0:
            logger.info(f"LLM requested media generation: {len(generate_media)} items")
            return True

        return False

    def _format_response_for_platform(self, response: 'LLMResponse', platform: str) -> str:
        """
        Форматирует ответ для конкретной платформы
        """
        try:
            return format_platform_message(platform=platform, message_data={
                "message": response.message,
                "agent_state": response.agent_state or {}
            })
        except Exception as e:
            logger.error(f"Error formatting response for platform {platform}: {str(e)}")
            return response.message

    def _build_final_response(
            self,
            generation_result: GenerationResult,
            formatted_message: str,
            media_files: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Собирает финальный ответ с метаданными
        """
        response_data = {
            "message": formatted_message,
            "agent_state": generation_result.response.agent_state or {},
            "success": True,
            "metadata": {
                "model_used": generation_result.model_used,
                "token_usage": generation_result.token_usage,
                "cost": generation_result.cost,
                "generation_time": generation_result.generation_time,
                "cached": generation_result.cached,
                "media_files": media_files if not self.llm_factory.config.use_local_models else []
            }
        }

        # Добавляем информацию о медиа в метаданные (только для OpenAI)
        if media_files and not self.llm_factory.config.use_local_models:
            total_media_cost = sum(f.get('generation_cost', 0.0) for f in media_files)
            response_data["metadata"]["total_media_cost"] = total_media_cost
            response_data["metadata"]["media_count"] = len(media_files)

        return response_data

    def _get_fallback_response(self, agent_type: str, error: Exception) -> Dict[str, Any]:
        """
        Возвращает fallback-ответ при критических ошибках
        """
        fallback_messages = {
            "diagnostic": (
                "Извините, у меня временные трудности. "
                "Давайте попробуем начать с простого вопроса — зачем вам нужен английский язык?"
            ),
            "curator": (
                "Произошла ошибка при подготовке вашего учебного плана. "
                "Пожалуйста, повторите запрос через несколько минут."
            ),
            "teacher": (
                "Извините, сейчас я не могу провести урок из-за технических проблем. "
                "Давайте попробуем с другим вопросом или повторим попытку позже."
            )
        }

        default_message = (
            "Извините, я столкнулся с технической проблемой. "
            "Пожалуйста, попробуйте повторить ваш запрос через несколько минут."
        )

        return {
            "message": fallback_messages.get(agent_type, default_message),
            "agent_state": {
                "engagement_change": -1,
                "error": str(error)
            },
            "success": False,
            "metadata": {
                "error": str(error),
                "fallback_used": True,
                "timestamp": datetime.now().isoformat()
            }
        }

    def _log_generation_results(self, agent_type: str, generation_result: GenerationResult,
                                media_files: List[Dict[str, Any]]):
        """
        Логирует результаты генерации для мониторинга
        """
        log_message = (
            f"Agent response generated successfully. "
            f"Agent: {agent_type}, "
            f"Model: {generation_result.model_used}, "
            f"Cost: ${generation_result.cost:.6f}, "
            f"Time: {generation_result.generation_time:.2f}s"
        )

        if media_files and not self.llm_factory.config.use_local_models:
            total_media_cost = sum(f.get('generation_cost', 0.0) for f in media_files)
            log_message += f", Media files: {len(media_files)}, Media cost: ${total_media_cost:.6f}"

        logger.info(log_message)

    # async def _generate_media_files(self, instructions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    #     """
    #     Генерирует медиафайлы на основе инструкций от агента
    #
    #     Args:
    #         instructions: Список инструкций для генерации медиа
    #
    #     Returns:
    #         Список сгенерированных медиафайлов с метаданными
    #     """
    #     generated_files = []
    #
    #     for instruction in instructions:
    #         try:
    #             media_type = instruction.get('type')
    #             prompt = instruction.get('prompt', '')
    #             media_subtype = instruction.get('subtype', '')  # Например, 'png' для изображений
    #
    #             if not media_type or not prompt:
    #                 logger.warning(f"Skipping media generation due to missing type or prompt: {instruction}")
    #                 continue
    #
    #             logger.info(f"Generating {media_type} with prompt: {prompt[:100]}...")
    #
    #             # Генерация медиа
    #             media_result = await self.llm_factory.generate_media_response(
    #                 media_type=media_type,
    #                 prompt=prompt
    #             )
    #
    #             if not media_result.get('success'):
    #                 logger.error(f"Media generation failed for {media_type}: {media_result.get('error')}")
    #                 continue
    #
    #             # Сохранение файла
    #             file_info = await self._save_generated_media(
    #                 media_type=media_type,
    #                 media_data=media_result.get('data'),
    #                 prompt=prompt,
    #                 metadata=instruction
    #             )
    #
    #             if file_info:
    #                 generated_files.append({
    #                     **file_info,
    #                     'generation_cost': media_result.get('cost', 0.0),
    #                     'original_prompt': prompt
    #                 })
    #                 logger.info(f"Successfully generated and saved {media_type}: {file_info['url']}")
    #
    #         except Exception as e:
    #             logger.error(f"Error generating media file: {str(e)}")
    #             continue
    #
    #     return generated_files

    async def _save_generated_media(
            self,
            media_type: str,
            media_data: bytes,
            prompt: str,
            metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """
        Сохраняет сгенерированный медиа-файл в хранилище Django

        Важно: Этот метод работает ТОЛЬКО с OpenAI, так как локальные модели
        не генерируют медиа
        """
        try:
            # Генерация уникального имени файла
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_uuid = uuid.uuid4().hex[:8]

            if media_type == 'image':
                file_name = f"ai_gen_img_{timestamp}_{file_uuid}.png"
                content_type = "image/png"
                folder = "generated/images/"
            elif media_type == 'audio':
                file_name = f"ai_gen_audio_{timestamp}_{file_uuid}.mp3"
                content_type = "audio/mpeg"
                folder = "generated/audio/"
            else:
                logger.warning(f"Unsupported media type for saving: {media_type}")
                return None

            # Путь к файлу
            file_path = os.path.join(folder, file_name)

            # Сохранение файла
            file_content = ContentFile(media_data)
            saved_path = default_storage.save(file_path, file_content)

            # Генерация URL
            file_url = default_storage.url(saved_path)

            # Подготовка метаданных для ответа
            file_info = {
                'url': file_url,
                'type': media_type,
                'mime_type': content_type,
                'path': saved_path,
                'size': len(media_data),
                'ai_generated': True,
                'generation_prompt': prompt,
                'metadata': metadata
            }

            return file_info

        except Exception as e:
            logger.error(f"Error saving generated media file: {str(e)}")
            return None

    # Следующие методы остались без изменений из оригинальной реализации
    # Они совместимы с новой архитектурой

    def _get_examples(self, agent_type: str) -> list:
        """Возвращает примеры для конкретного типа агента"""
        if agent_type == 'diagnostic':
            return DIAGNOSTIC_EXAMPLES
        elif agent_type == 'curator':
            return CURATOR_EXAMPLES
        return []

    def _format_examples(self, examples: list) -> str:
        """Форматирует примеры для промпта"""
        formatted = ""
        for example in examples:
            formatted += f"Контекст: {example['context']}\n"
            formatted += f"Вход: {example['input']}\n"
            formatted += f"Выход: {json.dumps(example['output'], ensure_ascii=False)}\n\n"
        return formatted

    def _format_history(self, history: list) -> str:
        """Форматирует историю диалога для промпта"""
        if not history:
            return "Диалог только начинается."

        formatted = ""
        for entry in history[-5:]:  # последние 5 сообщений для контекста
            formatted += f"Студент: {entry['user_message']}\n"
            if isinstance(entry['agent_response'], dict):
                formatted += f"Репетитор: {entry['agent_response'].get('message', '...')}\n\n"
            else:
                formatted += f"Репетитор: {entry['agent_response']}\n\n"
        return formatted