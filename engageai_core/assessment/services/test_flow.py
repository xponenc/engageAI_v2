import logging
import uuid

from django.utils import timezone
import random

from assessment.models import QuestionInstance, TestSession, TestAnswer, CEFRLevel
from curriculum.models import Task
from users.models import Student

from utils.setup_logger import setup_logger

logger = logging.getLogger(__name__)

# Конфигурационные параметры
DIAGNOSTIC_ORDER = ["A2", "B1", "B2", "C1"]
DIAGNOSTIC_COUNT = len(DIAGNOSTIC_ORDER)

# количество вопросов в одном пакете
MAIN_QUESTIONS_PACKET_SIZE = 12
# количество пакетов (итераций)
MAIN_QUESTIONS_ITERATION_COUNTER = 0
# общий максимум вопросов
MAIN_QUESTIONS_LIMIT = DIAGNOSTIC_COUNT + MAIN_QUESTIONS_PACKET_SIZE * MAIN_QUESTIONS_ITERATION_COUNTER

assessment_logger = setup_logger(name=__file__, log_dir="logs/core/assessment", log_file="assessment.log")


# ---------- Вспомогательные низкоуровневые функции ----------

# def pick_random_question(level: str) -> CEFRQuestion | None:
#     """Выбор случайного вопроса из уровня"""
#     qs = CEFRQuestion.objects.filter(level=level).values_list("id", flat=True)
#     if not qs:
#         return None
#     qid = random.choice(list(qs))
#     return CEFRQuestion.objects.get(id=qid)

#
# def _clone_question_to_instance(session, source_obj, source_type="cefr"):
#     """
#     Создаёт QuestionInstance, копируя question_json.
#     source_obj может быть CEFRQuestion или результат LLM (dict).
#     """
#     if source_type == "cefr":
#         q = source_obj
#         qi = QuestionInstance.objects.create(
#             session=session,
#             source_type="cefr",
#             source_question_id=q.id,
#             question_json={
#                 "id": str(q.id),
#                 "type": q.type,
#                 "level": q.level,
#                 "question_text": q.question_text,
#                 "options": q.options,
#                 "correct_answer": q.correct_answer,
#                 "explanation": q.explanation
#             }
#         )
#         return qi
#     else:
#         # source_obj уже dict = question_json
#         qi = QuestionInstance.objects.create(
#             session=session,
#             source_type="llm",
#             source_question_id=source_obj.get("id") or uuid.uuid4(),
#             question_json=source_obj
#         )
#         return qi


def can_generate_next_main_packet(session):
    """
    Возвращает True, если разрешено генерировать следующую партию основных вопросов.
    """
    total_created = QuestionInstance.objects.filter(session=session).count()
    # 1) даже диагностическая часть ещё не создана полностью
    if total_created < DIAGNOSTIC_COUNT:
        print("total_created < DIAGNOSTIC_COUNT", total_created < DIAGNOSTIC_COUNT)
        return False

    # 2) вычисляем сколько основных вопросов уже было создано
    main_created = total_created - DIAGNOSTIC_COUNT

    packets_done = main_created // MAIN_QUESTIONS_PACKET_SIZE
    print("packets_done < MAIN_QUESTIONS_ITERATION_COUNTER", packets_done < MAIN_QUESTIONS_ITERATION_COUNTER)

    return packets_done < MAIN_QUESTIONS_ITERATION_COUNTER


# ---------- Диагностический этап ----------
#
# def create_diagnostic_questions(session: TestSession):
#     """
#     Создаст стартовый диагностический пакет из одного вопроса по каждому уровню
#     на С2 не создается
#     """
#     bulk_container = []
#     for level in DIAGNOSTIC_ORDER:
#         q = pick_random_question(level)
#         if q:
#             q_i = QuestionInstance(
#                 session=session,
#                 source_type="cefr",
#                 source_question_id=q.id,
#                 question_json={
#                     "id": str(q.id),
#                     "level": q.level,
#                     "type": q.type,
#                     "question_text": q.question_text,
#                     "options": q.options,
#                     "correct_answer": q.correct_answer,
#                 }
#             )
#             bulk_container.append(q_i)
#     if bulk_container:
#         qi_created = QuestionInstance.objects.bulk_create(bulk_container)
#
#         assessment_logger.debug(f"Создан первичный пакет из QuestionInstance"
#                                 f" для TestSession {session.id}: [{qi_created}] ")
#         return
#
#     assessment_logger.error(f"Ошибка при первичный пакет QuestionInstance для TestSession {session.id}"
#                             f" не найдено подходящих вопросов по уровням {DIAGNOSTIC_ORDER}")

