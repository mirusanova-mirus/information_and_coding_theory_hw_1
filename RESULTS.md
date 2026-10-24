Вариант 14

# Результаты задачи 1.1

Python 3.11.14, seed=14

```text
python3.11 main.py --variant
Код завершения: 0
s=14, k=3, M=4, L=7, d=3, q=5, epsilon=1/10000
```

## Генерация

```text
python3.11 main.py generate examples/source14.json --N 10 --seed 14
Код завершения: 0
"B"
"C"
"B"
"B"
"A"
"A"
"C"
"A"
"A"
"B"
```

```text
python3.11 main.py generate examples/markov14.json --N 10 --seed 14
Код завершения: 0
"B"
"C"
"C"
"C"
"B"
"B"
"C"
"B"
"B"
"C"
```

```text
python3.11 main.py generate tests/constant.json --N 5 --seed 14
Код завершения: 0
"A"
"A"
"A"
"A"
"A"
```

## Вероятности и частота

```text
python3.11 main.py estimate examples/source14.json --N 1000000 --word examples/word.json --seed 14
Код завершения: 0
{
  "first": "35/432",
  "average": "85/648",
  "N": 1000000,
  "frequency": "131273/999999",
  "table": [
    {
      "N": 100,
      "frequency": "1/9",
      "error_first": "13/432",
      "error_average": "13/648"
    },
    {
      "N": 1000,
      "frequency": "136/999",
      "error_first": "881/15984",
      "error_average": "119/23976"
    },
    {
      "N": 10000,
      "frequency": "125/909",
      "error_first": "2465/43632",
      "error_average": "415/65448"
    },
    {
      "N": 100000,
      "frequency": "1479/11111",
      "error_first": "250043/4799952",
      "error_average": "13957/7199928"
    },
    {
      "N": 1000000,
      "frequency": "131273/999999",
      "error_first": "804073/15999984",
      "error_average": "2407/23999976"
    }
  ]
}
```

Дополнительные запуски `estimate` с `--word examples/word.json --seed 14`

| Файл | N | first | average | frequency |
| --- | --- | --- | --- | --- |
| examples/iid14.json | 1000000 | 1/6 | 1/6 | 167473/999999 |
| examples/markov14.json | 1000000 | 1/9 | 1/9 | 111392/999999 |
| examples/nonergodic14.json | 1000000 | 1/9 | 1/9 | 167473/999999 |
| tests/constant.json | 1000 | 0 | 0 | 0 |

Для блока `tests/unknown_word.json` на `examples/source14.json` при N=100: `first=0`, `average=0`, `frequency=0`, код завершения 0

## Некорректные входы

```text
python3.11 main.py generate tests/invalid.json --N 1
Код завершения: 1

Ошибка: model_1: нужны неотрицательные вероятности с суммой 1
```

```text
python3.11 main.py estimate examples/source14.json --N 1 --word examples/word.json
Код завершения: 1

Ошибка: Нужно N >= длины блока > 0
```

```text
python3.11 main.py estimate examples/source14.json --N 100 --word tests/empty_word.json
Код завершения: 1

Ошибка: Блок должен быть непустым JSON-массивом строк
```

## Автотесты

```text
python3.11 -m unittest discover -s tests -v
Ran 15 tests in 9.787s
OK
```
