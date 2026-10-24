
import argparse
import json
import math
import random
import sys
from collections import defaultdict, deque
from fractions import Fraction
from itertools import islice

def mapping(data, name):
    # Проверка непустоты словаря
    if not isinstance(data, dict) or not data or any(not isinstance(k, str) or not k for k in data):
        raise ValueError(f"{name}: нужен непустой объект с непустыми именами")
    return data

def parse_distribution(data, name, allowed=None):
    mapping(data, name)
    if any(not isinstance(p, str) for p in data.values()):
        raise ValueError(f"{name}: вероятности должны быть строками")
    try:
        # Рационализация строк
        result = {key: Fraction(value) for key, value in data.items()}
    except (ValueError, ZeroDivisionError):
        raise ValueError(f"{name}: некорректная вероятность") from None
    if min(result.values()) < 0 or sum(result.values()) != 1:
        raise ValueError(f"{name}: нужны неотрицательные вероятности с суммой 1")
    # Проверка на неизвестные элементы
    if allowed is not None and result.keys() - allowed.keys():
        raise ValueError(f"{name}: неизвестные имена {sorted(result.keys() - allowed.keys())}")
    return result

def draw(probabilities, rng):
    denominator = math.lcm(*(p.denominator for p in probabilities.values()))
    number = rng.randrange(denominator)
    for value, p in sorted(probabilities.items()):
        number -= p.numerator * (denominator // p.denominator)
        if number < 0:
            return value

class Source:
    def __init__(self, models, switches, sequence, initial, states):
        self.models, self.source, self.initial = models, sequence, initial
        self.alphabet = sorted(set().union(*(set(p) for p in models.values())))
        # Построение вероятностных переходов между состояниями вида: (модель, символ, следующее состояние) -> вероятность
        # Вероятность перехода = произведению вероятности выбора модели и вероятности символа в ней
        self.edges = {
            s: {(m, a, state["next"][a]): weight * p
                for m, weight in switches[state["switch"]].items()
                for a, p in models[m].items() if weight and p}
            for s, state in states.items()
        }

    # Воспроизводимый генератор случайных чисел
    def generate(self, seed=14):
        rng = random.Random(seed)
        state = draw(self.initial, rng)
        while True:
            # Выбор переход по его вероятности и выдача символа
            _, symbol, state = draw(self.edges[state], rng)
            yield symbol

    def step(self, distribution, symbol=None):
        # Получение распределения состояний после одного шага
        result = defaultdict(Fraction)
        # Перебор возможных текущих состояний
        for state, weight in distribution.items():
            for (_, a, target), p in self.edges[state].items():
                # Если symbol задан, учитываются только переходы, порождающие этот символ
                if symbol is None or a == symbol:
                    result[target] += weight * p
        # При заданном symbol распределение не нормируется: сумма весов равна вероятности наблюдения символа
        return dict(result)

    def probability(self, word, initial=None):
        # Вычисление точной вероятность блока: последовательно учитываем его символы и суммируем вероятности всех конечных состояний
        distribution = self.initial if initial is None else initial
        for symbol in word:
            distribution = self.step(distribution, symbol)
        return sum(distribution.values(), Fraction(0))

    def exact_probabilities(self, word):
        distribution, values = self.initial, []
        for _ in self.source:
            # Вычисление вероятности блока при текущем распределении состояний источника
            values.append(self.probability(word, distribution))
            # Переход к распределению состояний в следующий момент времени
            distribution = self.step(distribution)
        return values[0], sum(values) / len(values)


# Разбор JSON-конфигурации источника: проверка моделей, переключателей и последовательности переключений
# Если process не задан, создаётся циклический процесс, иначе используются заданные начальные состояния и переходы

# Начало генерации Codex
def parse_source(data):
    required = {"models", "switches", "source"}
    if not isinstance(data, dict) or not required <= data.keys() or data.keys() - required - {"process"}:
        raise ValueError("Нужны models, switches, source; дополнительно разрешено process")
    models = {m: parse_distribution(p, m) for m, p in mapping(data["models"], "models").items()}
    switches = {s: parse_distribution(p, s, models) for s, p in mapping(data["switches"], "switches").items()}
    sequence = data["source"]
    if (not isinstance(sequence, list) or not sequence or any(not isinstance(s, str) or s not in switches for s in sequence)):
        raise ValueError("source пуст или содержит неизвестный переключатель")
    alphabet = set().union(*(set(p) for p in models.values()))
    if "process" not in data:
        initial = {"0": Fraction(1)}
        states = {str(i): {"switch": s,
                          "next": {a: str((i + 1) % len(sequence)) for a in alphabet}}
                  for i, s in enumerate(sequence)}
    else:
        process = data["process"]
        if not isinstance(process, dict) or set(process) != {"initial", "states"}:
            raise ValueError("process должен содержать initial и states")
        states = mapping(process["states"], "states")
        initial = parse_distribution(process["initial"], "initial", states)
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
    # Проверка корректность блока и требуемой длины выборки
    if not isinstance(word, list) or not word or any(not isinstance(a, str) for a in word):
        raise ValueError("Блок должен быть непустым JSON-массивом строк")
    if n < len(word):
        raise ValueError("Нужно N >= длины блока > 0")

    # Теоретические вероятности для сравнения с экспериментом
    first, average = source.exact_probabilities(word)
    sizes = {n, 100, 1000, 10000, 100000, 1000000}

    # Скользящее окно для поиска блока, включая пересекающиеся вхождения
    window, target = deque(maxlen=len(word)), deque(word)
    hits, rows = 0, {}

    for i, symbol in enumerate(islice(source.generate(seed), max(sizes)), 1):
        window.append(symbol)
        # Подсчёт совпадений текущего окна с заданным блоком
        hits += window == target
        if i in sizes:
            # Подсчёт частоты как числа вхождений / число возможных позиций блока
            denominator = i - len(word) + 1
            rows[i] = (hits, Fraction(hits, denominator) if denominator > 0 else None)
    return first, average, rows


# Интерфейс командной строки для генерации последовательности и оценки частоты появления заданного блока
# Обрабатываются параметры запуска, вывод результатов в JSON и ошибки выполнения программы

# Начало генерации Codex
def main() -> int:
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
            limit = args.N if args.N is not None and args.N > 0 else None
            for symbol in islice(source.generate(args.seed), limit):
                print(json.dumps(symbol, ensure_ascii=False), flush=True)
        else:
            with open(args.word, encoding="utf-8") as file:
                word = json.load(file)
            first, average, rows = estimate(source, word, args.N, args.seed)
            print(json.dumps(dict(first=first, average=average, N=args.N, frequency=rows[args.N][1],
                                  table=[dict(N=n, frequency=f,
                                              error_first=None if f is None else abs(f - first),
                                              error_average=None if f is None else abs(f - average))
                                         for n, (_, f) in rows.items()]), default=str, indent=2))
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