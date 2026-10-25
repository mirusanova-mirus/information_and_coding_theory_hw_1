import argparse
import json
import math
import sys
from decimal import Decimal, localcontext
from fractions import Fraction
from pathlib import Path
from time import perf_counter

from source import load_source

def difference(left, right, factor=1):
    # Вычисление разности векторов состояний с заданным множителем
    return {s: left.get(s, 0) - factor * right.get(s, 0) for s in left.keys() | right.keys()}

def zero_continuations(source, pending):
    # Проверка отсутствия различий вероятностей для любых продолжений через базис векторов состояний
    # Входные векторы разностей весов состояний, включая отрицательные координаты
    # Ограничение размера базиса числом состояний вместо перебора бесконечного числа слов
    basis = []
    while pending:
        vector = pending.pop()
        # Исключение уже проверенных базисных направлений методом Гаусса
        for pivot, row in basis:
            vector = difference(vector, row, vector.get(pivot, 0))
        vector = {s: p for s, p in vector.items() if p}
        if not vector:
            continue
        # Сумма координат как разность вероятностей уже прочитанного слова
        if sum(vector.values()):
            return False
        # Нормировка нового базисного вектора по первой ненулевой координате
        pivot = min(vector)
        vector = {s: p / vector[pivot] for s, p in vector.items()}
        basis.append((pivot, vector))
        # Проверка всех следующих символов только для нового независимого направления
        pending.extend(source.step(vector, a) for a in source.alphabet)
    return True

def iid_distribution(source):
    initial = source.initial
    # Проверка стационарности: сравнение начального распределения и его сдвига по вероятностям слов
    shift_difference = difference(source.step(initial), initial)
    if not zero_continuations(source, [shift_difference]):
        raise ValueError("Источник нестационарен")
    probabilities = {a: source.probability([a]) for a in source.alphabet}
    # Проверка независимости будущих символов от первого символа через разность pi*T_a - P(a)*pi
    symbol_differences = [difference(source.step(initial, a), initial, p) for a, p in probabilities.items()]
    if not zero_continuations(source, symbol_differences):
        raise ValueError("Источник имеет память")
    # Исключение символов нулевой вероятности из кодирования
    return {a: p for a, p in probabilities.items() if p}

def decimal(value):
    # Преобразование точной дроби в Decimal с текущей точностью
    return Decimal(value.numerator) / value.denominator

def entropy(probabilities):
    # Точное вычисление энтропии для вероятностей вида 1/2^m
    if all(p.numerator == 1 and p.denominator & (p.denominator - 1) == 0 for p in probabilities):
        return sum((p * (p.denominator.bit_length() - 1) for p in probabilities), Fraction(0))
    # Вычисление суммы -P(a)*log2(P(a)) через логарифмы Decimal
    return -sum(decimal(p) * (Decimal(p.numerator).ln() - Decimal(p.denominator).ln()) for p in probabilities) / Decimal(2).ln()

def eventual(probabilities, rate, epsilon, q):
    # Проверка существования n0 с Pe(n) <= epsilon для всех n >= n0
    h = entropy(probabilities)
    if rate > h:
        return True, "R > H: ошибка стремится к 0"
    if rate < h:
        return False, "R < H: ошибка стремится к 1, хотя при малых n условие может выполняться"
    # Разбор границы R=H для неравномерного источника
    if len(set(probabilities)) > 1:
        return epsilon >= Fraction(1, 2), "R = H: для неравномерного источника ошибка стремится к 1/2 снизу"
    # Определение порога ошибки равномерного источника с учётом округления длины кода
    k = len(probabilities)
    if k == 1:
        threshold = Fraction(0)
    elif k & (k - 1) == 0 and q & (q - 1) == 0:
        # Учёт периода округления через НОД показателей степеней двойки
        a, b = k.bit_length() - 1, q.bit_length() - 1
        threshold = 1 - Fraction(1, 2 ** (b - math.gcd(a, b)))
    else:
        threshold = 1 - Fraction(1, q)
    return epsilon >= threshold, f"R = H: равномерный источник, предельная верхняя грань ошибки {threshold}"

