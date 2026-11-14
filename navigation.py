"""navigation.py — навигация по файловой системе Windows.

Проект «Файловый археолог», модуль 2 (I этап).
Разработчик: Инженер навигации.
Зависимости: utils.py.

Особенности Windows, учтённые в модуле:
* разделитель путей «\\», регистронезависимые имена;
* диски (C:, D:, ...) определяются через WinAPI GetLogicalDrives;
* атрибуты файлов (скрытый, системный, только для чтения);
* junction points и symlinks помечаются флагом ``link``, чтобы
  модуль анализа мог не заходить в них (защита от циклов);
* длинные пути (> 260 символов) автоматически переводятся в
  формат «\\\\?\\C:\\...» и сокращаются обратно, когда это возможно;
* специальные папки (Desktop, Documents, Downloads, Windows,
  Program Files и др.) определяются через Known Folders API,
  с запасным вариантом через os.environ;
* ошибки доступа (PermissionError и др.) не прерывают работу:
  причина последней неудачи доступна через get_last_error().

Модуль не падает при запуске вне Windows (для разработки и тестов),
но осмысленно работает только в Windows.
"""

import ctypes
import os
import re
import stat
import string
import sys
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import utils  # Импорт функций архитектора

# Порог, после которого путь переводится в формат «\\?\» (для каталогов
# WinAPI допускает не более 248 символов вместе с завершающим нулём)
_LONG_PATH_THRESHOLD = 248

# Тег reparse point для junction (IO_REPARSE_TAG_MOUNT_POINT)
_REPARSE_TAG_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT",
                                   0xA0000003)

# GUID специальных папок для SHGetKnownFolderPath
_KNOWN_FOLDER_GUIDS = {
    "Desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "Documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "Downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "Pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "Music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "Videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
}

# Причина последней неудачной операции (для вывода пользователю)
_last_error: str = ""


def _set_error(message: str) -> None:
    """Запоминает причину последней неудачной операции."""
    global _last_error
    _last_error = message


def get_last_error() -> str:
    """Возвращает причину последней неудачи ("" если её не было).

    Удобно для main.py: после ``(False, ...)`` из list_directory()
    или move_down() можно показать пользователю, что пошло не так.
    """
    return _last_error


def _describe_os_error(error: OSError, path: str) -> str:
    """Переводит Windows-ошибку в понятное сообщение."""
    if isinstance(error, PermissionError):
        return f"Отказано в доступе: {path}"
    if isinstance(error, FileNotFoundError):
        return f"Путь не найден: {path}"
    if getattr(error, "winerror", None) == 206 or error.errno == 36:
        return f"Слишком длинный путь: {path}"
    return f"Ошибка доступа к '{path}': {error.strerror or error}"


def _is_absolute(path: str) -> bool:
    """Абсолютный путь Windows: «C:\\...» или UNC «\\\\server\\...»."""
    if path.startswith("\\\\"):
        return True
    drive, tail = os.path.splitdrive(path)
    return bool(drive) and tail[:1] in ("\\", "/")


def normalize_path(path: str) -> str:
    """Приводит путь к каноническому виду Windows.

    * убирает лишние разделители, «.» и «..»;
    * «C:» превращает в «C:\\»;
    * слишком длинный абсолютный путь переводит в формат «\\\\?\\...»,
      а короткий путь с таким префиксом — обратно в обычный.

    Args:
        path: исходный путь.

    Returns:
        Нормализованный путь (пустая строка остаётся пустой).
    """
    if not path:
        return path

    prefix = utils.EXTENDED_PATH_PREFIX
    plain = path
    if path.startswith(prefix):
        body = path[len(prefix):]
        if body[:4].upper() == "UNC\\":
            plain = "\\\\" + body[4:]
        else:
            plain = body

    plain = os.path.normpath(plain)
    drive, tail = os.path.splitdrive(plain)
    if drive and not tail and not drive.startswith("\\\\"):
        plain = drive + "\\"

    if len(plain) < _LONG_PATH_THRESHOLD or not _is_absolute(plain):
        return plain
    if plain.startswith("\\\\"):
        return prefix + "UNC\\" + plain[2:]
    return prefix + plain


