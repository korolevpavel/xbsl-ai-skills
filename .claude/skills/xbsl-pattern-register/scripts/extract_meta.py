#!/usr/bin/env python3
"""
Извлекает метаданные из YAML-файла объекта конфигурации 1С:Элемент.
Поддерживает: РегистрНакопления, Документ.

Использование:
    python extract_meta.py <путь-к-файлу.yaml>

Вывод:
    Для регистра накопления — ВидРегистра, Измерения, Ресурсы (с суффиксами для запросов).
    Для документа — реквизиты шапки, табличные части и их реквизиты.
"""

import sys
import yaml


def extract_register(data: dict) -> None:
    имя = data.get("Имя", "???")
    вид = data.get("ВидРегистра", "???")
    измерения = [d["Имя"] for d in data.get("Измерения", []) if "Имя" in d]
    ресурсы = [r["Имя"] for r in data.get("Ресурсы", []) if "Имя" in r]

    print(f"=== РегистрНакопления: {имя} ===")
    print(f"ВидРегистра: {вид}")
    print()

    if измерения:
        print("Измерения (в ДобавитьЗапись и ГДЕ — без суффикса):")
        for и in измерения:
            print(f"  {и}")
    else:
        print("Измерения: (не заданы)")
    print()

    if ресурсы:
        print("Ресурсы:")
        print("  В ДобавитьЗапись (без суффикса):")
        for р in ресурсы:
            print(f"    {р}")
        print("  В запросе к .Остатки (с суффиксом Остаток):")
        for р in ресурсы:
            print(f"    {р}Остаток")
    else:
        print("Ресурсы: (не заданы)")
    print()

    if вид == "Остатки":
        print("ВидЗаписи: НУЖЕН (ВидЗаписиРегистраНакопления.Приход / .Расход)")
    else:
        print("ВидЗаписи: НЕ НУЖЕН (регистр Обороты)")


def extract_document(data: dict) -> None:
    имя = data.get("Имя", "???")

    # Реквизиты шапки (системные Дата/Номер — всегда есть)
    реквизиты_шапки = [
        р["Имя"] for р in data.get("Реквизиты", []) if "Имя" in р
    ]

    print(f"=== Документ: {имя} ===")
    print()

    if реквизиты_шапки:
        print("Реквизиты шапки:")
        for р in реквизиты_шапки:
            print(f"  {р}")
    else:
        print("Реквизиты шапки: (не заданы)")
    print()

    тч = data.get("ТабличныеЧасти", [])
    if тч:
        print("Табличные части:")
        for часть in тч:
            имя_тч = часть.get("Имя", "???")
            реквизиты_тч = [
                р["Имя"] for р in часть.get("Реквизиты", []) if "Имя" in р
            ]
            print(f"  {имя_тч}:")
            for р in реквизиты_тч:
                print(f"    {р}")
    else:
        print("Табличные части: (не заданы)")

    print()
    print(f"Обработчик записывается в: {имя}.Объект.xbsl")


def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python extract_meta.py <путь-к-файлу.yaml>", file=sys.stderr)
        sys.exit(1)

    path = sys.argv[1]
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        print(f"Файл не найден: {path}", file=sys.stderr)
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Ошибка парсинга YAML: {e}", file=sys.stderr)
        sys.exit(1)

    вид_элемента = data.get("ВидЭлемента", "")

    if вид_элемента == "РегистрНакопления":
        extract_register(data)
    elif вид_элемента == "Документ":
        extract_document(data)
    else:
        print(f"Неизвестный ВидЭлемента: '{вид_элемента}'")
        print("Скрипт поддерживает: РегистрНакопления, Документ")
        sys.exit(1)


if __name__ == "__main__":
    main()
