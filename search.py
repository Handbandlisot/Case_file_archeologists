import os
import re
import stat
from typing import List, Dict, Any, Optional, Tuple
import utils  # Функции архитектора
import navigation  # Функции инженера навигации  
import analysis  # Функции аналитика

def find_files_windows(pattern: str, path: str,
                       case_sensitive: bool = False) -> List[str]:
    """Search for files matching a Windows wildcard pattern.

    The search is recursive and walks the tree with
    navigation.list_directory(). Windows wildcards are supported:
    "*" matches any sequence of characters, "?" matches a single
    character. Matching is case-insensitive by default, in line
    with Windows path semantics. System files and links are skipped,
    which keeps the scan counter consistent with the total
    estimated by analysis.count_files().

    analysis.count_files() is used to estimate the total number of
    files so that scan progress can be shown in the terminal.

    Args:
        pattern: wildcard pattern for file names (e.g. "secrets*.txt").
        path: the directory where the search starts.
        case_sensitive: match the pattern case-sensitively if True.

    Returns:
        Full paths of the matching files; an empty list when nothing
        matched or the directory cannot be read.
    """
    if not pattern:
        return []

    # Translate the Windows wildcard into a regular expression
    regex = "".join(
        ".*" if char == "*" else "." if char == "?" else re.escape(char)
        for char in pattern
    )
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        matcher = re.compile(regex, flags).fullmatch
    except re.error:
        return []

    results: List[str] = []

    # File count estimate for progress tracking (spec requirement)
    counted, total_files = analysis.count_files(path)
    scanned = 0

    def walk_directory(current_path: str) -> None:
        nonlocal scanned
        success, items = navigation.list_directory(current_path)
        if not success:
            return
        for item in items:
            if item["link"] or item["system"]:
                continue
            if item["type"] == "file":
                scanned += 1
                if counted and total_files and scanned % 10 == 0:
                    print(f"\r  Scanning: {scanned}/{total_files} files...",
                          end="", flush=True)
                if matcher(item["name"]):
                    results.append(item["path"])
            elif item["type"] == "dir":
                walk_directory(item["path"])

    walk_directory(path)
    if counted and total_files and scanned:
        print()  # finish the progress line
    return results


def find_by_windows_extension(extensions: List[str], path: str) -> List[str]:
    """
       Рекурсивно ищет файлы по списку расширений.
       Поиск выполняется без учёта регистра. Точка перед расширением
       добавляется автоматически. Символические ссылки и junction points пропускаются.
       Скрытые и системные файлы участвуют в поиске.

       Args:
           extensions: список расширений
           path: путь к начальному каталогу поиска.

       Returns:
           Список полных путей найденных файлов. Возвращает пустой
           список, если совпадений нет, список расширений пуст или
           начальный каталог недоступен.
       """
    normalized_ext = set()
    for ext in extensions:
        normalized = ext.strip().lower()

        if normalized and not normalized.startswith("."):
            normalized = "." + normalized

        normalized_ext.add(normalized)

    if not normalized_ext:
        return []

    results = []

    def walk_directory(current_path: str) -> None:
        """
        Рекурсивно обходит каталог и добавляет найденные пути в results.
        """
        success, items = navigation.list_directory(current_path)
        if not success:
            return

        for item in items:
            if item["link"]:
                continue
            if item["type"] == "file":
                file_ext = os.path.splitext(item["name"])[1].lower()
                if file_ext in normalized_ext:
                    results.append(item["path"])

            elif item["type"] == "dir":
                walk_directory(item["path"])

    walk_directory(path)
    return results


def find_large_files_windows(min_size_mb: float, path: str) -> List[Dict[str, Any]]:
    """
    Рекурсивно ищет файлы не меньше заданного размера.
    Результаты сортируются по размеру от большего к меньшему.

    Args:
        min_size_mb: минимальный размер файла в мегабайтах
        path: начальный каталог поиска.

    Returns:
        Список словарей с путём, размером в MB и расширением файла.
    """
    results = []
    if min_size_mb < 0:
        return []
    min_size_bytes = min_size_mb * 1024 * 1024

    def walk_directory(current_path: str) -> None:
        """
        Рекурсивно обходит каталог и добавляет информацию
        о файлах, размер которых не меньше заданного порога.
        """
        success, items = navigation.list_directory(current_path)
        if not success:
            return

        for item in items:
            if item["link"]:
                continue

            if item["type"] == "file":
                if item["size"] >= min_size_bytes:
                    ext = os.path.splitext(item["name"])[1].lower()
                    results.append({"path": item["path"], "size_mb": item["size"] / (1024 * 1024), "type": ext})

            elif item["type"] == "dir":
                walk_directory(item["path"])

    walk_directory(path)
    results.sort(key=lambda x: x["size_mb"], reverse=True)
    return results