def error_table(probabilities, rate, q, nmax):
    # Приведение вероятностей к целым весам: P[i] = weights[i] / denominator
    denominator = math.lcm(*(p.denominator for p in probabilities))
    weights = [int(p * denominator) for p in probabilities]
    # Предварительное вычисление степеней целых весов
    powers = [[w ** n for n in range(nmax + 1)] for w in weights]
    k, rows = len(weights), []
    uniform = len(set(weights)) == 1
    # Число битов в одном q-ичном разряде, общее для всех длин блока
    power_of_two = q & (q - 1) == 0
    bits_per_digit = q.bit_length() - 1 if power_of_two else Decimal(q).ln() / Decimal(2).ln()

    def types(left, i=0, word_weight=1, type_size=1, counts=()):
        # Перебор типов: вес одного слова, число слов типа и вектор количеств символов
        # Обозначения: left свободных позиций, i номер текущего символа, counts количества предыдущих символов
        if i == k - 1:
            # Заполнение оставшихся позиций последним символом
            yield word_weight * powers[i][left], type_size, counts + (left,)
        else:
            for c in range(left + 1):
                # Выбор c позиций очередного символа из left свободных позиций
                next_weight = word_weight * powers[i][c]
                next_size = type_size * math.comb(left, c)
                yield from types(left - c, i + 1, next_weight, next_size, counts + (c,))

    for n in range(1, nmax + 1):
        # Вычисление floor(n*R/log2(q)) с точным делением при q=2^m
        if power_of_two:
            length = n * rate // bits_per_digit
        else:
            length = int(decimal(n * rate) / bits_per_digit)
        # Ограничение ёмкости числом k^n исходных блоков
        total_blocks = k ** n
        # Предотвращение огромной степени при заведомо достаточной длине, поскольку q >= 2
        capacity = total_blocks if length >= total_blocks.bit_length() else min(q ** length, total_blocks)
        boundary = None
        # Прямой расчёт при полном покрытии или одинаковых вероятностях слов
        if capacity == total_blocks or uniform:
            error = Fraction(total_blocks - capacity, total_blocks)
            order = "lex"
        else:
            remaining, mass = capacity, 0
            # Сортировка типов по вероятности одного слова и накопление массы выбранных слов
            for word_weight, type_size, counts in sorted(types(n), key=lambda t: t[0], reverse=True):
                # Выбор всего типа или его части в пределах оставшейся ёмкости
                used = min(remaining, type_size)
                mass += used * word_weight
                remaining -= used
                if not remaining:
                    # Сохранение описания граничного типа и числа выбранных из него слов
                    boundary = dict(counts=counts, used=used)
                    break
            # Вычисление ошибки как вероятности всех невключённых слов
            error = 1 - Fraction(mass, denominator ** n)
            order = "types"
        rows.append(dict(n=n, length=length, error=error, coded=capacity, order=order, boundary=boundary))
    return rows

# Разбор параметров командной строки для расчёта энтропии и построения кода

# Начало генерации Codex
def parse_args():
    # Задаём режим, описание источника и параметры кодирования
    parser = argparse.ArgumentParser(description="Задача 1.2, вариант 14")
    parser.add_argument("command", choices=("entropy", "code"))
    parser.add_argument("file")
    parser.add_argument("--R")
    parser.add_argument("--epsilon", default="1/10000")
    parser.add_argument("--q", type=int, default=5)
    parser.add_argument("--nmax", type=int, default=50)
    parser.add_argument("--output", default="code14.json")
    parser.add_argument("--variant", action="version", version="s=14, k=3, M=4, L=7, d=3, q=5, epsilon=1/10000")
    return parser.parse_args()
# Конец генерации Codex

# Запуск расчётов, сохранение описания кода, вывод JSON и обработка ошибок

# Начало генерации Codex
def main():
    args = parse_args()
    try:
        sys.set_int_max_str_digits(0)
        started = perf_counter()
        probabilities = iid_distribution(load_source(args.file))
        with localcontext() as context:
            # Вычисляем логарифмы с точностью 80 значащих цифр
            context.prec = 80
            h = entropy(probabilities.values())
            output = dict(H=f"{float(h):.12f}", probabilities=probabilities)
            if args.command == "code":
                # Проверяем наличие скорости и допустимые значения параметров кодирования
                if args.R is None:
                    raise ValueError("Для code нужен --R")
                rate, epsilon = Fraction(args.R), Fraction(args.epsilon)
                if rate < 0 or not 0 < epsilon < 1 or args.q < 2 or args.nmax < 1:
                    raise ValueError("Нужны R >= 0, 0 < epsilon < 1, q >= 2 и nmax >= 1")
                rows = error_table(probabilities.values(), rate, args.q, args.nmax)
                exists, reason = eventual(probabilities.values(), rate, epsilon, args.q)
                # Собираем компактное описание кода без перечисления всех кодируемых слов
                document = dict(format="type-code-v1", alphabet=list(probabilities), probabilities=probabilities, R=rate, epsilon=epsilon, q=args.q, table=rows)
                # Не разрешаем записывать результат поверх исходного файла
                if Path(args.output).resolve() == Path(args.file).resolve():
                    raise ValueError("Файл кода должен отличаться от входного файла")
                Path(args.output).write_text(json.dumps(document, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
                # Находим первое n с ошибкой не больше epsilon и готовим таблицу для вывода
                minimum_n = next((row["n"] for row in rows if row["error"] <= epsilon), None)
                table = [{key: row[key] for key in ("n", "length", "error")} for row in rows]
                output.update(table=table, minimum_n=minimum_n, eventual=exists, reason=reason, code=args.output, seconds=round(perf_counter() - started, 6))
                if minimum_n is None:
                    output["minimum_message"] = f"На отрезке 1..{args.nmax} подходящего n нет"
            print(json.dumps(output, ensure_ascii=False, default=str, indent=2))
    except KeyboardInterrupt:
        print("Остановлено пользователем (Ctrl+C)", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    return 0

# Запускаем программу при прямом запуске файла
if __name__ == "__main__":
    raise SystemExit(main())
# Конец генерации Codex
