# ARCHITECTURE.md

## Архитектура системы адаптивного обучения (v1)

Документ описывает целостную архитектуру **Экосистемы нейро-репетитора** версии v1.

Цель архитектуры:
- обеспечить управляемое, адаптивное обучение;
- чётко разделить ответственность между логикой обучения, оценкой, адаптацией и объяснимостью;
- зафиксировать, что **LLM — инструмент анализа и генерации текста, но не источник решений**.

---

## 1. Ключевые принципы

### 1.1 Разделение ответственности

| Слой | Ответственность |
|-----|----------------|
| Curriculum | Структура обучения (Course, Lesson, Task) |
| LearningAgent | Оркестрация обучения и переходов |
| Assessment | Оценка ответов студента |
| Metrics | Агрегация и интерпретация результатов |
| Adaptive Decisions | Принятие решений о дальнейшем пути |
| Skill System | Хранение и обновление навыков |
| Explainability | Объяснение решений человеку |
| Feedback | Мотивационная обратная связь |

---

## 2. Основные сущности

### 2.1 Course

**Назначение:**
- Дидактическая программа.
- Не зависит от конкретного студента.

Свойства:
- тема
- уровень
- порядок уроков

> Курс — это "что изучаем", а не "для кого".

---

### 2.2 Lesson

**Назначение:**
- Логический учебный шаг.
- Может быть адаптирован под студента.

Свойства:
- skill_focus (JSON, стандартизированные SkillDomain)
- сложность
- порядок

---

### 2.3 Task

**Назначение:**
- Минимальная единица активности.
- Связана с одним или несколькими навыками.

---

## 3. LearningAgent (главный оркестратор)

**Расположение:** `learning/services/agent.py`

**Роль:**
- управляет потоком обучения;
- не принимает педагогических решений;
- вызывает специализированные сервисы.

Flow:
```
Course → Lesson → Task → Assessment → Metrics → Decision → Transition
```

---

## 4. Assessment

### 4.1 AutoAssessment

- Rule-based / ML
- Быстрые проверки

### 4.2 LLMAssessmentService

**Расположение:** `assessment/services/llm.py`

Задачи:
- интерпретация сложных ответов;
- нормализация в структурированный формат.

LLM возвращает:
- scores по навыкам
- confidence
- пояснения

> LLM не решает, что делать дальше.

---

## 5. Skill System

### 5.1 SkillProfile (текущее состояние)

- один навык = один объект
- всегда актуальное состояние

### 5.2 SkillTrajectory (история)

- снапшоты изменений
- используется для аналитики и объяснимости

### 5.3 SkillProfileUpdater

Flow:
```
Assessment → SkillProfileUpdater → SkillProfile + SkillTrajectory
```

---

## 6. Metrics

### 6.1 LessonMetrics

**Расположение:** `metrics/models.py`

Содержит:
- success_ratio
- confidence
- failure_streak
- skill_deltas

Используется:
- Adaptive Engine
- Feedback
- Explainability

---

## 7. Adaptive Decisions

### 7.1 Decision Engine

**Расположение:** `curriculum/services/decisions.py`

Выдаёт:
- ADVANCE
- REPEAT
- SIMPLIFY

> Решения детерминированы и объяснимы.

---

## 8. Lesson Transitions

**Расположение:** `curriculum/models/lesson_transition.py`

Хранит:
- откуда → куда
- почему
- на основании каких метрик

Используется для:
- explainability
- teacher override

---

## 9. Explainability

### 9.1 ExplainabilityEngine

**Расположение:** `explainability/services/engine.py`

Функции:
- почему принято решение;
- какие навыки повлияли;
- что изменилось со временем.

### 9.2 Human-readable narratives (LLM)

LLM используется:
- для переформулировки объяснений
- для teacher / admin / student UI

---

## 10. Feedback System

### 10.1 FeedbackBuilder

- формирует мотивационную обратную связь;
- не влияет на обучение.

### 10.2 YAML Templates

**Расположение:** `feedback/templates/*.yaml`

Роль:
- контент и вариативность;
- локализация;
- A/B тесты.

---

## 11. Teacher & Admin Dashboard

**Расположение:** `dashboards/`

Содержит:
- агрегированные метрики;
- траектории навыков;
- причины адаптивных решений;
- возможность override.

---

## 12. Student-facing Explainability

- упрощённые объяснения;
- поддержка мотивации;
- без перегрузки деталями.

---

## 13. End-to-End Flow (v1)

```
Task
 ↓
StudentTaskResponse
 ↓
Assessment (Auto / LLM)
 ↓
SkillProfileUpdater
 ↓
LessonMetricsCalculator
 ↓
DecisionEngine
 ↓
LessonTransition
 ↓
FeedbackBuilder
```

---

## 14. Что сознательно НЕ делаем в v1

- LLM как decision maker
- RL / self-modifying rules
- скрытую адаптацию без объяснений

---

## 15. Готовность к v2

Архитектура допускает:
- multiple agents
- персональные курсы
- reinforcement learning
- cross-course skill graphs

Без ломки v1.

---

**Статус:** зафиксировано как базовая архитек