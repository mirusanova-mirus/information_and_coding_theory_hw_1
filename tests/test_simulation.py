# Модульные и интеграционные тесты генерации и моделирования источников

# Начало генерации Codex
import copy
import json
import signal
import subprocess
import sys
import unittest
from fractions import Fraction as F
from itertools import islice
from pathlib import Path

from source import estimate, load_source, parse_source

ROOT = Path(__file__).resolve().parents[1]

class SimulationTests(unittest.TestCase):
    def test_generation_and_seed(self):
        # Проверяем повторяемость seed, допустимые символы и результат с другим seed
        for name in ("source14", "iid14", "markov14", "nonergodic14"):
            with self.subTest(source=name):
                source = load_source(ROOT / f"examples/{name}.json")
                first = list(islice(source.generate(14), 100))
                self.assertEqual(first, list(islice(source.generate(14), 100)))
                self.assertTrue(set(first) <= set(source.alphabet))
                self.assertNotEqual(first, list(islice(source.generate(15), 100)))

    def test_periodic_probabilities(self):
        # Сверяем точные вероятности с ручным расчётом для периодического источника
        source = load_source(ROOT / "examples/source14.json")
        self.assertEqual(source.exact_probabilities(["A", "B"]), (F(35, 432), F(85, 648)))
        word = list("ABCABCABC")
        # Вероятность A в каждой из семи фаз периода
        phases = [F(5, 12), F(5, 9), F(5, 12), F(5, 12), F(5, 9), F(5, 9), F(5, 12)]
        # Независимость тактов позволяет перемножить вероятности символов
        expected = F(1)
        for i, a in enumerate(word):
            expected *= {"A": phases[i % 7], "B": F(3, 4) - phases[i % 7], "C": F(1, 4)}[a]
        self.assertEqual(source.probability(word), expected)
        self.assertEqual(source.probability(["?"]), 0)
        self.assertEqual(source.probability([]), 1)

    def test_markov_memory(self):
        # Сверяем вероятности блоков для источника с памятью d=3
        source = load_source(ROOT / "examples/markov14.json")
        self.assertEqual(source.probability(list("AAA")), F(1, 27))
        self.assertEqual(source.probability(list("AAAA")), F(1, 54))
        self.assertEqual(source.exact_probabilities(["A", "B"]), (F(1, 9), F(1, 9)))

    def test_nonergodic_mixture(self):
        # Проверяем безусловные вероятности смеси двух сохраняемых компонент
        source = load_source(ROOT / "examples/nonergodic14.json")
        self.assertEqual(source.probability(["A"]), F(1, 3))
        self.assertEqual(source.probability(["A", "A"]), F(5, 36))
        self.assertEqual(source.exact_probabilities(["A", "B"]), (F(1, 9), F(1, 9)))

    def test_frequency_and_overlap(self):
        # У источника из одних A блок длины 101 встречается в N-100 окнах при N >= 101
        source = load_source(ROOT / "tests/constant.json")
        first, average, rows = estimate(source, ["A"] * 101, 123)
        self.assertEqual((first, average), (1, 1))
        self.assertEqual(set(rows), {100, 123, 1000, 10000, 100000, 1000000})
        for n, (hits, frequency) in rows.items():
            self.assertEqual(hits, max(0, n - 100))
            # Если полного блока ещё нет, частота не определена
            self.assertEqual(frequency, None if n < 101 else 1)

    def test_frequency_matches_generated_prefix(self):
        # Сравниваем вывод командной строки с ручным подсчётом по той же реализации
        source = load_source(ROOT / "examples/source14.json")
        result = subprocess.run([sys.executable, "source.py", "estimate", "examples/source14.json",
                                 "--N", "100", "--word", "examples/word.json", "--seed", "14"],
                                cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        sequence = list(islice(source.generate(14), 100))
        # Считаем совпадения AB с учётом перекрывающихся окон
        hits = sum(sequence[i:i + 2] == ["A", "B"] for i in range(99))
        self.assertEqual(F(output["frequency"]), F(hits, 99))
        self.assertEqual(F(output["first"]), F(35, 432))
        self.assertEqual(F(output["average"]), F(85, 648))
        self.assertEqual({row["N"] for row in output["table"]}, {100, 1000, 10000, 100000, 1000000})

    def test_invalid_measurement(self):
        # Проверяем неверный блок, неположительное N и N меньше длины блока
        source = load_source(ROOT / "examples/source14.json")
        for word, n in [([], 10), ([1], 10), ("AB", 10), (["A"], 0), (["A", "B"], 1)]:
            with self.subTest(word=word, n=n), self.assertRaises(ValueError):
                estimate(source, word, n)

    def test_invalid_extension(self):
        # Проверяем структуру process, начальные состояния и цели переходов
        data = json.loads((ROOT / "examples/nonergodic14.json").read_text())
        invalid = [None, {}, {"initial": {"missing": "1"}, "states": data["process"]["states"]}]
        for process in invalid:
            with self.subTest(process=process), self.assertRaises(ValueError):
                parse_source({**data, "process": process})
        for target in ["missing", None, {"left": "1"}]:
            bad = copy.deepcopy(data)
            bad["process"]["states"]["left"]["next"]["A"] = target
            with self.subTest(target=target), self.assertRaises(ValueError):
                parse_source(bad)

    def test_cli_error(self):
        # Ошибочные файлы и аргументы должны давать ненулевой код без traceback
        for args in [("generate", "tests/invalid.json"), ("generate", "missing.json"),
                     ("generate", "examples/source14.json", "--N", "abc"),
                     ("estimate", "examples/source14.json", "--N", "1", "--word", "examples/word.json")]:
            result = subprocess.run([sys.executable, "source.py", *args], cwd=ROOT, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn(b"Traceback", result.stderr)

    @unittest.skipIf(sys.platform == "win32", "Проверка SIGINT для Unix")
    def test_infinite_generation(self):
        # Проверяем бесконечную генерацию при None, нуле и отрицательном N
        for n in ("None", "0", "-1"):
            with self.subTest(N=n):
                process = subprocess.Popen([sys.executable, "source.py", "generate", "tests/constant.json", "--N", n],
                                           cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                # Ждём первый символ, чтобы прервать уже работающую генерацию
                self.assertTrue(process.stdout.readline())
                # SIGINT соответствует нажатию Ctrl+C
                process.send_signal(signal.SIGINT)
                _, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 130)
                self.assertNotIn(b"Traceback", error)

# Запускаем тесты при прямом запуске файла
if __name__ == "__main__":
    unittest.main()
# Конец генерации Codex