import logging
import time
import uuid
from collections import defaultdict

from django.utils import timezone
import random

from assessment.models import QuestionInstance, TestSession, TestAnswer, CEFRLevel
from curriculum.models import Task
from users.models import Student

from utils.setup_logger import setup_logger

logger = logging.getLogger(__name__)

# Конфигурационные параметры
DIAGNOSTIC_ORDER = ["A2", "B1", "B2", "C1"]
DIAGNOSTIC_COUNT = len(DIAGNOSTIC_ORDER) * 2

# количество вопросов в одном пакете
MAIN_QUESTIONS_PACKET_SIZE = 12
# количество пакетов (итераций)
MAIN_QUESTIONS_ITERATION_COUNTER = 0
# общий максимум вопросов
MAIN_QUESTIONS_LIMIT = DIAGNOSTIC_COUNT + MAIN_QUESTIONS_PACKET_SIZE * MAIN_QUESTIONS_ITERATION_COUNTER

EVALUATION_TIMEOUT_MAX_RETRIES = 10

assessment_logger = setup_logger(name=__file__, log_dir="logs/core/assessment", log_file="assessment.log")


def can_generate_next_main_packet(session):
    """
    Возвращает True, если разрешено генерировать следующую партию основных вопросов.
    """
    total_created = QuestionInstance.objects.filter(session=session).count()
    print(f"{total_created=}")
    # 1) даже диагностическая часть ещё не создана полностью
    if total_created < DIAGNOSTIC_COUNT:
        print("total_created < DIAGNOSTIC_COUNT", total_created < DIAGNOSTIC_COUNT)
        return False

    # 2) вычисляем сколько основных вопросов уже было создано
    main_created = total_created - DIAGNOSTIC_COUNT
    print(f"{main_created=}")

    packets_done = main_created // MAIN_QUESTIONS_PACKET_SIZE
    print(f"{packets_done=}")
    print("packets_done < MAIN_QUESTIONS_ITERATION_COUNTER", packets_done < MAIN_QUESTIONS_ITERATION_COUNTER)

    return packets_done < MAIN_QUESTIONS_ITERATION_COUNTER


def create_diagnostic_questions(session):
    """
    Создаст стартовый диагностический пакет из одного вопроса по каждому уровню CEFR.
    Замена CEFRQuestion → Task(isdiagnostic=True).
    """
    bulk_container = []

    for level in DIAGNOSTIC_ORDER * 2:
        print(level)
        task = pick_random_diagnostic_task(level)
        print(task)
        if task:
            question_instance = QuestionInstance(
                session=session,
                task=task,
                # source_type остается для legacy совместимости
            )
            print(question_instance)
            bulk_container.append(question_instance)

    if bulk_container:
        created_instances = QuestionInstance.objects.bulk_create(bulk_container)
        logger.info(f"Создан диагностический пакет для TestSession {session.id}: "
                    f"{len(created_instances)} вопросов по уровням {DIAGNOSTIC_ORDER}")
        return True

    logger.error(f"Ошибка создания диагностического пакета для TestSession {session.id}: "
                 f"не найдено диагностических Tasks по уровням {DIAGNOSTIC_ORDER}")
    return False


def pick_random_diagnostic_task(level: str) -> Task:
    """Выбор случайного диагностического задания по уровню"""
    tasks = Task.objects.filter(
        is_active=True,
        difficulty_cefr=level
    ).order_by('?')[:1]  # random

    return tasks.first()


def determine_range_from_diagnostic(session):
    """Определяет по оценкам теста примерный уровень пользователя
    """
    # TODO УРОВНИ ПРИМЕРНЫЕ НУЖНА ПОДСТРОЙКА СПЕЦИАЛИСТОМ или вызов LLM
    NORMALIZED_RANGES = [
        {"max": 0.35, "range": ("A2", "A2")},
        {"max": 0.55, "range": ("A2", "B1")},
        {"max": 0.75, "range": ("B1", "B2")},
        {"max": 1.01, "range": ("B2", "C1")},
    ]
    DIAGNOSTIC_ORDER = ["A2", "B1", "B2", "C1"]

    answers = TestAnswer.objects.select_related("question__task").filter(question__session=session)
    for retry in range(EVALUATION_TIMEOUT_MAX_RETRIES):
        if not answers.filter(evaluation_status="pending").exists():
            break
        time.sleep(1)
    else:
        # сюда попадаем, если break НЕ сработал
        logger.warning(
            "Timeout while waiting for answer evaluation",
            extra={"session_id": session.id}
        )

    for ans in answers:
        print(ans.__dict__)

    level_results = defaultdict(list)

    # 1. Агрегация ответов
    for answer in answers:
        level = answer.question.task.difficulty_cefr

        ai_feedback = answer.ai_feedback or {}
        is_correct = ai_feedback.get("is_correct") is True

        level_results[level].append(is_correct)

    total_answers = sum(len(v) for v in level_results.values())
    if total_answers == 0:
        return DIAGNOSTIC_ORDER[0], DIAGNOSTIC_ORDER[0]

    correct_answers = sum(
        is_correct
        for results in level_results.values()
        for is_correct in results
    )

    # 2. Нормализация
    normalized_score = correct_answers / total_answers
    print(f"{normalized_score=}")

    # 3. Определение вилки
    for item in NORMALIZED_RANGES:
        if normalized_score <= item["max"]:
            return item["range"]

    return DIAGNOSTIC_ORDER[0], DIAGNOSTIC_ORDER[-1]


