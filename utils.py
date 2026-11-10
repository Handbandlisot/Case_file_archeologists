"""utils.py — basic utilities for working with the Windows file system.

Project: "File Archaeologist", module 1 (Stage 1).
Developer: System Architect (Team Lead).
Dependencies: none — this module does not rely on other team modules.

Platform policy:
* The core logic follows Windows rules: path separator "\\",
  forbidden characters / : * ? " < > |, MAX_PATH = 260 limit,
  file attributes (FILE_ATTRIBUTE_HIDDEN).
* Fallback behaviors are provided for development and testing
  on non-Windows systems, as described in the function docstrings.
"""

import os
import platform
import ctypes
import ntpath
from pathlib import Path
from typing import Union, List, Tuple

PathString = Union[str, Path]

# Maximum length of a regular Windows path (MAX_PATH)
MAX_PATH_LENGTH = 260

# Maximum length of an extended Windows path ("\\?\" prefix)
MAX_EXTENDED_PATH_LENGTH = 32767

# Extended-length path prefix ("\\?\")
EXTENDED_PATH_PREFIX = "\\\\?\\"

# Characters forbidden in Windows file and folder names
FORBIDDEN_CHARS = '/:*?"<>|'

# Hidden file attribute FILE_ATTRIBUTE_HIDDEN (WinAPI value)
FILE_ATTRIBUTE_HIDDEN = 0x2

# Invalid result of GetFileAttributesW (INVALID_FILE_ATTRIBUTES)
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


def is_windows_os() -> bool:
    """Check whether the program is running on Windows.

    Returns:
        True if the operating system is Windows, False otherwise.
    """
    return platform.system() == "Windows"


def validate_windows_path(path: PathString,
                          check_exists: bool = True) -> Tuple[bool, str]:
    """Validate a Windows path.

    The following are checked:
    * forbidden characters in names: / : * ? " < > |
      (the drive letter "C:" and the extended prefix "\\?\"
      are allowed exceptions);
    * path length: at most 260 characters for regular paths
      (up to 32767 for extended paths "\\?\\...");
    * existence of the path on disk (when check_exists=True).

    Args:
        path: the path to validate (str or pathlib.Path).
        check_exists: whether to check that the path actually
            exists. Defaults to True. On non-Windows systems the
            existence check uses the host file system, so Windows
            paths will be reported as non-existent there.

    Returns:
        (True, "") if the path is valid;
        (False, "error message") otherwise.
    """
    if isinstance(path, Path):
        path_str = str(path)
    elif isinstance(path, str):
        path_str = path
    else:
        return False, f"Invalid path type: {type(path).__name__}"

    if not path_str:
        return False, "Path must not be empty"

    is_extended = path_str.startswith(EXTENDED_PATH_PREFIX)

    if not is_extended and len(path_str) > MAX_PATH_LENGTH:
        return False, (f"Path length exceeded: "
                       f"{len(path_str)} > {MAX_PATH_LENGTH} characters")
    if len(path_str) > MAX_EXTENDED_PATH_LENGTH:
        return False, (f"Extended path length exceeded: "
                       f"{len(path_str)} > {MAX_EXTENDED_PATH_LENGTH} "
                       f"characters")

    # String used for character checks: without the "\\?\" prefix;
    # a UNC path is normalized to the regular "\\server\share" form
    check_str = path_str
    if is_extended:
        body = path_str[len(EXTENDED_PATH_PREFIX):]
        if body[:4].upper() == "UNC\\":
            check_str = "\\\\" + body[4:]
        else:
            check_str = body

    # Forbidden characters are checked in every name segment.
    # The first segment may carry a drive letter ("C:", "C:folder");
    # UNC segments ("\\server\share\...") are checked in full.
    for index, segment in enumerate(check_str.split("\\")):
        name = segment
        if (index == 0 and len(segment) >= 2 and segment[1] == ":"
                and segment[0].isalpha()):
            # Drive letter "C:" — check only the part after ":"
            name = segment[2:]
        if not name:
            continue
        for char in FORBIDDEN_CHARS:
            if char in name:
                message = (f"Forbidden character '{char}' "
                           f"in name '{segment}'")
                if char == "/":
                    message += " (Windows path separator is '\\')"
                return False, message

    if check_exists and not os.path.exists(path_str):
        return False, f"Path does not exist: {path_str}"

    return True, ""