def find_windows_system_files(path: str) -> List[str]:
    """Поиск системных файлов Windows.

    Ищет файлы, характерные для критической инфраструктуры ОС (.exe, .dll, .sys),
    ориентируясь на стандартные системные каталоги (Windows, System32 и т.д.).
    Использует переменные окружения и специальные папки Windows.
    """
    system_files = []
    target_extensions = {".exe", ".dll", ".sys"}

    # Получаем пути к важным системным директориям Windows через переменные окружения
    # Имя каталога приводим к нижнему регистру для регистронезависимого сравнения
    system_roots = []

    win_dir = os.environ.get("SystemRoot") or os.environ.get("WINDIR")
    if win_dir:
        system_roots.append(os.path.normpath(win_dir).lower())

        # Добавляем частые системные подкаталоги
        for sub_dir in ["system32", "syswow64", "drivers"]:
            system_roots.append(os.path.join(win_dir, sub_dir).lower())

    # Приводим исследуемый путь к единому виду
    current_search_path = os.path.normpath(path).lower()

    # Проверяем, находится ли текущий путь внутри какой-либо системной директории Windows
    is_inside_system_zone = any(
        current_search_path.startswith(root) or root.startswith(
            current_search_path)
        for root in system_roots
    )

    if not is_inside_system_zone:
        return system_files  # Если мы далеко от системных папок, ничего не возвращаем в целях оптимизации

    # Используем безопасное чтение каталога через утилиты архитектора
    items = utils.safe_windows_listdir(path)
    for item_name in items:
        full_path = os.path.join(path, item_name)

        # Пропускаем Junction Points и Symlinks во избежание бесконечной рекурсии
        if os.path.islink(full_path):
            continue

        if os.path.isdir(full_path):
            # Рекурсивно уходим вглубь системных папок
            system_files.extend(find_windows_system_files(full_path))
        else:
            # Проверяем расширение файла (регистронезависимо)
            _, ext = os.path.splitext(item_name.lower())
            if ext in target_extensions:
                system_files.append(full_path)

    return system_files


def search_menu_handler(current_path: str) -> bool:
    """Обработчик меню поиска для Windows.

    Реализует интерактивное терминальное меню с использованием оператора `match case`.
    Интегрирует функции поиска текущего модуля и выводит статистику.
    """
    print("\n" + "=" * 50)
    print(f"🕵️ ДРЕВНИЕ ПОИСКОВЫЕ АЛГОРИТМЫ WINDOWS")
    print(f"Текущая зона сканирования: {current_path}")
    print("=" * 50)
    print("1. Поиск файлов по шаблону (Wildcards: *, ?)")
    print("2. Поиск по системным расширениям Windows (.exe, .dll...)")
    print("3. Поиск крупных файлов (Артефактов)")
    print("4. Автоматическое сканирование Системных файлов ОС")
    print("0. Вернуться в Главное меню")
    print("=" * 50)

    choice = input("Выберите режим сканирования (0-4): ").strip()

    match choice:
        case "1":
            pattern = input(
                "Введите шаблон для поиска (например, secrets*.txt): ").strip()
            case_opt = input("Учитывать регистр букв? (y/N): ").strip().lower()
            case_sensitive = True if case_opt == 'y' else False

            print("\n🔍 Запуск поискового сканирования...")
            results = find_files_windows(pattern, current_path, case_sensitive)
            format_windows_search_results(results, "pattern")

        case "2":
            ext_input = input(
                "Введите расширения через запятую (например: exe, bat, docx): ")
            # Очищаем от пробелов и точек, формируем чистый список
            extensions = [f".{e.strip().lstrip('.')}" for e in
                          ext_input.split(",") if e.strip()]

            print("\n🔍 Фильтрация структуры по расширениям...")
            results = find_by_windows_extension(extensions, current_path)
            format_windows_search_results(results, "extension")

        case "3":
            try:
                min_size = float(
                    input("Введите минимальный размер файла-артефакта в МБ: "))
                print("\n🔍 Взвешивание файлов в локальных секторах...")
                results = find_large_files_windows(min_size, current_path)
                format_windows_search_results(results, "large_files")
            except ValueError:
                print(
                    "❌ Ошибка: Введено некорректное числовое значение размера.")

        case "4":
            print(
                "\n🔒 Анализ системных секторов Windows на наличие исполняемого кода...")
            results = find_windows_system_files(current_path)
            format_windows_search_results(results, "system")

        case "0":
            print("⬅️ Возврат в командный интерфейс архитектора...")
            return False

        case _:
            print(
                "⚠️ Неизвестная директива терминала 2142 года. Повторите ввод.")

    return True


