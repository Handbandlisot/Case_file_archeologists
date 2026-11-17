import builtins
import os
import platform
import queue
import sys
import threading
from typing import NoReturn

try:
    import tkinter as tk
except ImportError:  # keep the module importable on headless systems
    tk = None

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
            pass  # exit is handled by the GUI / main loop
        case _:
            print(f"Unknown command: {command!r}. Use 0-6.")
    return current_path


# =====================================================================
# GUI layer. Everything below belongs to the System Architect and only
# wraps the functions above: the other roles' modules are not changed.
# print() and input() of the module functions are redirected into the
# window through a queue, so their code stays untouched.
# =====================================================================


class _QueueWriter:
    """File-like stdout/stderr replacement that feeds a queue.

    The GUI thread drains the queue and appends the text to the
    output console, so worker threads never touch widgets directly.
    """

    def __init__(self, events: "queue.Queue") -> None:
        self._events = events

    def write(self, text: str) -> int:
        if text:
            self._events.put(("text", text))
        return len(text)

    def flush(self) -> None:
        pass

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return False


class _InputBridge:
    """Replacement for input() that asks the GUI for an answer.

    The worker thread blocks until the user types the answer into
    the input line of the window and presses Enter.
    """

    def __init__(self, events: "queue.Queue",
                 answers: "queue.Queue") -> None:
        self._events = events
        self._answers = answers

    def __call__(self, prompt: str = "") -> str:
        if prompt:
            self._events.put(("text", prompt))
        self._events.put(("prompt", prompt))
        return str(self._answers.get())


