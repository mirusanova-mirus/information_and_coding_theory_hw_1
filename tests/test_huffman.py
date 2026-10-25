# Модульные и интеграционные тесты сжатия и восстановления файлов методом Хаффмана

# Начало генерации Codex
import json
import math
import random
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from huffman import CHUNK, HEADER, MAGIC, canonical_codes, code_lengths, compress, decompress

ROOT = Path(__file__).resolve().parents[1]

class HuffmanTests(unittest.TestCase):
    def setUp(self):
        # Для каждого теста создаём временную папку и удаляем её после завершения
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.folder = Path(self.directory.name)
        self.source = self.folder / "input.bin"
        self.archive = self.folder / "input.bin.zmh"
        self.restored = self.folder / "output.bin"

    def test_known_codes(self):
        # Сверяем длины кодов и общее число битов с ручным расчётом для весов 45,13,12,16,9,5
        counts = dict(zip(b"ABCDEF", (45, 13, 12, 16, 9, 5)))
        lengths = code_lengths(counts)
        self.assertEqual(lengths, dict(zip(b"ABCDEF", (1, 3, 3, 3, 4, 4))))
        self.assertEqual(sum(counts[a] * length for a, length in lengths.items()), 224)
        codes = canonical_codes(lengths)
        words = [format(code, f"0{length}b") for code, length in codes.values()]
        # Проверяем, что ни одно кодовое слово не является началом другого
        self.assertFalse(any(right.startswith(left) for left in words for right in words if left != right))
        # Проверяем воспроизводимость дерева и длину 8 при равных частотах всех 256 байтов
        self.assertEqual(code_lengths(dict(reversed(list(counts.items())))), lengths)
        self.assertEqual(set(code_lengths(dict.fromkeys(range(256), 1)).values()), {8})

    def test_round_trip(self):
        # Проверяем восстановление пустого файла, одного байта, всех байтов и данных длиннее одной порции
        rng = random.Random(14)
        cases = [b"", b"\0", b"\xff" * (CHUNK + 17), bytes(range(256)) * 300, rng.randbytes(CHUNK + 101), "Теория информации\n".encode()]
        for data in cases:
            with self.subTest(size=len(data)):
                self.source.write_bytes(data)
                stats = compress(self.source, self.archive)
                decompress(self.archive, self.restored)
                self.assertEqual(self.restored.read_bytes(), data)
                self.assertEqual(stats["input_bytes"], len(data))
                self.assertEqual(stats["archive_bytes"], self.archive.stat().st_size)
                self.assertEqual(stats["header_bytes"], 26 + 2 * len(set(data)))
                self.assertEqual(stats["archive_bytes"], stats["header_bytes"] + stats["data_bytes"])
                # Учитываем округление статистики при проверке H <= средней длины < H+1
                self.assertLessEqual(stats["H"], stats["average_length"] + 1e-8)
                self.assertLess(stats["average_length"], stats["H"] + 1 + 1e-8)
                self.archive.unlink()
                self.restored.unlink()

    def test_required_examples(self):
        # Проверяем наличие пяти типов файлов из отчёта и их побайтовое восстановление
        for name in ("russian.txt", "english.txt", "image.png", "repeat.bin", "empty.bin"):
            with self.subTest(file=name):
                path = ROOT / "examples/files" / name
                self.assertTrue(path.is_file())
                compress(path, self.archive)
                decompress(self.archive, self.restored)
                self.assertEqual(self.restored.read_bytes(), path.read_bytes())
                self.archive.unlink()
                self.restored.unlink()

    def test_empty_and_single_byte(self):
        # Проверяем, что пустой файл и повторяющийся байт не требуют потока кодов
        for data in (b"", b"A" * 4096):
            with self.subTest(size=len(data)):
                self.source.write_bytes(data)
                stats = compress(self.source, self.archive)
                self.assertEqual(stats["H"], 0)
                self.assertEqual(stats["average_length"], 0)
                self.assertEqual(stats["data_bytes"], 0)
                self.archive.unlink()

    def test_padding_and_determinism(self):
        # Сверяем упаковку ABA с ручным расчётом: коды 0,1,0 и пять нулей заполнения
        self.source.write_bytes(b"ABA")
        compress(self.source, self.archive)
        data = self.archive.read_bytes()
        self.assertEqual(len(data), 31)
        self.assertEqual(data[-1], 0b01000000)
        other = self.folder / "other.zmh"
        compress(self.source, other)
        self.assertEqual(other.read_bytes(), data)
        # Меняем бит заполнения и проверяем отказ с удалением неполного результата
        self.archive.write_bytes(data[:-1] + bytes([data[-1] | 1]))
        with self.assertRaisesRegex(ValueError, "Повреждённый.*заполнения"):
            decompress(self.archive, self.restored)
        self.assertFalse(self.restored.exists())

    def test_truncated_and_foreign_files(self):
        # Проверяем отдельные сообщения для чужого формата и обрыва в каждой позиции архива
        self.archive.write_bytes(b"not a zmh file")
        with self.assertRaisesRegex(ValueError, "Чужой формат"):
            decompress(self.archive, self.restored)
        self.source.write_bytes(b"ABACABAD" * 10)
        self.archive.unlink()
        compress(self.source, self.archive)
        data = self.archive.read_bytes()
        for position in range(len(data)):
            self.archive.write_bytes(data[:position])
            with self.subTest(position=position), self.assertRaisesRegex(ValueError, "Обрезанный файл"):
                decompress(self.archive, self.restored)
            self.assertFalse(self.restored.exists())

    def test_corruption(self):
        # Проверяем обнаружение изменённой контрольной суммы, битов данных и лишнего байта
        self.source.write_bytes(b"ABACABAD" * 100)
        compress(self.source, self.archive)
        original = self.archive.read_bytes()
        # Меняем бит в поле CRC32, затем в предпоследнем байте потока кодов
        for position in (20, len(original) - 2):
            damaged = bytearray(original)
            damaged[position] ^= 0x80
            self.archive.write_bytes(damaged)
            with self.subTest(position=position), self.assertRaisesRegex(ValueError, "Повреждённый файл"):
                decompress(self.archive, self.restored)
            self.assertFalse(self.restored.exists())
        self.archive.write_bytes(original + b"\0")
        with self.assertRaisesRegex(ValueError, "Повреждённый.*лишние"):
            decompress(self.archive, self.restored)

    def test_invalid_model(self):
        # Передаём модели с повторяющимися символами, пересечением кодов и неполным деревом
        models = [bytes((65, 1, 65, 1)), bytes((65, 1, 66, 1, 67, 1)), bytes((65, 2, 66, 2, 67, 2)), bytes((65, 0, 66, 1))]
        for model in models:
            self.archive.write_bytes(HEADER.pack(MAGIC, 3, 3, 0, len(model) // 2) + model + b"\0")
            with self.subTest(model=model), self.assertRaisesRegex(ValueError, "Повреждённый файл"):
                decompress(self.archive, self.restored)
        # Проверяем несовместимые поля заголовка и число символов больше 256
        for size, bits, checksum, count in ((0, 1, 0, 0), (0, 0, 1, 0), (1, 0, 0, 0), (1, 1, 0, 257)):
            self.archive.write_bytes(HEADER.pack(MAGIC, size, bits, checksum, count))
            with self.subTest(size=size, bits=bits, count=count), self.assertRaisesRegex(ValueError, "Повреждённый файл"):
                decompress(self.archive, self.restored)
            self.assertFalse(self.restored.exists())

    def test_existing_files(self):
        # Проверяем, что совпадающий или занятый путь результата не приводит к перезаписи файла
        self.source.write_bytes(b"original")
        with self.assertRaises(FileExistsError):
            compress(self.source, self.source)
        self.assertEqual(self.source.read_bytes(), b"original")
        compress(self.source, self.archive)
        self.restored.write_bytes(b"keep")
        with self.assertRaises(FileExistsError):
            decompress(self.archive, self.restored)
        self.assertEqual(self.restored.read_bytes(), b"keep")

    def test_cli_and_stats(self):
        # Сверяем статистику командной строки с независимым расчётом для вероятностей 3/4 и 1/4
        self.source.write_bytes(b"AAAB")
        result = subprocess.run([sys.executable, "huffman.py", "compress", str(self.source), "--stats"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        stats = json.loads(result.stdout)
        expected_h = -sum(p * math.log2(p) for p in (3 / 4, 1 / 4))
        self.assertAlmostEqual(stats["H"], expected_h, places=8)
        self.assertEqual(stats["average_length"], 1)
        self.assertEqual(stats["header_bytes"], 30)
        self.assertEqual(stats["data_bytes"], 1)
        self.assertAlmostEqual(stats["ratio"], 4 / 31, places=8)
        # Запускаем восстановление через командную строку и сравниваем исходные байты
        result = subprocess.run([sys.executable, "huffman.py", "decompress", str(self.archive), "--output", str(self.restored)], cwd=ROOT, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.restored.read_bytes(), b"AAAB")
        # Проверяем вывод номера варианта
        version = subprocess.run([sys.executable, "huffman.py", "--variant"], cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(version.returncode, 0)
        self.assertIn("s=14", version.stdout)

    def test_invalid_cli(self):
        # Проверяем ненулевой код завершения и отсутствие traceback при неверных входах
        self.source.write_bytes(b"A")
        cases = [("compress", str(self.folder / "missing")), ("decompress", str(self.source)), ("compress", str(self.source), "--output", str(self.source)), ("decompress", str(self.source), "--stats")]
        for args in cases:
            result = subprocess.run([sys.executable, "huffman.py", *args], cwd=ROOT, capture_output=True)
            with self.subTest(args=args):
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn(b"Traceback", result.stderr)

# Запускаем тесты при прямом запуске файла
if __name__ == "__main__":
    unittest.main()
# Конец генерации Codex
