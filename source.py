import argparse
import json
import math
import random
import sys
from collections import defaultdict, deque
from fractions import Fraction
from itertools import islice

def mapping(data, name):
    # Проверка непустого словаря и непустых строковых имён
    if not isinstance(data, dict) or not data or any(not isinstance(k, str) or not k for k in data):
        raise ValueError(f"{name}: нужен непустой объект с непустыми именами")
    return data

def parse_distribution(data, name, allowed=None):
    mapping(data, name)
    # Проверка строкового представления вероятностей
    if any(not isinstance(p, str) for p in data.values()):
        raise ValueError(f"{name}: вероятности должны быть строками")
    try:
        # Рационализация строк: разбор дробей и десятичной записи
        result = {key: Fraction(value) for key, value in data.items()}
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{name}: некорректная вероятность") from None
    # Проверка неотрицательности и точной нормировки распределения
    if min(result.values()) < 0 or sum(result.values()) != 1:
        raise ValueError(f"{name}: нужны неотрицательные вероятности с суммой 1")
    # Проверка на неизвестные элементы
    if allowed is not None and result.keys() - allowed.keys():
        raise ValueError(f"{name}: неизвестные имена {sorted(result.keys() - allowed.keys())}")
    return result

def sampling_table(probabilities):
    # Однократное приведение вероятностей к целым весам в фиксированном порядке
    denominator = math.lcm(*(p.denominator for p in probabilities.values()))
    return denominator, [(value, int(p * denominator)) for value, p in sorted(probabilities.items())]

def draw(table, rng):
    denominator, outcomes = table
    # Равномерный выбор целого числа от 0 до denominator-1
    number = rng.randrange(denominator)
    for value, weight in outcomes:
        # Поиск интервала исхода последовательным вычитанием его целого веса
        number -= weight
        if number < 0:
            return value

class Source:
    def __init__(self, models, switches, sequence, initial, states):
        self.models, self.source, self.initial = models, sequence, initial
        # Объединение символов всех моделей в общий алфавит
        self.alphabet = sorted(set().union(*models.values()))
        # Построение совместных переходов: (модель, символ, следующее состояние) -> вероятность
        # Вычисление веса как P(модель)*P(символ|модель) с исключением нулевых переходов
        self.edges = {}
        for name, state in states.items():
            self.edges[name] = {}
            for model, weight in switches[state["switch"]].items():
                for symbol, probability in models[model].items():
                    if weight and probability:
                        self.edges[name][model, symbol, state["next"][symbol]] = weight * probability

    # Генерация символов источника с воспроизводимой случайностью
    def generate(self, seed=14):
        rng = random.Random(seed)
        # Подготовка таблиц один раз на реализацию, без пересчёта при каждом символе
        tables = {state: sampling_table(edges) for state, edges in self.edges.items()}
        # Однократный выбор начального состояния
        state = draw(sampling_table(self.initial), rng)
        while True:
            # Выбор перехода по его вероятности и выдача символа
            _, symbol, state = draw(tables[state], rng)
            yield symbol

    def step(self, distribution, symbol=None):
        # Получение весов состояний после одного шага
        result = defaultdict(Fraction)
        # Перебор возможных текущих состояний
        for state, weight in distribution.items():
            for (_, a, target), p in self.edges[state].items():
                # Отбор переходов с заданным символом или всех переходов при symbol=None
                if symbol is None or a == symbol:
                    # Накопление вкладов разных переходов в одно и то же состояние
                    result[target] += weight * p
        # Сохранение ненормированных весов для последующего вычисления вероятности всего блока
        return dict(result)

    def probability(self, word, initial=None):
        # Вычисление точной вероятности блока последовательным учётом его символов
        distribution = self.initial if initial is None else initial
        for symbol in word:
            distribution = self.step(distribution, symbol)
        # Суммирование весов всех возможных конечных состояний
        return sum(distribution.values(), Fraction(0))

    def exact_probabilities(self, word):
        # Вычисление вероятности первого блока и среднего первых L стартовых позиций
        distribution, values = self.initial, []
        for _ in self.source:
            # Вычисление вероятности блока при текущем распределении состояний источника
            values.append(self.probability(word, distribution))
            # Переход к распределению состояний в следующий момент времени
            distribution = self.step(distribution)
        return values[0], sum(values) / len(values)

# Разбор JSON-конфигурации источника: проверка моделей, переключателей и последовательности переключений
# Поддержка циклического источника без process и расширенного источника с состояниями

