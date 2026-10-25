import argparse
import heapq
import json
import math
import sys
import zlib
from collections import Counter
from contextlib import contextmanager
from pathlib import Path
from struct import Struct

MAGIC = b"ZMH1"
# Поля заголовка: сигнатура, исходная длина, число битов, CRC32, число символов
HEADER = Struct(">4sQQIH")
CHUNK = 65536

@contextmanager
def new_file(path):
    # Создание нового файла и удаление неполного результата при ошибке
    with Path(path).open("xb") as file:
        try:
            # Передача открытого файла блоку with и возврат сюда после его выполнения
            yield file
        except BaseException:
            file.close()
            Path(path).unlink()
            raise

def code_lengths(counts):
    # Построение дерева объединением двух наименьших весов
    # Элемент кучи: (вес, номер для разрешения равенств, байт или пара дочерних узлов)
    heap = [(count, symbol, symbol) for symbol, count in counts.items()]
    heapq.heapify(heap)
    serial = 256
    while len(heap) > 1:
        left_weight, _, left_node = heapq.heappop(heap)
        right_weight, _, right_node = heapq.heappop(heap)
        # Разрешение равных весов по номеру узла для воспроизводимости
        heapq.heappush(heap, (left_weight + right_weight, serial, (left_node, right_node)))
        serial += 1
    lengths = {}
    pending = [(heap[0][2], 0)] if heap else []
    while pending:
        node, depth = pending.pop()
        if isinstance(node, int):
            lengths[node] = depth
        else:
            pending.extend((child, depth + 1) for child in node)
    return lengths

def canonical_codes(lengths):
    # Восстановление кодов по длинам с упорядочением по длине и значению байта
    invalid_single = len(lengths) == 1 and set(lengths.values()) != {0}
    invalid_multiple = len(lengths) > 1 and 0 in lengths.values()
    if invalid_single or invalid_multiple:
        raise ValueError("Повреждённый файл: неверные длины кодов")
    codes, next_code, previous_length = {}, 0, 0
    for symbol, length in sorted(lengths.items(), key=lambda item: (item[1], item[0])):
        # Сдвиг следующего кода влево при увеличении длины, например 10 -> 100
        next_code <<= length - previous_length
        if next_code >= 1 << length:
            raise ValueError("Повреждённый файл: коды пересекаются")
        codes[symbol] = (next_code, length)
        next_code, previous_length = next_code + 1, length
    # Проверка полноты двоичного дерева, полученного методом Хаффмана
    if len(lengths) > 1 and next_code != 1 << previous_length:
        raise ValueError("Повреждённый файл: неполная модель")
    return codes

def compress(source, destination):
    counts, size, checksum = Counter(), 0, 0
    with Path(source).open("rb") as file:
        # Первый проход: подсчёт байтов, длины файла и контрольной суммы
        for block in iter(lambda: file.read(CHUNK), b""):
            counts.update(block)
            size += len(block)
            checksum = zlib.crc32(block, checksum)
        lengths = code_lengths(counts)
        codes = canonical_codes(lengths)
        bit_count = sum(count * lengths[symbol] for symbol, count in counts.items())
        model = b"".join(bytes((symbol, length)) for symbol, length in sorted(lengths.items()))
        file.seek(0)
        with new_file(destination) as output:
            output.write(HEADER.pack(MAGIC, size, bit_count, checksum, len(lengths)) + model)
            buffer, bits, payload = 0, 0, bytearray()
            second_size, second_checksum = 0, 0
            # Второй проход: упаковка кодовых слов в байты, начиная со старших битов
            for block in iter(lambda: file.read(CHUNK), b""):
                second_size += len(block)
                second_checksum = zlib.crc32(block, second_checksum)
                for symbol in block:
                    code, length = codes[symbol]
                    buffer = (buffer << length) | code
                    bits += length
                    while bits >= 8:
                        # Выдача старшего полного байта и сохранение оставшихся младших битов
                        bits -= 8
                        payload.append(buffer >> bits)
                        buffer &= (1 << bits) - 1
                # Запись полных байтов после обработки очередной порции исходного файла
                output.write(payload)
                payload.clear()
            # Заполнение младших разрядов последнего байта нулями
            if bits:
                payload.append(buffer << (8 - bits))
            output.write(payload)
            if (second_size, second_checksum) != (size, checksum):
                raise ValueError("Исходный файл изменился между проходами")
    header_bytes = HEADER.size + len(model)
    archive_bytes = Path(destination).stat().st_size
    h = sum(count / size * math.log2(size / count) for count in counts.values()) if size else 0
    return dict(H=round(h, 9), average_length=round(bit_count / size, 9) if size else 0,
                header_bytes=header_bytes, data_bytes=archive_bytes - header_bytes,
                input_bytes=size, archive_bytes=archive_bytes, ratio=round(size / archive_bytes, 9))

def read_exact(file, size):
    # Проверка наличия всех объявленных байтов заголовка и данных
    data = file.read(size)
    if len(data) != size:
        raise ValueError("Обрезанный файл: недостаточно байтов")
    return data

