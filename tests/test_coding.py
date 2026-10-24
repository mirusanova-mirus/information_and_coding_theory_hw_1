# Модульные и интеграционные тесты равномерного кодирования источника без памяти

# Начало генерации Codex
import json
import math
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from decimal import localcontext
from fractions import Fraction as F
from itertools import product
from pathlib import Path

from coding import entropy, error_table, eventual, iid_distribution
from source import load_source, parse_source

ROOT = Path(__file__).resolve().parents[1]


class CodingTests(unittest.TestCase):
    def test_source_conditions(self):
        # Проверяем распределение и энтропию стационарного источника без памяти
        p = iid_distribution(load_source(ROOT / "examples/iid14.json"))
        self.assertEqual(list(p.values()), [F(1, 2), F(1, 3), F(1, 6)])
        self.assertAlmostEqual(float(entropy(list(p.values()))), 1.459147917027, places=11)
        # Источники с нестационарностью или памятью должны быть отклонены
        for name, error in [("source14", "нестационарен"), ("markov14", "память"), ("nonergodic14", "память")]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, error):
                iid_distribution(load_source(ROOT / f"examples/{name}.json"))

    def test_hidden_states_can_still_give_iid(self):
        # Проверяем, что скрытые состояния сами по себе не означают память у выходных символов
        data = json.loads((ROOT / "examples/nonergodic14.json").read_text())
        data["models"]["model_2"] = {"A": "1/3", "B": "1/3", "C": "1/3"}
        data["switches"]["reset"] = {"model_2": "1"}
        data["process"]["states"]["reset"] = {"switch": "reset", "next": {a: "reset" for a in "ABC"}}
        # После первого символа все состояния переходят к равномерной модели
        for state in data["process"]["states"].values():
            state["next"] = {a: "reset" for a in "ABC"}
        # Начальная смесь тоже равномерна, поэтому вся последовательность должна быть iid
        self.assertEqual(set(iid_distribution(parse_source(data)).values()), {F(1, 3)})

    def test_optimal_error_against_enumeration(self):
        # Сверяем метод типов с полным перебором всех слов при n <= 5
        with localcontext() as context:
            context.prec = 80
            for p in ([F(1, 2), F(1, 3), F(1, 6)], [F(1, 2), F(1, 4), F(1, 4)], [F(1, 3)] * 3):
                for q in (2, 3, 5):
                    for rate in (F(0), F(3, 2), F(2)):
                        for row in error_table(p, rate, q, 5):
                            n = row["n"]
                            # Полный перебор служит независимой проверкой вероятностей
                            masses = sorted((math.prod(word) for word in product(p, repeat=n)), reverse=True)
                            # Всё, что не входит в первые q^length слов, даёт ошибку декодирования
                            expected = 1 - sum(masses[:q ** row["length"]])
                            self.assertEqual(row["error"], expected, (p, q, rate, n))
                            self.assertEqual(row["length"], math.floor(n * float(rate) / math.log2(q)))

    def test_asymptotics_and_small_n(self):
        # Проверяем ответы для R ниже, выше и на границе энтропии H=3/2
        p = [F(1, 2), F(1, 4), F(1, 4)]
        self.assertFalse(eventual(p, F(1), F(1, 10000), 5)[0])  # R < H
        self.assertTrue(eventual(p, F(2), F(1, 10000), 5)[0])  # R > H
        self.assertFalse(eventual(p, F(3, 2), F(1, 10000), 5)[0])  # R = H, epsilon < 1/2
        self.assertTrue(eventual(p, F(3, 2), F(1, 2), 5)[0])  # R = H, epsilon = 1/2
        # При равномерном источнике на границе R=H учитывается округление длины
        uniform = [F(1, 2)] * 2
        self.assertTrue(eventual(uniform, F(1), F(1, 10000), 2)[0])
        # Для q=4 порог epsilon равен 1/2, для q=5 равен 4/5
        self.assertFalse(eventual(uniform, F(1), F(49, 100), 4)[0])
        self.assertTrue(eventual(uniform, F(1), F(1, 2), 4)[0])
        self.assertFalse(eventual(uniform, F(1), F(1, 2), 5)[0])
        self.assertTrue(eventual(uniform, F(1), F(4, 5), 5)[0])
        # При R < H малое n может подходить, а следующее уже нет
        rows = error_table([F(9999, 10000), F(1, 10000)], F(0), 5, 2)
        self.assertEqual(rows[0]["error"], F(1, 10000))
        self.assertGreater(rows[1]["error"], F(1, 10000))

    def test_saved_code(self):
        # Запускаем кодирование и проверяем сохранённое описание кода во временной папке
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "code.json"
            result = subprocess.run([sys.executable, "coding.py", "code", "examples/iid14.json", "--R", "1.6",
                                     "--nmax", "4", "--output", str(path)], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            output, code = json.loads(result.stdout), json.loads(path.read_text())
            # На отрезке n <= 4 граница ещё не достигнута, но для больших n достижима
            self.assertIsNone(output["minimum_n"])
            self.assertIn("подходящего n нет", output["minimum_message"])
            self.assertTrue(output["eventual"])
            p, alphabet = code["probabilities"], code["alphabet"]
            # Восстанавливаем порядок и состав выбранных слов по описанию из JSON
            for row in code["table"]:
                words = list(product(alphabet, repeat=row["n"]))
                def key(word):
                    # Минус перед вероятностью задаёт сортировку по убыванию
                    counts = tuple(Counter(word)[a] for a in alphabet)
                    return -math.prod(F(p[a]) for a in word), counts, word
                words.sort(key=key if row["order"] == "types" else None)
                selected = words[:row["coded"]]
                self.assertLessEqual(len(selected), code["q"] ** row["length"])
                self.assertEqual(1 - sum(math.prod(F(p[a]) for a in word) for word in selected), F(row["error"]))
                # Проверяем граничный тип и число выбранных слов из него
                if row["boundary"]:
                    counts = row["boundary"]["counts"]
                    self.assertEqual([Counter(selected[-1])[a] for a in alphabet], counts)
                    self.assertEqual(sum([Counter(word)[a] for a in alphabet] == counts for word in selected),
                                     row["boundary"]["used"])

    def test_invalid_cli(self):
        # Неверные входы и параметры должны давать ненулевой код без traceback
        cases = [("entropy", "tests/invalid.json"), ("entropy", "missing.json"),
                 ("code", "examples/iid14.json"),
                 ("code", "examples/iid14.json", "--R", "1/0"),
                 ("code", "examples/iid14.json", "--R", "-1"),
                 ("code", "examples/iid14.json", "--R", "1", "--q", "1"),
                 ("code", "examples/iid14.json", "--R", "1", "--epsilon", "2"),
                 ("code", "examples/iid14.json", "--R", "1", "--nmax", "0"),
                 ("code", "examples/iid14.json", "--R", "1", "--output", "examples/iid14.json")]
        for args in cases:
            with self.subTest(args=args):
                result = subprocess.run([sys.executable, "coding.py", *args], cwd=ROOT, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"Traceback", result.stderr)

    def test_degenerate_source(self):
        # У источника из одного символа энтропия и ошибка равны нулю даже при R=0
        p = iid_distribution(load_source(ROOT / "tests/constant.json"))
        self.assertEqual(p, {"A": F(1)})
        self.assertEqual(entropy(list(p.values())), 0)
        self.assertTrue(all(row["error"] == 0 for row in error_table(list(p.values()), F(0), 5, 50)))
        self.assertTrue(eventual(list(p.values()), F(0), F(1, 10000), 5)[0])


# Запускаем тесты при прямом запуске файла
if __name__ == "__main__":
    unittest.main()
# Конец генерации Codex