def _is_root(path: str) -> bool:
    """True, если путь — корень диска («C:\\») или UNC-шары."""
    drive, tail = os.path.splitdrive(normalize_path(path))
    return bool(drive) and tail in ("", "\\", "/")


def get_current_drive() -> str:
    """Получение текущего диска Windows.

    Returns:
        Текущий диск, например "C:" (для UNC — "\\\\server\\share").
        Если определить не удалось — диск из переменной SystemDrive.
    """
    drive = os.path.splitdrive(os.getcwd())[0]
    if not drive:
        drive = os.environ.get("SystemDrive", "")
    if len(drive) == 2 and drive[1] == ":":
        drive = drive.upper()
    return drive


def list_available_drives() -> List[str]:
    """Получение списка доступных дисков Windows.

    Используется WinAPI GetLogicalDrives (битовая маска дисков) —
    он не обращается к самим устройствам, поэтому не «зависает»
    на пустых картридерах. Если вызов недоступен, запасной вариант —
    перебор букв A–Z.

    Returns:
        Список дисков вида ['C:', 'D:']; вне Windows — пустой список.
    """
    # если проверка не была сделана в main
    if not utils.is_windows_os():
        return []

    try:
        bitmask = int(ctypes.windll.kernel32.GetLogicalDrives())
    except (AttributeError, OSError, ValueError):
        bitmask = 0

    drives = [f"{string.ascii_uppercase[i]}:"
              for i in range(26) if bitmask & (1 << i)]
    if not drives:
        drives = [f"{letter}:" for letter in string.ascii_uppercase
                  if os.path.exists(f"{letter}:\\")]
    return drives


def change_drive(drive: str) -> Tuple[bool, str]:
    """Переход на другой диск Windows.

    Args:
        drive: диск в любом виде: "D", "d:", "D:\\".

    Returns:
        (True, "D:\\") при успехе; (False, "") если диска нет
        или он не готов (например, пустой дисковод).
    """
    letter = drive.strip().rstrip("\\/:").upper()
    if len(letter) != 1 or letter not in string.ascii_uppercase:
        _set_error(f"Некорректное имя диска: '{drive}'")
        return False, ""
    if f"{letter}:" not in list_available_drives():
        _set_error(f"Диск {letter}: не найден")
        return False, ""

    root = f"{letter}:\\"
    if not os.path.isdir(root):
        _set_error(f"Диск {letter}: не готов")
        return False, ""
    _set_error("")
    return True, root


def _read_attributes(info: Optional[os.stat_result]) -> Dict[str, bool]:
    """Извлекает флаги атрибутов из результата os.lstat()."""
    flags = {"system": False, "readonly": False, "link": False}
    if info is None:
        return flags

    attrs = getattr(info, "st_file_attributes", None)
    if attrs is None:
        # Не Windows: «только чтение» определяем по правам владельца
        flags["readonly"] = not info.st_mode & stat.S_IWUSR
        flags["link"] = stat.S_ISLNK(info.st_mode)
        return flags

    flags["system"] = bool(attrs & stat.FILE_ATTRIBUTE_SYSTEM)
    flags["readonly"] = bool(attrs & stat.FILE_ATTRIBUTE_READONLY)
    is_junction = (
        bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        and getattr(info, "st_reparse_tag", 0) == _REPARSE_TAG_MOUNT_POINT
    )
    flags["link"] = stat.S_ISLNK(info.st_mode) or is_junction
    return flags


