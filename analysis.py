import os
from typing import Dict, Any, Tuple
from collections import defaultdict
import utils  # Функции архитектора
import navigation  # Функции инженера навигации


def count_files(path: str) -> Tuple[bool, int]:
    """
    Рекурсивно подсчитывает обычные файлы в Windows-каталоге.

    Системные объекты, символические ссылки и junction points
    пропускаются.

    Args:
        path: Путь к анализируемому каталогу.

    Returns:
        (True, количество файлов) при успешном чтении начального
        каталога или (False, 0) при ошибке.
    """
    success, items = navigation.list_directory(path)

    if not success:
        return False, 0

    total_files = 0

    for item in items:
        if item["system"] or item["link"]:
            continue

        if item["type"] == "file":
            total_files += 1

        elif item["type"] == "dir":
            child_success, child_count = count_files(item["path"])

            if child_success:
                total_files += child_count

    return True, total_files


def count_directories(path: str) -> Tuple[bool, int]:
    """
    Рекурсивно подсчитывает вложенные каталоги.

    Начальный каталог не входит в результат. Системные каталоги,
    символические ссылки и junction points пропускаются.

    Args:
        path: Путь к анализируемому каталогу.

    Returns:
        (True, количество каталогов) при успехе или (False, 0)
        при ошибке чтения начального каталога.
    """
    success, items = navigation.list_directory(path)

    if not success:
        return False, 0

    total_directories = 0

    for item in items:
        if item["system"] or item["link"]:
            continue

        if item["type"] == "dir":
            total_directories += 1

            child_success, child_count = count_directories(item["path"])

            if child_success:
                total_directories += child_count

    return True, total_directories


def count_bytes(path: str) -> Tuple[bool, int]:
    """
    Рекурсивно вычисляет суммарный размер файлов в байтах.

    Системные объекты и ссылки пропускаются. Файл с недоступным
    или некорректным размером не увеличивает сумму.

    Args:
        path: Путь к анализируемому каталогу.

    Returns:
        (True, размер в байтах) при успехе или (False, 0)
        при ошибке чтения начального каталога.
    """
    success, items = navigation.list_directory(path)

    if not success:
        return False, 0

    total_bytes = 0

    for item in items:
        if item["system"] or item["link"]:
            continue

        if item["type"] == "file":
            size = item.get("size", 0)

            if isinstance(size, int) and size >= 0:
                total_bytes += size

        elif item["type"] == "dir":
            child_success, child_bytes = count_bytes(item["path"])

            if child_success:
                total_bytes += child_bytes

    return True, total_bytes


def analyze_windows_file_types(path: str) -> Tuple[bool, Dict[str, Dict[str, Any]]]:
    """
    Рекурсивно группирует файлы по расширениям.

    Расширения приводятся к нижнему регистру. Пустая строка используется
    как ключ для файлов без расширения. Системные объекты и ссылки
    пропускаются.

    Args:
        path: Путь к анализируемому каталогу.

    Returns:
        Пара из признака успеха и словаря статистики. Для каждого
        расширения сохраняются количество файлов и общий размер:
        {".txt": {"count": 2, "size": 1024}}.
    """
    success, items = navigation.list_directory(path)
    if not success:
        return False, {}

    statistics = defaultdict(lambda: {"count": 0, "size": 0})
    for item in items:

        if item["system"] or item["link"]:
            continue

        if item["type"] == "file":
            extension = os.path.splitext(item["name"])[1].lower()

            size = item.get("size", 0)
            if isinstance(size, int) and size >= 0:
                statistics[extension]["size"] += size

            statistics[extension]["count"] += 1

        elif item["type"] == "dir":
            child_success, child_statistics = analyze_windows_file_types(item["path"])
            if child_success:
                for ext, data in child_statistics.items():
                    statistics[ext]["count"] += data["count"]
                    statistics[ext]["size"] += data["size"]

    return True, dict(statistics)


def get_windows_file_attributes_stats(path: str) -> Dict[str, int]:
    """
    Рекурсивно собирает статистику по атрибутам файлов Windows.

    Считает скрытые, системные и доступные только для чтения файлы.
    Символические ссылки и junction points пропускаются.

    Args:
        path: Путь к анализируемому каталогу.

    Returns:
        Словарь с количеством файлов по атрибутам:
        {"hidden": 0, "system": 0, "readonly": 0}.
    """
    success, items = navigation.list_directory(path)

    stats = {"hidden": 0, "system": 0, "readonly": 0}
    if not success:
        return stats

    for item in items:
        if item["link"]:
            continue

        if item["type"] == "file":

            if item["hidden"]:
                stats["hidden"] += 1
            if item["system"]:
                stats["system"] += 1
            if item["readonly"]:
                stats["readonly"] += 1

        elif item["type"] == "dir":
            child_stats = get_windows_file_attributes_stats(item["path"])
            stats["hidden"] += child_stats["hidden"]
            stats["system"] += child_stats["system"]
            stats["readonly"] += child_stats["readonly"]

    return stats


def show_windows_directory_stats(path: str) -> bool:
    """
    Выводит сводную статистику Windows-каталога.

    Показывает количество файлов и вложенных каталогов, общий размер,
    распределение файлов по расширениям и статистику атрибутов.

    Args:
        path: Путь к анализируемому каталогу.

    Returns:
        True при успешном анализе или False, если начальный каталог
        прочитать не удалось.
    """
    files_success, total_files = count_files(path)
    bytes_success, total_bytes = count_bytes(path)
    types_success, file_types = analyze_windows_file_types(path)
    dir_success, total_dirs = count_directories(path)
    attribute_stats = get_windows_file_attributes_stats(path)

    if not files_success or not bytes_success or not types_success or not dir_success:
        print(f"Не удалось проанализировать каталог: {path}")
        return False

    print(f"\nСтатистика каталога: {path}")
    print(f"Всего файлов без системных и ссылок: {total_files}")
    print(f"Всего вложенных каталогов: {total_dirs}")
    print(f"Общий размер: {utils.format_size(total_bytes)}")

    print("\nТипы файлов:")
    if not file_types:
        print("Файлы не найдены.")

    for extension, data in file_types.items():

        if extension:
            label = extension
        else:
            label = "(без расширения)"

        size = utils.format_size(data["size"])
        print(f"    {label}: {data['count']} шт., общий размер: {size}")

    print("\nСтатистика атрибутов:")
    print(f"  Скрытые: {attribute_stats['hidden']}")
    print(f"  Системные: {attribute_stats['system']}")
    print(f"  Только для чтения: {attribute_stats['readonly']}")

    return True