def create_diagnostic_questions(session):
    """
    Создаст стартовый диагностический пакет из одного вопроса по каждому уровню CEFR.
    Замена CEFRQuestion → Task(isdiagnostic=True).
    """
    bulk_container = []

    for level in DIAGNOSTIC_ORDER:
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


# ---------- Определение диапазона по диагностическим ответам ----------

def determine_range_from_diagnostic(session):
    """Определяет по оценкам теста примерный уровень пользователя
    """
    # TODO УРОВНИ ПРИМЕРНЫЕ НУЖНА ПОДСТРОЙКА СПЕЦИАЛИСТОМ
    LEVEL_RANGES = [
        {"max": 2.5, "range": ("A2", "B1")},
        {"max": 3.5, "range": ("B1", "B2")},
        {"max": 4.5, "range": ("B2", "C1")},
    ]

    DEFAULT_RANGE = ("A2", "B1")

    answers = TestAnswer.objects.filter(question__session=session).order_by('answered_at')[:DIAGNOSTIC_COUNT]
    total = sum([a.score or 0 for a in answers])
    level_range = DEFAULT_RANGE

    for rule in LEVEL_RANGES:
        if total < rule["max"]:
            level_range = rule["range"]
            break
    assessment_logger.info(
        f"{session} определение промежуточного уровня: score={total}, range={level_range}"
    )
    return level_range



# ---------- Загрузка основного набора ----------
#
# def load_questions_for_range(session, low, high, total=MAIN_QUESTIONS_PACKET_SIZE):
#     """
#     Загружает вопросы для основной фазы: половина lower, половина higher.
#     Смешивает их в случайном порядке.
#     """
#     # Какие вопросы уже использованы в сессии:
#     used_cefr_ids = (
#         QuestionInstance.objects.filter(
#             session=session,
#             source_type=SourceType.CEFR
#         ).values_list("source_question_id", flat=True)
#     )
#
#     half = total // 2
#     qs_low = list(
#         CEFRQuestion.objects
#         .filter(level=low)
#         .exclude(id__in=used_cefr_ids)
#         .order_by("?")[:half]
#     )
#
#     qs_high = list(
#         CEFRQuestion.objects
#         .filter(level=high)
#         .exclude(id__in=used_cefr_ids)
#         .order_by("?")[:total - half]
#     )
#     chosen = qs_low + qs_high
#     random.shuffle(chosen)
#     for q in chosen:
#         _clone_question_to_instance(session, q, source_type="cefr")


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
        task_skills = set(task.lesson.skillfocus) if task.lesson else set()

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



# ---------- Получение следующего вопроса ----------

# def get_next_unanswered_question(session):
#     """
#     Возвращает следующий QuestionInstance без ответов (first created order).
#     """
#     return QuestionInstance.objects.filter(session=session).exclude(answer__isnull=False).order_by(
#         'created_at').first()



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
    answers = TestAnswer.objects.filter(question__session=session)
    total_questions = answers.count()
    total_score = sum([a.score or 0.0 for a in answers])
    ratio = (total_score / total_questions) if total_questions else 0.0

    # TODO УРОВНИ ПРИМЕРНЫЕ НУЖНА ПОДСТРОЙКА СПЕЦИАЛИСТОМ - хотя на всякий случай мы отправим все на оценку в LLM
    if ratio < 0.4:
        level = CEFRLevel.A1
    elif ratio < 0.55:
        level = CEFRLevel.A2
    elif ratio < 0.7:
        level = CEFRLevel.B1
    elif ratio < 0.85:
        level = CEFRLevel.B2
    elif ratio < 0.95:
        level = CEFRLevel.C1
    else:
        level = CEFRLevel.C2

    protocol = {
        "total_questions": total_questions,
        "total_score": total_score,
        "ratio": round(ratio, 3),
        "estimated_level": level,
        "answers": []
    }

    for a in answers.select_related("question"):
        protocol["answers"].append({
            "question_id": str(a.question.task.id),
            "question": a.question.task.content,
            "answer_text": a.answer_text,
            "score": a.score,
            "ai_feedback": a.ai_feedback
        })

    session.estimated_level = level
    session.protocol_json = protocol
    session.finished_at = timezone.now()
    session.save(update_fields=["estimated_level", "protocol_json", "finished_at"])

    Student.objects.update_or_create(
        user=session.user,
        defaults={"english_level": level}
    )

    return protocol
