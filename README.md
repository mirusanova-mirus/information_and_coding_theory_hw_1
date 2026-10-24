# Задачи 1.1 и 1.2, вариант 14

```sh
python3.11 source.py --variant
python3.11 source.py generate examples/source14.json --N 20 --seed 14
python3.11 source.py estimate examples/source14.json --N 1000000 --word examples/word.json --seed 14
python3.11 -m unittest discover -s tests -v
```

`generate` выводит по одному JSON-символу на строку. При `--N None`, N <= 0 или без `--N` генерация продолжается до Ctrl+C

`estimate` принимает блок как JSON-массив строк и требует N >= длины блока > 0. Поля результата: `first` - вероятность первого блока, `average` - среднее первых L позиций, `frequency` - частота, `table` - частоты и отклонения для N=100, 1000, ..., 1000000 и заданного N

[Отчёт](REPORT.md), [спецификация формата](FORMAT.md), [результаты тестов](RESULTS.md)

## Задача 1.2

```sh
python3.11 coding.py entropy examples/iid14.json
python3.11 coding.py code examples/iid14.json --R 1.6
```

Оба режима проверяют стационарность и отсутствие памяти. `entropy` выводит H в битах на символ, `code` выводит точные ошибки, минимальное n на заданном отрезке и ответ о существовании n0 для всех больших n

`code14.json` содержит описание кодов для всех рассмотренных n, формат описан в отчёте. По умолчанию q=5, epsilon=1/10000, nmax=50