def _build_item(directory: str, name: str) -> Dict[str, Any]:
    """Собирает словарь с информацией об одном элементе каталога."""
    full_path = normalize_path(os.path.join(directory, name))
    try:
        info: Optional[os.stat_result] = os.lstat(full_path)
    except OSError:
        info = None  # нет доступа к метаданным — элемент всё равно виден

    is_dir = os.path.isdir(full_path)
    modified = ""
    size = 0
    if info is not None:
        try:
            modified = datetime.fromtimestamp(info.st_mtime).strftime(
                "%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            modified = ""  # дата вне допустимого диапазона
        if not is_dir:
            size = info.st_size

    item: Dict[str, Any] = {
        "name": name,
        "type": "dir" if is_dir else "file",
        "size": size,
        "modified": modified,
        "hidden": utils.is_hidden_windows_file(full_path),
        "path": full_path,
    }
    item.update(_read_attributes(info))
    return item


def list_directory(path: str) -> Tuple[bool, List[Dict[str, Any]]]:
    """Отображение содержимого каталога в Windows.

    Для каждого элемента возвращается словарь::

        {'name': 'file.txt', 'type': 'file' | 'dir', 'size': 1024,
         'modified': '2024-01-15', 'hidden': False,
         'system': False, 'readonly': False, 'link': False,
         'path': 'C:\\\\Users\\\\file.txt'}

    ``link`` — True для symlink и junction point (анализу и поиску
    не следует заходить в такие каталоги, чтобы не уйти в цикл).
    Сначала идут каталоги, затем файлы, оба списка — по имени без
    учёта регистра.

    Args:
        path: путь к каталогу (длинные пути поддерживаются).

    Returns:
        (True, данные) при успехе, (False, []) при ошибке; причина
        ошибки доступна через get_last_error().
    """
    target = normalize_path(path)
    valid, message = utils.validate_windows_path(target)
    if not valid:
        _set_error(message)
        return False, []
    if not os.path.isdir(target):
        _set_error(f"Не является каталогом: {path}")
        return False, []

    names = utils.safe_windows_listdir(target)
    if not names:
        # safe_windows_listdir() возвращает [] и для пустого каталога,
        # и при ошибке — отличаем их повторным вызовом
        try:
            os.listdir(target)
        except OSError as error:
            _set_error(_describe_os_error(error, path))
            return False, []

    items = [_build_item(target, name) for name in names]
    items.sort(key=lambda item: (item["type"] != "dir",
                                 item["name"].casefold()))
    _set_error("")
    return True, items


def _safe_text(text: str) -> str:
    """Заменяет символы, которые консоль не может отобразить.

    Консоль Windows (cp866/cp1251) падает с UnicodeEncodeError на
    «экзотических» именах файлов — вместо падения выводим «?».
    """
    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    return text.encode(encoding, errors="replace").decode(
        encoding, errors="replace")


def _attribute_flags(item: Dict[str, Any]) -> str:
    """Строка атрибутов вида 'H S R L' (по одной букве на флаг)."""
    letters = (("hidden", "H"), ("system", "S"),
               ("readonly", "R"), ("link", "L"))
    return " ".join(letter if item.get(key) else "-"
                    for key, letter in letters)


def format_directory_output(items: List[Dict[str, Any]],
                            current_path: str = "",
                            show_hidden: bool = True) -> None:
    """Форматированный вывод содержимого каталога для Windows.

    Args:
        items: данные из list_directory().
        current_path: текущий каталог (необязательно). Если это
            корень диска — дополнительно выводится список дисков.
        show_hidden: показывать ли скрытые и системные элементы.
    """
    line = "-" * 72
    if current_path:
        print(_safe_text(f"Каталог: {current_path}"))
    if current_path and _is_root(current_path):
        drives = list_available_drives()
        if drives:
            print("Доступные диски: " + "  ".join(drives))
    print(line)
    print(f"{'Изменён':<11}{'Тип':<7}{'Размер':>11}  "
          f"{'H S R L':<8}  Имя")
    print(line)

    visible = [item for item in items
               if show_hidden or not (item["hidden"] or item["system"])]
    for item in visible:
        is_dir = item["type"] == "dir"
        kind = "<DIR>" if is_dir else ""
        size = "" if is_dir else utils.format_size(item["size"])
        suffix = "\\" if is_dir else ""
        print(_safe_text(
            f"{item['modified'] or '?':<11}{kind:<7}{size:>11}  "
            f"{_attribute_flags(item):<8}  {item['name']}{suffix}"))

    if not visible:
        print("(каталог пуст)")
    print(line)

    dirs = sum(1 for item in visible if item["type"] == "dir")
    files = len(visible) - dirs
    total = sum(item["size"] for item in visible if item["type"] == "file")
    print(f"Папок: {dirs}, файлов: {files}, "
          f"размер файлов: {utils.format_size(total)}")
    hidden_count = len(items) - len(visible)
    if hidden_count:
        print(f"Скрытых/системных элементов не показано: {hidden_count}")
    print("Атрибуты: H — скрытый, S — системный, "
          "R — только чтение, L — ссылка/junction")


def move_up(current_path: str) -> str:
    """Переход в родительский каталог в Windows.

    В корне диска («C:\\») или UNC-шары подняться выше нельзя —
    возвращается тот же путь (смена диска — через change_drive()).

    Args:
        current_path: текущий путь.

    Returns:
        Путь к родительскому каталогу или current_path, если
        подняться не удалось.
    """
    current = normalize_path(current_path)
    if not current:
        _set_error("Текущий путь не задан")
        return current_path

    parent = normalize_path(utils.get_parent_path(current))
    if not parent or os.path.normcase(parent) == os.path.normcase(current):
        _set_error("Вы уже в корне диска")
        return current

    valid, message = utils.validate_windows_path(parent)
    if not valid:
        _set_error(message)
        return current_path
    _set_error("")
    return parent


def _check_accessible(path: str) -> bool:
    """Проверяет, что содержимое каталога можно прочитать.

    Чтобы не «заводить» пользователя в каталог, который нельзя
    открыть (например, «System Volume Information»).
    """
    try:
        os.listdir(path)
    except OSError as error:
        _set_error(_describe_os_error(error, path))
        return False
    return True


def move_down(current_path: str, target_dir: str) -> Tuple[bool, str]:
    """Переход в указанный подкаталог в Windows.

    Имя подкаталога ищется без учёта регистра, а возвращается в том
    виде, как оно записано на диске. Помимо имени поддерживаются:
    вложенный путь («Users\\\\Admin»), «..», «.» и абсолютный путь
    («D:\\\\Data»). Кавычки вокруг имени игнорируются.

    Args:
        current_path: текущий каталог.
        target_dir: имя подкаталога (или путь).

    Returns:
        (True, новый_путь) при успехе, (False, текущий_путь) при
        ошибке; причина — в get_last_error().
    """
    base = normalize_path(current_path)
    valid, message = utils.validate_windows_path(base)
    if not valid:
        _set_error(message)
        return False, current_path

    target = target_dir.strip().strip('"').strip()
    if not target:
        _set_error("Не указано имя каталога")
        return False, current_path

    # Абсолютный путь: «D:\Data», «\\server\share», «\Windows»
    if _is_absolute(target) or target.startswith(("\\", "/")):
        if not _is_absolute(target):
            target = os.path.splitdrive(base)[0] + target
        candidate = normalize_path(target)
        valid, message = utils.validate_windows_path(candidate)
        if not valid:
            _set_error(message)
            return False, current_path
        if not os.path.isdir(candidate):
            _set_error(f"Не является каталогом: {target_dir}")
            return False, current_path
        if not _check_accessible(candidate):
            return False, current_path
        _set_error("")
        return True, candidate

    # Относительный путь: идём по сегментам
    new_path = base
    for segment in re.split(r"[\\/]+", target):
        if not segment or segment == ".":
            continue
        if segment == "..":
            upper = move_up(new_path)
            if os.path.normcase(upper) == os.path.normcase(new_path):
                return False, current_path
            new_path = upper
            continue

        bad_char = next((c for c in utils.FORBIDDEN_CHARS
                         if c in segment), "")
        if bad_char:
            _set_error(f"Недопустимый символ '{bad_char}' "
                       f"в имени '{segment}'")
            return False, current_path

        wanted = os.path.normcase(segment)
        entries = utils.safe_windows_listdir(new_path)
        real_name = next((name for name in entries
                          if os.path.normcase(name) == wanted), None)
        if real_name is None:
            _set_error(f"Каталог '{segment}' не найден "
                       f"(или нет доступа): {new_path}")
            return False, current_path

        candidate = normalize_path(os.path.join(new_path, real_name))
        if not os.path.isdir(candidate):
            _set_error(f"'{real_name}' — не каталог")
            return False, current_path
        new_path = candidate

    valid, message = utils.validate_windows_path(new_path)
    if not valid:
        _set_error(message)
        return False, current_path
    if new_path != base and not _check_accessible(new_path):
        return False, current_path
    _set_error("")
    return True, new_path


def _known_folder_path(guid_string: str) -> str:
    """Путь к специальной папке через SHGetKnownFolderPath.

    В отличие от USERPROFILE\\Desktop учитывает перенаправление папок
    (например, Рабочий стол и Документы в OneDrive).
    Возвращает "" при любой неудаче.
    """
    class _Guid(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_uint32),
                    ("Data2", ctypes.c_uint16),
                    ("Data3", ctypes.c_uint16),
                    ("Data4", ctypes.c_ubyte * 8)]

    try:
        parsed = uuid.UUID(guid_string)
        guid = _Guid(parsed.time_low, parsed.time_mid,
                     parsed.time_hi_version,
                     (ctypes.c_ubyte * 8)(*parsed.bytes[8:]))
        buffer = ctypes.c_wchar_p()
        get_path = ctypes.windll.shell32.SHGetKnownFolderPath
        get_path.argtypes = [ctypes.POINTER(_Guid), ctypes.c_uint32,
                             ctypes.c_void_p,
                             ctypes.POINTER(ctypes.c_wchar_p)]
        get_path.restype = ctypes.c_long
        result = get_path(ctypes.byref(guid), 0, None,
                          ctypes.byref(buffer))
        value = buffer.value or ""
        ctypes.windll.ole32.CoTaskMemFree(buffer)
        return value if result == 0 else ""
    except (AttributeError, OSError, ValueError, TypeError):
        return ""