# Начало генерации Codex
def parse_source(data):
    required = {"models", "switches", "source"}
    # Проверяем обязательные поля и отклоняем неизвестные
    if not isinstance(data, dict) or not required <= data.keys() <= required | {"process"}:
        raise ValueError("Нужны models, switches, source; дополнительно разрешено process")
    # Читаем распределения и проверяем ссылки переключателей на модели
    models = {m: parse_distribution(p, m) for m, p in mapping(data["models"], "models").items()}
    switches = {s: parse_distribution(p, s, models) for s, p in mapping(data["switches"], "switches").items()}
    sequence = data["source"]
    # Проверяем, что source содержит непустой список известных переключателей
    if (not isinstance(sequence, list) or not sequence or any(not isinstance(s, str) or s not in switches for s in sequence)):
        raise ValueError("source пуст или содержит неизвестный переключатель")
    alphabet = set().union(*models.values())
    if "process" not in data:
        # Без process представляем период как цикл состояний 0,...,L-1
        initial = {"0": Fraction(1)}
        # После каждого символа переходим к следующей позиции, замыкая цикл
        states = {str(i): {"switch": s, "next": {a: str((i + 1) % len(sequence)) for a in alphabet}} for i, s in enumerate(sequence)}
    else:
        # В расширенном формате читаем начальное распределение и описания состояний
        process = data["process"]
        if not isinstance(process, dict) or set(process) != {"initial", "states"}:
            raise ValueError("process должен содержать initial и states")
        states = mapping(process["states"], "states")
        initial = parse_distribution(process["initial"], "initial", states)
        # Проверяем структуру состояний, ссылки на переключатели и переходы для каждого символа
        for name, state in states.items():
            if not isinstance(state, dict) or set(state) != {"switch", "next"}:
                raise ValueError(f"{name}: нужны switch и next")
            if not isinstance(state["switch"], str) or state["switch"] not in switches:
                raise ValueError(f"{name}: неизвестный переключатель")
            if not isinstance(state["next"], dict) or set(state["next"]) != alphabet:
                raise ValueError(f"{name}: next должен содержать все символы алфавита")
            if any(not isinstance(t, str) or t not in states for t in state["next"].values()):
                raise ValueError(f"{name}: неизвестное следующее состояние")
    return Source(models, switches, sequence, initial, states)
# Конец генерации Codex

def load_source(path):
    # Загрузка и проверка конфигурации источника из JSON
    with open(path, encoding="utf-8") as file:
        return parse_source(json.load(file))

def estimate(source, word, n, seed=14):
    # Проверка корректности блока и требуемой длины выборки
    if not isinstance(word, list) or not word or any(not isinstance(a, str) for a in word):
        raise ValueError("Блок должен быть непустым JSON-массивом строк")
    if n < len(word):
        raise ValueError("Нужно N >= длины блока > 0")

    # Теоретические вероятности для сравнения с экспериментом
    first, average = source.exact_probabilities(word)
    # Выбор контрольных длин, включая N из параметров запуска
    sizes = {n, 100, 1000, 10000, 100000, 1000000}

    # Создание окна длины блока с автоматическим удалением старейших символов
    window, target = deque(maxlen=len(word)), deque(word)
    hits, rows = 0, {}

    # Обработка одной реализации до максимальной контрольной длины
    for i, symbol in enumerate(islice(source.generate(seed), max(sizes)), 1):
        window.append(symbol)
        # Подсчёт совпадений с блоком, включая перекрывающиеся вхождения
        hits += window == target
        if i in sizes:
            # Подсчёт числа возможных стартовых позиций: N-r+1
            denominator = i - len(word) + 1
            # Сохранение частоты или None при отсутствии полного окна
            rows[i] = (hits, Fraction(hits, denominator) if denominator > 0 else None)
    return first, average, rows

# Интерфейс командной строки для генерации последовательности и оценки частоты появления заданного блока
# Обработка параметров запуска, вывод результатов в JSON и диагностика ошибок

# Начало генерации Codex
def main() -> int:
    # Разрешаем вывод больших целых чисел, которые появляются в точных дробях
    sys.set_int_max_str_digits(0)
    parser = argparse.ArgumentParser(description="Теория информации. Вариант 14")
    parser.add_argument("command", choices=("generate", "estimate"))
    parser.add_argument("file", help="описание источника в JSON")
    parser.add_argument("--N", type=lambda s: None if s == "None" else int(s))
    parser.add_argument("--seed", type=int, default=14)
    parser.add_argument("--word", help="JSON-файл с массивом символов")
    parser.add_argument("--variant", action="version", version="s=14, k=3, M=4, L=7, d=3, q=5, epsilon=1/10000")
    args = parser.parse_args()
    if args.command == "estimate" and (args.N is None or args.word is None):
        parser.error("для estimate нужны --N и --word")

    try:
        source = load_source(args.file)
        if args.command == "generate":
            # Выдаём N символов, а при N <= 0 или None продолжаем до Ctrl+C
            for symbol in islice(source.generate(args.seed), args.N if args.N is not None and args.N > 0 else None):
                print(json.dumps(symbol, ensure_ascii=False), flush=True)
        else:
            # Читаем блок символов из JSON-файла
            with open(args.word, encoding="utf-8") as file:
                word = json.load(file)
            first, average, rows = estimate(source, word, args.N, args.seed)
            # Собираем частоты и отклонения в таблицу, точные дроби выводим строками
            table = []
            for n, (_, frequency) in rows.items():
                error_first = None if frequency is None else abs(frequency - first)
                error_average = None if frequency is None else abs(frequency - average)
                table.append(dict(N=n, frequency=frequency, error_first=error_first, error_average=error_average))
            output = dict(first=first, average=average, N=args.N, frequency=rows[args.N][1], table=table)
            print(json.dumps(output, default=str, indent=2))
    except KeyboardInterrupt:
        print("Остановлено пользователем (Ctrl+C)", file=sys.stderr)
        return 130
    except Exception as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
# Конец генерации Codex