class _ArchaeologistGUI:
    """The application window: console output, buttons and input line.

    Commands run in a daemon worker thread; all widget updates happen
    on the GUI thread via the event queue (polled with after()).
    """

    POLL_MS = 50

    def __init__(self, root: "tk.Tk") -> None:
        self.root = root
        self.current_path = os.getcwd()
        self.events: "queue.Queue" = queue.Queue()
        self.answers: "queue.Queue" = queue.Queue()
        self._busy = False
        self._awaiting_input = False

        root.title("File Archaeologist - Windows File System Navigator")
        root.geometry("980x640")
        root.minsize(780, 500)

        # Top line: the current path
        top = tk.Frame(root)
        top.pack(fill=tk.X, padx=10, pady=(10, 0))
        tk.Label(top, text="Current path:").pack(side=tk.LEFT)
        self.path_var = tk.StringVar(value=self.current_path)
        tk.Label(top, textvariable=self.path_var, anchor="w",
                 font=("Consolas", 10, "bold")).pack(side=tk.LEFT, padx=8)

        # Output console
        frame = tk.Frame(root)
        frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)
        self.output = tk.Text(frame, wrap=tk.WORD, state=tk.DISABLED,
                              font=("Consolas", 10),
                              bg="#101418", fg="#d8dee9")
        scroll = tk.Scrollbar(frame, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Command buttons (hybrid control: buttons + input line)
        buttons = tk.Frame(root)
        buttons.pack(fill=tk.X, padx=10)
        self._buttons = []
        for label, command in (
                ("1 List dir", "1"), ("2 Statistics", "2"),
                ("3 Search", "3"), ("4 Attributes", "4"),
                ("5 Up", "5"), ("6 Go to...", "6"), ("0 Exit", "0")):
            button = tk.Button(buttons, text=label, width=12,
                               command=lambda c=command: self._on_button(c))
            button.pack(side=tk.LEFT, padx=3, pady=3)
            self._buttons.append(button)

        # Input line (free commands and answers to input() prompts)
        line = tk.Frame(root)
        line.pack(fill=tk.X, padx=10, pady=(4, 0))
        self.prompt_var = tk.StringVar(value="Command:")
        tk.Label(line, textvariable=self.prompt_var, width=10,
                 anchor="w").pack(side=tk.LEFT)
        self.entry = tk.Entry(line, font=("Consolas", 10))
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))
        self.entry.bind("<Return>", self._on_submit)
        tk.Button(line, text="Send", width=10,
                  command=self._on_submit).pack(side=tk.LEFT)

        # Status bar
        self.status_var = tk.StringVar(value="Ready")
        tk.Label(root, textvariable=self.status_var, anchor="w",
                 relief=tk.SUNKEN).pack(fill=tk.X, padx=10, pady=(6, 10))

        root.protocol("WM_DELETE_WINDOW", self.close)
        self._saved_stdout = None
        self._saved_stderr = None
        self._saved_input = None
        self._install_streams()
        self._greet()
        self.root.after(self.POLL_MS, self._poll)
        self.entry.focus_set()

    # ---- stream redirection (keeps other modules untouched) ----

    def _install_streams(self) -> None:
        self._saved_stdout = sys.stdout
        self._saved_stderr = sys.stderr
        self._saved_input = builtins.input
        writer = _QueueWriter(self.events)
        sys.stdout = writer
        sys.stderr = writer
        builtins.input = _InputBridge(self.events, self.answers)

    def restore_streams(self) -> None:
        if self._saved_stdout is not None:
            sys.stdout = self._saved_stdout
            sys.stderr = self._saved_stderr
            builtins.input = self._saved_input
            self._saved_stdout = None

    # ---- output helpers ----

    def _append_output(self, text: str) -> None:
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, text)
        self.output.see(tk.END)
        self.output.configure(state=tk.DISABLED)

    def _greet(self) -> None:
        display_windows_banner()
        display_main_menu(self.current_path)

    # ---- commands ----

    def _on_button(self, command: str) -> None:
        if command == "0":
            self.close()
            return
        self._start_worker(command)

    def _on_submit(self, _event=None) -> None:
        text = self.entry.get().strip()
        self.entry.delete(0, tk.END)
        if self._awaiting_input:
            # The worker is blocked inside input() — this is the answer
            self._append_output(text + "\n")
            self.answers.put(text)
            return
        if not text or self._busy:
            return
        if text == "0":
            self.close()
            return
        self._start_worker(text)

    def _start_worker(self, command: str) -> None:
        if self._busy:
            return
        self._busy = True
        for button in self._buttons:
            button.configure(state=tk.DISABLED)
        self.status_var.set(f"Running command {command!r}...")
        self._append_output(f"\n>>> {command}\n")
        threading.Thread(target=self._worker, args=(command,),
                         daemon=True).start()

    def _worker(self, command: str) -> None:
        try:
            self.current_path = run_windows_command(command,
                                                    self.current_path)
        except Exception as error:  # top-level error handling
            print(f"Unexpected error: {error}")
        self.events.put(("path", self.current_path))
        display_main_menu(self.current_path)
        self.events.put(("idle", None))

    # ---- event pump ----

    def _poll(self) -> None:
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "text":
                    self._append_output(payload)
                elif kind == "prompt":
                    self._awaiting_input = True
                    self.prompt_var.set("Input:")
                    self.status_var.set(
                        f"Waiting for input: {payload or 'value'}")
                elif kind == "path":
                    self.path_var.set(payload)
                elif kind == "idle":
                    self._busy = False
                    self._awaiting_input = False
                    self.prompt_var.set("Command:")
                    self.status_var.set("Ready")
                    for button in self._buttons:
                        button.configure(state=tk.NORMAL)
                    self.entry.focus_set()
        except queue.Empty:
            pass
        self.root.after(self.POLL_MS, self._poll)

    # ---- shutdown ----

    def close(self) -> None:
        self.restore_streams()
        self.root.destroy()


def main() -> NoReturn:
    """Run the File Archaeologist GUI application.

    1. Check the Windows environment.
    2. Build the window and redirect print()/input() of all modules
       into it (the modules themselves are not modified).
    3. Run the Tk main loop as the top-level command cycle with
       top-level error handling.
    4. Restore the streams and terminate cleanly.
    """
    check_windows_environment()
    if tk is None:
        print("Error: tkinter is not available in this Python build.")
        sys.exit(1)

    root = tk.Tk()
    app = _ArchaeologistGUI(root)
    try:
        root.mainloop()
    finally:
        app.restore_streams()
    sys.exit(0)


if __name__ == "__main__":
    main()
