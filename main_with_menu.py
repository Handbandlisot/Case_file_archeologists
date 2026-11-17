import os
import platform
import sys
from typing import NoReturn

import utils  # own module — basic Windows utilities
import navigation  # navigation engineer module
import analysis  # data analyst module
import search  # search expert module


def check_windows_environment() -> bool:
    """Check that the program is running on Windows.

    Uses utils.is_windows_os(). If the OS is not Windows, an error
    message is printed and the program is terminated.

    Returns:
        True when running on Windows.
    """
    if utils.is_windows_os():
        return True
    print("Error: File Archaeologist requires Microsoft Windows.")
    print("This tool explores the Windows file system and cannot "
          "run on the current platform.")
    sys.exit(1)


def display_windows_banner() -> None:
    """Display the startup banner with Windows environment info."""
    drive = navigation.get_current_drive()
    print("=" * 60)
    print("  FILE ARCHAEOLOGIST - Windows File System Navigator")
    print("  Digital archaeology expedition toolkit")
    print("=" * 60)
    print(f"  Current drive : {drive}")
    print(f"  OS            : {platform.platform()}")
    print(f"  Python        : {platform.python_version()}")
    print(f"  Workspace     : {os.getcwd()}")
    print("=" * 60)


def display_main_menu(current_path: str) -> None:
    """Display the main menu with available commands and drives.

    Args:
        current_path: the directory the user is currently in.
    """
    drives = navigation.list_available_drives()
    drives_line = "  ".join(drives) if drives else "(no drives detected)"
    print()
    print(f"Current path: {current_path}")
    print(f"Drives: {drives_line}")
    print("-" * 60)
    print("1. List directory contents           [navigation]")
    print("2. Directory statistics              [analysis]")
    print("3. Search files                      [search]")
    print("4. File attributes statistics        [analysis]")
    print("5. Go to parent directory            [navigation]")
    print("6. Go to folder / switch drive       [navigation]")
    print("0. Exit")
    print("-" * 60)


def handle_windows_navigation(command: str, current_path: str) -> str:
    """Handle navigation commands 1, 5 and 6.

    Uses navigation.list_directory(), navigation.move_up(),
    navigation.move_down() and navigation.list_available_drives()
    for drive switching.

    Args:
        command: the selected menu command.
        current_path: the current directory.

    Returns:
        The (possibly updated) current path.
    """
    match command:
        case "1":
            success, items = navigation.list_directory(current_path)
            if success:
                navigation.format_directory_output(items, current_path)
            else:
                print(f"Cannot read directory: {current_path}")
            return current_path

        case "5":
            new_path = navigation.move_up(current_path)
            if new_path != current_path:
                print(f"Moved up to: {new_path}")
            else:
                print("Already at the drive root.")
            return new_path

        case "6":
            target = input("Enter folder name, full path, "
                           "or drive letter (e.g. D:): ").strip()
            if not target:
                return current_path

            # Drive switching: "D", "d:", "D:\\"
            drive_token = target.rstrip("\\/").upper()
            if len(drive_token) == 1 and drive_token.isalpha():
                drive_token += ":"
            if drive_token in navigation.list_available_drives():
                print(f"Switched to drive {drive_token}\\")
                return drive_token + "\\"

            success, new_path = navigation.move_down(current_path, target)
            if success:
                print(f"Current path: {new_path}")
                return new_path
            print(f"No such folder: {target}")
            return current_path

        case _:
            return current_path


def handle_windows_analysis(command: str, current_path: str) -> None:
    """Handle analysis commands 2 and 4.

    Uses analysis.show_windows_directory_stats() and
    analysis.get_windows_file_attributes_stats().

    Args:
        command: the selected menu command.
        current_path: the current directory.
    """
    match command:
        case "2":
            analysis.show_windows_directory_stats(current_path)

        case "4":
            stats = analysis.get_windows_file_attributes_stats(current_path)
            print()
            print(f"Attribute statistics for: {current_path}")
            print(f"  Hidden files    : {stats['hidden']}")
            print(f"  System files    : {stats['system']}")
            print(f"  Read-only files : {stats['readonly']}")

        case _:
            print(f"Unknown analysis command: {command}")


def handle_windows_search(command: str, current_path: str) -> None:
    """Handle search command 3.

    Runs the interactive search menu until the user leaves it
    (search.search_menu_handler() returns False).

    Args:
        command: the selected menu command.
        current_path: the current directory.
    """
    while search.search_menu_handler(current_path):
        pass


def run_windows_command(command: str, current_path: str) -> str:
    """Route a user command to the proper module using match/case.

    Routing map (per the technical specification):
    * commands 1, 5, 6 - navigation module;
    * commands 2, 4 - analysis module;
    * command 3 - search module.

    Args:
        command: the entered command.
        current_path: the current directory.

    Returns:
        The (possibly updated) current path.
    """
    match command:
        case "1" | "5" | "6":
            return handle_windows_navigation(command, current_path)
        case "2" | "4":
            handle_windows_analysis(command, current_path)
        case "3":
            handle_windows_search(command, current_path)
        case "0":
            pass  # exit is handled by the main loop
        case _:
            print(f"Unknown command: {command!r}. Use 0-6.")
    return current_path


def main() -> NoReturn:
    """Run the File Archaeologist main loop.

    1. Check the Windows environment.
    2. Show the startup banner.
    3. Run the command loop over all project modules.
    4. Handle errors of the top level and terminate cleanly.
    """
    check_windows_environment()
    display_windows_banner()
    current_path = os.getcwd()

    while True:
        display_main_menu(current_path)
        try:
            command = input("Enter command (0-6): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession terminated by user. Goodbye, archaeologist!")
            break

        if command == "0":
            print("Session closed. Goodbye, archaeologist!")
            break

        try:
            current_path = run_windows_command(command, current_path)
        except Exception as error:  # top-level error handling
            print(f"Unexpected error: {error}")

    sys.exit(0)


if __name__ == "__main__":
    main()