def decoded_blocks(file, codes, bit_count, size):
    # Восстановление повторений единственного символа по исходной длине
    if len(codes) == 1:
        symbol = bytes([next(iter(codes))])
        while size:
            count = min(size, CHUNK)
            yield symbol * count
            size -= count
        return
    # Поиск символа по накопленному коду и числу прочитанных битов
    decoder = {(code, length): symbol for symbol, (code, length) in codes.items()}
    prefix, length, payload = 0, 0, bytearray()
    while bit_count:
        block = read_exact(file, min(CHUNK, (bit_count + 7) // 8))
        for byte in block:
            take = min(8, bit_count)
            if take < 8 and byte & ((1 << (8 - take)) - 1):
                raise ValueError("Повреждённый файл: ненулевые биты заполнения")
            for shift in range(7, 7 - take, -1):
                # Добавление очередного бита справа к ещё не распознанному коду
                prefix = (prefix << 1) | ((byte >> shift) & 1)
                length += 1
                symbol = decoder.get((prefix, length))
                if symbol is not None:
                    payload.append(symbol)
                    prefix, length = 0, 0
                    if len(payload) >= CHUNK:
                        yield bytes(payload)
                        payload.clear()
            bit_count -= take
    if length:
        raise ValueError("Повреждённый файл: незавершённое кодовое слово")
    if payload:
        yield bytes(payload)

def decompress(source, destination):
    with Path(source).open("rb") as file:
        signature = file.read(len(MAGIC))
        if signature != MAGIC:
            if MAGIC.startswith(signature):
                raise ValueError("Обрезанный файл: неполная сигнатура")
            raise ValueError("Чужой формат: нет сигнатуры ZMH1")
        _, size, bit_count, checksum, count = HEADER.unpack(signature + read_exact(file, HEADER.size - len(MAGIC)))
        if count > 256:
            raise ValueError("Повреждённый файл: слишком много символов")
        model = read_exact(file, 2 * count)
        lengths = dict(zip(model[::2], model[1::2]))
        # Согласование модели с исходной длиной, включая пустой файл
        if len(lengths) != count or bool(size) != bool(count):
            raise ValueError("Повреждённый файл: неверная модель")
        codes = canonical_codes(lengths)
        minimum = size * min(lengths.values(), default=0)
        maximum = size * max(lengths.values(), default=0)
        if not minimum <= bit_count <= maximum:
            raise ValueError("Повреждённый файл: неверное число битов")
        expected = HEADER.size + len(model) + (bit_count + 7) // 8
        actual = file.seek(0, 2)
        if actual < expected:
            raise ValueError("Обрезанный файл: недостаточно данных")
        if actual > expected:
            raise ValueError("Повреждённый файл: лишние данные")
        file.seek(HEADER.size + len(model))
        restored, actual_checksum = 0, 0
        with new_file(destination) as output:
            for block in decoded_blocks(file, codes, bit_count, size):
                restored += len(block)
                if restored > size:
                    raise ValueError("Повреждённый файл: превышена исходная длина")
                actual_checksum = zlib.crc32(block, actual_checksum)
                output.write(block)
            # Проверка длины и контрольной суммы восстановленных данных
            if restored != size or actual_checksum != checksum:
                raise ValueError("Повреждённый файл: не совпали длина или CRC32")

# Запуск архиватора через командную строку
# main читает параметры, выбирает путь результата и вызывает compress или decompress
# Затем выводит путь файла, запрошенную статистику или сообщение об ошибке

# Начало генерации Codex
def main():
    # Читаем режим работы, входной файл и необязательные параметры
    parser = argparse.ArgumentParser(description="Задача 1.3, вариант 14")
    parser.add_argument("command", choices=("compress", "decompress"))
    parser.add_argument("file")
    parser.add_argument("--output")
    parser.add_argument("--stats", action="store_true")
    parser.add_argument("--variant", action="version", version="s=14, k=3, M=4, L=7, d=3, q=5, epsilon=1/10000")
    args = parser.parse_args()
    try:
        source = Path(args.file)
        # Проверяем, что статистика запрошена для режима сжатия
        if args.stats and args.command != "compress":
            raise ValueError("Ключ --stats используется при сжатии")
        # Выбираем заданный путь результата или формируем имя по выбранному режиму
        if args.output:
            destination = Path(args.output)
        elif args.command == "compress":
            destination = Path(str(source) + ".zmh")
        else:
            destination = source.with_suffix("")
        # Не разрешаем записывать результат поверх входного файла
        if source.resolve() == destination.resolve():
            raise ValueError("Входной и выходной файлы должны различаться")
        result = dict(output=str(destination))
        if args.command == "compress":
            # Сжимаем файл и при --stats добавляем показатели сжатия к результату
            stats = compress(source, destination)
            if args.stats:
                result.update(stats)
        else:
            # Восстанавливаем исходные байты и проверяем целостность файла
            decompress(source, destination)
        # Выводим путь результата и запрошенную статистику в JSON
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except KeyboardInterrupt:
        # Обрабатываем остановку пользователем через Ctrl+C
        print("Остановлено пользователем (Ctrl+C)", file=sys.stderr)
        return 130
    except Exception as error:
        # Выводим сообщение об ошибке и возвращаем ненулевой код завершения
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    return 0

# Запускаем программу при прямом запуске файла
if __name__ == "__main__":
    raise SystemExit(main())
# Конец генерации Codex
