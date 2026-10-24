# Задача 1.1, вариант 14

```sh
python3.11 main.py --variant
python3.11 main.py generate examples/source14.json --N 20 --seed 14
python3.11 main.py estimate examples/source14.json --N 1000000 --word examples/word.json --seed 14
python3.11 -m unittest discover -s tests -v
```

`generate` выводит по одному JSON-символу на строку. При `--N None`, N <= 0 или без `--N` генерация продолжается до Ctrl+C

`estimate` принимает блок как JSON-массив строк и требует N >= длины блока > 0. Поля результата: `first` - вероятность первого блока, `average` - среднее первых L позиций, `frequency` - частота, `table` - частоты и отклонения для N=100, 1000, ..., 1000000 и заданного N

Оба режима принимают все источники из `examples/`, случайность задаётся `--seed`

[Отчёт](REPORT.md), [спецификация формата](FORMAT.md), [результаты тестов](RESULTS.md)
