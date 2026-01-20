from typing import List
import numpy as np


def calculate_trend(values: List[float]) -> float:
    """
    Рассчитывает тренд навыка.
    Используется линейная регрессия по времени.

    Возвращает:
    -1.0 .. 1.0
    """
    if len(values) < 2:
        return 0.0

    x = np.arange(len(values))
    y = np.array(values)

    slope = np.polyfit(x, y, 1)[0]

    # нормализация
    return max(-1.0, min(1.0, slope))


def calculate_stability(values: List[float]) -> float:
    """
    Оценивает устойчивость навыка.
    Чем меньше разброс — тем выше стабильность.
    """
    if len(values) < 3:
        return 0.0

    std = np.std(values)
    return max(0.0, min(1.0, 1 - std))