def load_questions_for_range(session, low_level: str, high_level: str, exclude_tasks=None):
    """
    Загрузка основного пакета задач по диапазону уровней.
    Исключение уже использованных задач + приоритет разным skillfocus.
    """
    if exclude_tasks is None:
        exclude_tasks = []

    # Сначала пробуем найти задачи с разными skillfocus для покрытия
    used_skills = set()
    selected_tasks = []

    available_tasks = Task.objects.filter(
        is_active=True,
        difficulty_cefr__in=[low_level, high_level],
    ).exclude(id__in=exclude_tasks).select_related('lesson').distinct()

    # Группируем по skillfocus для разнообразия
    for task in available_tasks.order_by('?'):
        task_skills = set(task.lesson.skill_focus) if task.lesson else set()

        # Если есть непокрытые skills или первый выбор
        if not selected_tasks or any(skill not in used_skills for skill in task_skills):
            selected_tasks.append(task)
            used_skills.update(task_skills)

            if len(selected_tasks) >= MAIN_QUESTIONS_PACKET_SIZE:
                break

    # Если не хватило с разными skills - добираем любые
    while len(selected_tasks) < MAIN_QUESTIONS_PACKET_SIZE:
        remaining = available_tasks.exclude(
            id__in=[t.id for t in selected_tasks]
        ).order_by('?')[:1]
        if not remaining.exists():
            break
        selected_tasks.append(remaining.first())

    # Создаем QuestionInstance
    bulk_container = []
    for task in selected_tasks:
        question_instance = QuestionInstance(
            session=session,
            task=task,
        )
        bulk_container.append(question_instance)

    if bulk_container:
        QuestionInstance.objects.bulk_create(bulk_container)
        logger.debug(f"Загружен пакет задач для TestSession {session.id}: "
                     f"{len(bulk_container)} задач [{low_level}-{high_level}]")


def get_next_unanswered_question(session):
    """Без изменений - первая непройденная"""
    return session.questions.filter(
        answer__isnull=True
    ).select_related('task').order_by('created_at').first()


# ---------- Финализация сессии и расчёт уровня ----------

def finalize_session(session):
    """
    Считаем итоговые метрики и определяем итоговый уровень.
    Сохраняем protocol_json и отмечаем finished_at.
    Возвращает protocol (dict).
    """
    # 1. Сбор ответов
    answers = TestAnswer.objects.filter(question__session=session)
    total_questions = answers.count()

    # 2. Агрегация по уровню CEFR
    level_results = defaultdict(list)
    for answer in answers:
        level = answer.question.task.difficulty_cefr
        is_correct = (answer.ai_feedback or {}).get("is_correct") is True
        level_results[level].append(is_correct)

    # 3. Считаем долю правильных ответов по каждому уровню
    level_scores = {}
    for level, results in level_results.items():
        level_scores[level] = sum(results) / len(results) if results else 0.0

    print(f"Level scores: {level_scores}")

    # 4. Определяем один уровень
    LEVEL_ORDER = ["A2", "B1", "B2", "C1"]

    if level_scores:
        max_score = max(level_scores.values())
        best_levels = [lvl for lvl, score in level_scores.items() if score == max_score]

        # Выбираем самый низкий уровень из лучших
        level = min(best_levels, key=lambda x: LEVEL_ORDER.index(x))
    else:
        level = "A2"  # минимальный уровень по умолчанию

    print(f"Determined CEFR level (conservative): {level}")

    protocol = {
        "total_questions": total_questions,
        "level_scores": level_scores,
        "estimated_level": level,
    }
    protocol_answers = []
    for a in answers.select_related("question"):
        protocol_answers.append({
            "question_id": str(a.question.task.id),
            "question": a.question.task.content,
            "response_text": a.response_text,
            "score": a.score,
            "ai_feedback": a.ai_feedback
        })
    protocol["answers"] = protocol_answers
    session.estimated_level = level
    session.protocol_json = protocol
    session.finished_at = timezone.now()
    session.save(update_fields=["estimated_level", "protocol_json", "finished_at"])

    Student.objects.update_or_create(
        user=session.user,
        defaults={"english_level": level}
    )

    return protocol