def format_size(size_bytes: int) -> str:
    """Format a file size in a human-readable Windows-style form.

    Windows units are used: bytes, KB, MB, GB, TB
    (division by 1024, but labels are KB/MB/GB without the "Ki" prefix).

    Examples: 1024 -> "1.0 KB", 1500000 -> "1.4 MB", 512 -> "512 bytes".

    Args:
        size_bytes: file size in bytes (non-negative integer).

    Returns:
        A string with the size and the unit of measurement.

    Raises:
        ValueError: if size_bytes is negative.
    """
    if size_bytes < 0:
        raise ValueError("File size must not be negative")

    units = ["bytes", "KB", "MB", "GB", "TB"]
    value = float(size_bytes)
    unit_index = 0

    while value >= 1024.0 and unit_index < len(units) - 1:
        value /= 1024.0
        unit_index += 1

    if unit_index == 0:
        # Bytes are printed as an integer: 0 bytes, 1 byte, 512 bytes
        if size_bytes == 1:
            return "1 byte"
        return f"{size_bytes} bytes"

    rounded = round(value, 1)
    # Rounding up to 1024.0 KB and the like moves to the next unit
    if rounded >= 1024.0 and unit_index < len(units) - 1:
        rounded /= 1024.0
        unit_index += 1

    return f"{rounded:.1f} {units[unit_index]}"


def get_parent_path(path: PathString) -> str:
    """Get the parent directory with Windows path semantics.

    Peculiarities (os.path/ntpath semantics on Windows):
    * "C:\\" -> "C:\\" (drive root is its own parent);
    * "C:\\Users" -> "C:\\";
    * "C:\\Users\\Admin" -> "C:\\Users";
    * "C:folder" -> "C:\\" (drive-relative path);
    * "\\\\server\\share\\dir" -> "\\\\server\\share" (UNC);
    * "folder" -> "" (relative path without a parent).

    Args:
        path: the path (str or pathlib.Path).

    Returns:
        The parent directory path in Windows format.
    """
    path_str = str(path) if isinstance(path, Path) else path
    parent = ntpath.dirname(path_str)

    if parent.endswith(":"):
        # "C:" (path relative to the drive's current dir) -> "C:\\"
        parent += "\\"
    elif not parent:
        drive, _rest = ntpath.splitdrive(path_str)
        if drive and not drive.startswith("\\\\"):
            # "C:" -> "C:\\" (drive root)
            parent = drive + "\\"
        elif drive:
            # UNC root "\\server\share" stays as is
            parent = drive
    elif (parent.startswith("\\\\")
          and not parent.startswith(EXTENDED_PATH_PREFIX)
          and parent.endswith("\\")):
        # UNC root "\\server\share\\" -> "\\server\share"
        stripped = parent.rstrip("\\")
        if stripped.startswith("\\\\"):
            parent = stripped

    return parent


def safe_windows_listdir(path: PathString) -> List[str]:
    """Safely list the contents of a Windows directory.

    Args:
        path: path to the directory (str or pathlib.Path).

    Returns:
        A list of directory item names, or an empty list on error:
        PermissionError (access denied),
        FileNotFoundError (directory not found),
        OSError (long paths and other OS errors).
    """
    try:
        return os.listdir(os.fspath(path))
    except OSError:
        # PermissionError, FileNotFoundError and other OSError cases
        # return an empty list so the navigator keeps working
        return []


def is_hidden_windows_file(path: PathString) -> bool:
    """Check whether a file is hidden on Windows.

    On Windows the FILE_ATTRIBUTE_HIDDEN attribute is checked:
    first via ctypes (GetFileAttributesW), falling back to
    os.stat (st_file_attributes) on failure.

    Fallback for non-Windows systems and cases where attributes
    are unavailable: a file whose name starts with a dot is
    considered hidden (POSIX convention).

    Args:
        path: path to the file or directory (str or pathlib.Path).

    Returns:
        True if the file is hidden, False otherwise.
    """
    path_str = str(path) if isinstance(path, Path) else path

    if is_windows_os():
        # Primary method: GetFileAttributesW via ctypes
        try:
            get_attrs = ctypes.windll.kernel32.GetFileAttributesW
            get_attrs.argtypes = [ctypes.c_wchar_p]
            get_attrs.restype = ctypes.c_uint32
            attrs = get_attrs(path_str)
            if attrs != INVALID_FILE_ATTRIBUTES:
                return bool(attrs & FILE_ATTRIBUTE_HIDDEN)
        except (AttributeError, OSError, ValueError):
            pass  # ctypes is unavailable or the call failed

        # Fallback method: attributes via os.stat
        try:
            attrs = os.stat(path_str).st_file_attributes
            return bool(attrs & FILE_ATTRIBUTE_HIDDEN)
        except (OSError, AttributeError):
            return False

    # Fallback for non-Windows systems: name starts with a dot
    trimmed = path_str.rstrip("\\/")
    return ntpath.basename(trimmed).startswith(".")
