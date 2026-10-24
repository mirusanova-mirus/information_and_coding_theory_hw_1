# Модульные тесты для проверки корректности работы с источником

# Начало генерации Codex
import copy
import json
import unittest
from fractions import Fraction
from pathlib import Path

from source import parse_distribution, parse_source


class SourceTests(unittest.TestCase):
    def setUp(self):
        # Перед каждым тестом заново читаем исходные данные
        path = Path(__file__).resolve().parents[1] / "examples" / "source14.json"
        self.data = json.loads(path.read_text(encoding="utf-8"))

    def test_variant_source(self):
        # Проверяем алфавит, число моделей, длину периода и одну вероятность
        source = parse_source(self.data)
        self.assertEqual(source.alphabet, ["A", "B", "C"])
        self.assertEqual(len(source.models), 4)
        self.assertEqual(len(source.source), 7)
        self.assertEqual(source.models["model_4"]["A"], Fraction(3, 4))

    def test_exact_normalization(self):
        # Проверяем точный перевод десятичных строк в дроби и сумму 1
        result = parse_distribution({"A": "0.1", "B": "0.2", "C": "0.7"}, "model")
        self.assertEqual(sum(result.values()), 1)
        self.assertEqual(result["A"], Fraction(1, 10))

    def test_invalid_probabilities(self):
        # Каждое неверное распределение должно вызвать ValueError
        for distribution in [
            {"A": "1/2", "B": "1/3"},  # Сумма не равна 1
            {"A": "-1", "B": "2"},  # Отрицательная вероятность
            {"A": 1},  # Число вместо строки
            {"A": "1/0"},  # Нулевой знаменатель
            {},  # Пустое распределение
        ]:
            with self.subTest(distribution=distribution):
                with self.assertRaises(ValueError):
                    parse_distribution(distribution, "model")

    def test_unknown_model(self):
        # Подставляем неизвестную модель и проверяем сообщение об ошибке
        self.data["switches"]["switch_1"] = {"missing": "1"}
        with self.assertRaisesRegex(ValueError, "неизвестные имена"):
            parse_source(self.data)

    def test_invalid_sequence(self):
        # Проверяем пустой список, неизвестное имя, число вместо имени и None
        for sequence in [[], ["missing"], [123], None]:
            with self.subTest(sequence=sequence):
                data = copy.deepcopy(self.data)
                data["source"] = sequence
                with self.assertRaises(ValueError):
                    parse_source(data)


# Запускаем тесты при прямом запуске файла
if __name__ == "__main__":
    unittest.main()
# Конец генерации Codex