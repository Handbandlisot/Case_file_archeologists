import ctypes
import os
import stat
import string
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import utils


_LONG_PATH_THRESHOLD = 248
_REPARSE_TAG_MOUNT_POINT = getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT",
                                   0xA0000003)


def get_current_drive(path: str = "") -> str:
    """
    Возвращает диск, на котором находится указанный путь.

    Args:
        path: путь, диск которого нужен

    Returns:
        Диск
    """
    source = path or os.getcwd()

    drive = os.path.splitdrive(source)[0]

    if not drive:
        drive = os.environ.get("SystemDrive", "C:")

    if len(drive) == 2 and drive[1] == ":":
        drive = drive.upper()

    return drive


def list_available_drives() -> List[str]:
    """
    Возвращает список доступных дисков Windows.

    Returns:
        Список вида ["C:", "D:"]. Вне Windows - пустой список.
    """
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


def _is_absolute(path: str) -> bool:
    """
    Проверка, является ли путь абсолютным.
    """
    if path.startswith("\\\\"):
        return True
    drive, tail = os.path.splitdrive(path)
    return bool(drive) and tail[:1] in ("\\", "/")


def normalize_path(path: str) -> str:
    """
    Приводит путь к каноническому виду Windows.

    Args:
        path: исходный путь.

    Returns:
        Нормализованный путь. Пустая строка возвращается без изменений.
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


def _read_attributes(info: Optional[os.stat_result]) -> Dict[str, bool]:
    """
    Определяет флаги атрибутов элемента по результату os.lstat() (system"
    (системный), "readonly" (только для чтения) и "link"
    (symlink или junction point))

    Args:
        info: результат os.lstat()

    Returns:
        Словарь с флагами "system" (системный), "readonly" (только
        для чтения) и "link" (symlink или junction point). Если
        метаданные недоступны, все флаги равны False.
    """
    flags = {"system": False, "readonly": False, "link": False}
    if info is None:
        return flags

    attrs = getattr(info, "st_file_attributes", None)

    flags["system"] = bool(attrs & stat.FILE_ATTRIBUTE_SYSTEM)
    flags["readonly"] = bool(attrs & stat.FILE_ATTRIBUTE_READONLY)
    is_junction = (
        bool(attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        and getattr(info, "st_reparse_tag", 0) == _REPARSE_TAG_MOUNT_POINT
    )
    flags["link"] = stat.S_ISLNK(info.st_mode) or is_junction
    return flags


def _build_item(directory: str, name: str) -> Dict[str, Any]:
    """
    Собирает словарь с информацией об одном элементе каталога.

    Args:
        directory: каталог, в котором лежит элемент.
        name: имя элемента.

    Returns:
        Словарь в формате, описанном в list_directory().
    """
    full_path = normalize_path(os.path.join(directory, name))
    try:
        info: Optional[os.stat_result] = os.lstat(full_path)
    except OSError:
        info = None

    is_dir = os.path.isdir(full_path)
    modified = ""
    size = 0
    if info is not None:
        try:
            modified = datetime.fromtimestamp(info.st_mtime).strftime(
                "%Y-%m-%d")
        except (OSError, OverflowError, ValueError):
            modified = ""
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
    """
    Возвращает содержимое каталога Windows.

    Args:
        path: путь к каталогу. Длинные пути поддерживаются.

    Returns:
        (True, список_элементов) при успехе, (False, []) если путь
        некорректен, не является каталогом или нет доступа.
    """
    target = normalize_path(path)
    valid, message = utils.validate_windows_path(target)
    if not valid:
        return False, []
    if not os.path.isdir(target):
        return False, []

    names = utils.safe_windows_listdir(target)
    if not names:
        return False, []

    items = [_build_item(target, name) for name in names]
    items.sort(key=lambda item: (item["type"] != "dir",
                                 item["name"].casefold()))
    return True, items


def _is_root(path: str) -> bool:
    """Проверяет, что путь - корень диска или сетевой папки."""
    drive, tail = os.path.splitdrive(normalize_path(path))
    return bool(drive) and tail in ("", "\\", "/")


def format_directory_output(items: List[Dict[str, Any]],
                            current_path: str = "") -> None:
    """
    Печатает содержимое каталога в виде таблицы.

    Колонка «HS»: H - скрытый элемент, S - системный, "-" - флаг
    не установлен.

    Args:
        items: данные, полученные от list_directory().
        current_path: текущий каталог.
    """
    if current_path and _is_root(current_path):
        print("Доступные диски:", "  ".join(list_available_drives()))

    print(f"{'Изменён':<11}{'Тип':<7}{'Размер':>10}  {'HS':<2}  Имя")
    for item in items:
        is_dir = item["type"] == "dir"
        kind = "<DIR>" if is_dir else ""
        size = "" if is_dir else utils.format_size(item["size"])
        flags = ("H" if item["hidden"] else "-") + \
                ("S" if item.get("system") else "-")
        print(f"{item['modified'] or '-':<11}{kind:<7}{size:>10}  "
              f"{flags}  {item['name']}")

    if not items:
        print("(каталог пуст)")
    dirs = sum(1 for i in items if i["type"] == "dir")
    print(f"Папок: {dirs}, файлов: {len(items) - dirs}")


def move_up(current_path: str) -> str:
    """
    Возвращает родительский каталог для указанного пути.

    Args:
        current_path: текущий путь.

    Returns:
        Путь к родительскому каталогу.
    """
    current = normalize_path(current_path)
    parent = normalize_path(utils.get_parent_path(current))

    if not parent or parent == current:
        return current

    valid, _ = utils.validate_windows_path(parent)
    if not valid:
        return current
    return parent


def move_down(current_path: str, target_dir: str) -> Tuple[bool, str]:
    """
    Переходит в указанный подкаталог (или по абсолютному пути).

    Args:
        current_path: текущий каталог.
        target_dir: имя подкаталога или абсолютный путь.

    Returns:
        (True, новый_путь) при успехе, (False, current_path) если
        каталог не найден, это файл или путь некорректен.
    """
    target = target_dir.strip().strip('"').strip()
    current = normalize_path(current_path)

    if _is_absolute(target):
        new_path = normalize_path(target)
    else:
        wanted = os.path.normcase(target)
        real_name = None
        for name in utils.safe_windows_listdir(current):
            if os.path.normcase(name) == wanted:
                real_name = name
                break
        if real_name is None:
            return False, current_path
        new_path = normalize_path(os.path.join(current, real_name))

    valid, _ = utils.validate_windows_path(new_path)
    if not valid or not os.path.isdir(new_path):
        return False, current_path
    return True, new_path


def get_windows_special_folders() -> Dict[str, str]:
    """
    Возвращает пути к специальным папкам Windows.

    Returns:
        Словарь «название -> путь». Возможные ключи: "Home",
        "AppData", "Temp", "Windows", "Program Files",
        "Program Files (x86)", "ProgramData", "Desktop", "Documents",
        "Downloads", "System32".
    """
    env = os.environ
    home = env.get("USERPROFILE", "")
    system_root = env.get("SystemRoot", "")

    candidates = {
        "Home": home,
        "AppData": env.get("APPDATA", ""),
        "Temp": env.get("TEMP", ""),
        "Windows": system_root,
        "Program Files": env.get("ProgramFiles", ""),
        "Program Files (x86)": env.get("ProgramFiles(x86)", ""),
        "ProgramData": env.get("ProgramData", ""),
    }
    if home:
        for name in ("Desktop", "Documents", "Downloads"):
            candidates[name] = os.path.join(home, name)
    if system_root:
        candidates["System32"] = os.path.join(system_root, "System32")

    return {name: path for name, path in candidates.items()
            if path and os.path.isdir(path)}