def get_windows_special_folders() -> Dict[str, str]:
    """Получение путей к специальным папкам Windows.

    Returns:
        Словарь только из существующих каталогов. Возможные ключи:
        'Home', 'Desktop', 'Documents', 'Downloads', 'Pictures',
        'Music', 'Videos', 'AppData', 'LocalAppData', 'Temp',
        'Windows', 'System32', 'Program Files',
        'Program Files (x86)', 'ProgramData'.
    """
    env = os.environ
    home = env.get("USERPROFILE", "")
    system_root = env.get("SystemRoot") or env.get("windir", "")

    candidates: Dict[str, str] = {"Home": home}
    for name, guid in _KNOWN_FOLDER_GUIDS.items():
        path = _known_folder_path(guid) if utils.is_windows_os() else ""
        if not path and home:
            path = os.path.join(home, name)  # запасной вариант
        candidates[name] = path

    candidates.update({
        "AppData": env.get("APPDATA", ""),
        "LocalAppData": env.get("LOCALAPPDATA", ""),
        "Temp": env.get("TEMP", ""),
        "Windows": system_root,
        "System32": (os.path.join(system_root, "System32")
                     if system_root else ""),
        "Program Files": env.get("ProgramFiles", ""),
        "Program Files (x86)": env.get("ProgramFiles(x86)", ""),
        "ProgramData": env.get("ProgramData", ""),
    })

    return {name: normalize_path(path)
            for name, path in candidates.items()
            if path and os.path.isdir(path)}