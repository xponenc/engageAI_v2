# curriculum/services/content_generation/methodological_plan_loader.py
import asyncio
import json
import logging
import os
import sys
from pathlib import Path
from pprint import pprint
from typing import Dict, List, Tuple, Any
from collections import defaultdict, Counter

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parents[3]
FIXTURES_PATH = BASE_DIR / "fixtures" / "learning_objectives"

SKILL_ORDER = ["grammar", "vocabulary", "reading", "listening", "writing", "speaking"]
LEVEL_ORDER: List[str] = ["A2", "B1", "B2", "C1"]


class MethodologicalPlanLoader:
    """Загрузка и валидация полного методологического плана"""

    async def load_full_plan(self) -> Dict[str, Any]:
        """Загружает все JSON файлы и возвращает структурированный план"""
        plan = {}
        missing_files = []
        total_units = 0

        for level in LEVEL_ORDER:
            plan[level] = {}
            for skill in SKILL_ORDER:
                file_path = FIXTURES_PATH / f"{level.lower()}_{skill}.json"

                units = await self._load_single_file(file_path, level, skill)
                plan[level][skill] = units
                total_units += len(units)

                if not units:
                    missing_files.append(str(file_path))

        logger.info(f"Методплан загружен: {total_units} юнитов из {len(LEVEL_ORDER) * len(SKILL_ORDER)} файлов")

        if missing_files:
            logger.warning(f"Отсутствуют файлы: {missing_files}")

        return {
            'plan': plan,
            'total_units': total_units,
            'coverage': len([u for level in plan.values() for skill in level.values() for u in skill]) / total_units
        }

    async def _load_single_file(self, file_path: Path, expected_level: str, expected_skill: str) -> List[Dict]:
        """Загрузка и валидация одного JSON файла"""
        if not file_path.exists():
            return []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data: List[Dict] = json.load(f)

            # Фильтрация и сортировка
            valid_units = [
                unit for unit in data
                if (unit.get('cefr_level') == expected_level and
                    unit.get('skill_domain') == expected_skill)
            ]

            # Сортировка по order_in_level
            valid_units.sort(key=lambda x: x.get('order_in_level', float('inf')))

            logger.debug(f"{file_path}: {len(valid_units)} валидных юнитов")
            return valid_units

        except json.JSONDecodeError as e:
            logger.error(f"Ошибка JSON в {file_path}: {e}")
            return []
        except Exception as e:
            logger.error(f"Ошибка загрузки {file_path}: {e}")
            return []


if __name__ == "__main__":
    p = MethodologicalPlanLoader()
    plan = asyncio.run(p.load_full_plan())
    pprint(plan)