def _file_attribute_flags(path: str) -> str:
    """Return Windows attribute flags of a file as a short string.

    "H" — hidden, "S" — system, "R" — read-only; "-" when the file
    has none of these attributes. Hidden detection falls back to
    utils.is_hidden_windows_file() when attributes are unavailable.

    Args:
        path: full path to the file.

    Returns:
        A compact flags string for the results table.
    """
    hidden = utils.is_hidden_windows_file(path)
    system = readonly = False
    try:
        info = os.stat(path)
    except OSError:
        info = None
    attrs = getattr(info, "st_file_attributes", 0) or 0
    system = bool(attrs & stat.FILE_ATTRIBUTE_SYSTEM)
    readonly = bool(attrs & stat.FILE_ATTRIBUTE_READONLY)
    flags = ""
    if hidden:
        flags += "H"
    if system:
        flags += "S"
    if readonly:
        flags += "R"
    return flags or "-"


def format_windows_search_results(results: List, search_type: str) -> None:
    """Print search results as a readable table for the Windows UI.

    Handles both result shapes used across the module:
    * lists of file paths (pattern, extension and system searches);
    * lists of dictionaries with "path" and "size_mb" keys
      (the large-files search).

    Sizes are formatted with utils.format_size(). Every row shows
    the attribute flags of the file. The footer prints attribute
    statistics for the scanned folders, obtained with
    analysis.get_windows_file_attributes_stats().

    Args:
        results: search results to display.
        search_type: result kind — "pattern", "extension",
            "large_files" or "system"; selects the header text.
    """
    titles = {
        "pattern": "Search results: wildcard pattern",
        "extension": "Search results: files by extension",
        "large_files": "Search results: large files",
        "system": "Search results: Windows system files",
    }
    print()
    print("=" * 70)
    print(titles.get(search_type, "Search results"))
    print("=" * 70)

    if not results:
        print("No files found.")
        return

    # Normalize the entries to (path, size in bytes or None)
    entries: List[Tuple[str, Optional[int]]] = []
    for result in results:
        if isinstance(result, dict):
            path = str(result.get("path", ""))
            size_mb = result.get("size_mb")
            size = (int(size_mb * 1024 * 1024)
                    if isinstance(size_mb, (int, float)) else None)
        else:
            path = str(result)
            size = None
        if path:
            entries.append((path, size))

    print(f"{'Flags':<6} {'Size':>12}  Path")
    total_size = 0
    for path, size in entries:
        if size is None:
            try:
                size = os.path.getsize(path)
            except OSError:
                size = 0
        total_size += size
        flags = _file_attribute_flags(path)
        print(f"{flags:<6} {utils.format_size(size):>12}  {path}")

    print("-" * 70)
    print(f"Files: {len(entries)}   "
          f"Total size: {utils.format_size(total_size)}")

    # Attribute statistics for the folders that contain the results
    folders: List[str] = []
    for path, _ in entries:
        folder = utils.get_parent_path(path)
        if folder:
            folders.append(folder)

    # Keep only top-level folders to avoid walking nested trees twice
    top_folders: List[str] = []
    for folder in sorted(set(folders), key=len):
        lower = folder.lower()
        if not any(lower.startswith(top.lower() + "\\")
                   or lower.startswith(top.lower() + "/")
                   for top in top_folders):
            top_folders.append(folder)

    totals = {"hidden": 0, "system": 0, "readonly": 0}
    for folder in top_folders:
        folder_stats = analysis.get_windows_file_attributes_stats(folder)
        for key in totals:
            totals[key] += folder_stats.get(key, 0)

    print(f"Attribute statistics for {len(top_folders)} scanned folder(s): "
          f"hidden={totals['hidden']}, system={totals['system']}, "
          f"readonly={totals['readonly']}")
