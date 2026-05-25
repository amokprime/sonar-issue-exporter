#!/usr/bin/env python3
"""
Watch the system clipboard for SonarCloud issue URLs and automatically
export them using export_sonar_issue.py.

Shows a 6-dot spinning indicator (braille dots) beside each link while it
is downloading, replaced by a checkmark when the export finishes.

On startup, the current clipboard contents are noted so that a URL already
in the clipboard from a previous session is never re-fetched automatically.

Run once and leave it in the background. Press Ctrl+C to stop.
"""
import shutil
import subprocess
import sys
import time
import re
import threading
from pathlib import Path

try:
    import pyperclip
except ImportError:
    print("pyperclip not installed. Run: pip install pyperclip", file=sys.stderr)
    sys.exit(1)

# Prefer the installed CLI command; fall back to running the script directly
if shutil.which("sonar-export"):
    EXPORT_CMD = ["sonar-export"]
else:
    EXPORT_SCRIPT = str(Path(__file__).parent / "export_sonar_issue.py")
    EXPORT_CMD = [sys.executable, EXPORT_SCRIPT]

# Regex to quickly identify a SonarCloud issue URL
URL_PATTERN = re.compile(
    r"https://sonarcloud\.io/project/issues\?.*?open=[A-Za-z0-9_-]+"
)

# 6-dot braille spinner frames
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴"]
CHECKMARK = "✓"
# ANSI escape to clear from cursor to end of line (prevents ghost characters
# when a shorter line overwrites a longer one via \r)
_CLEAR_EOL = "\033[K"


class DownloadTracker:
    """Track active downloads and display spinner/checkmark status.

    Each download gets a single line in the terminal. While active the line
    shows a spinning braille indicator; once finished it is replaced by a
    checkmark and a newline is emitted so the line stays in the scrollback.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # Each entry: { "url_short": str, "process": Popen, "done": bool, "frame": int, "line_pos": int }
        self._entries = []
        self._display_thread = None
        self._stop_event = threading.Event()
        self._next_line_pos = 0  # tracks which visual line each download owns

    def add(self, url_short: str, process: subprocess.Popen):
        """Register a new download."""
        with self._lock:
            self._entries.append({
                "url_short": url_short,
                "process": process,
                "done": False,
                "frame": 0,
                "line_pos": self._next_line_pos,
            })
            self._next_line_pos += 1
        self._ensure_display_running()

    def _ensure_display_running(self):
        """Start the display-update thread if not already running."""
        if self._display_thread is not None and self._display_thread.is_alive():
            return
        self._stop_event.clear()
        self._display_thread = threading.Thread(target=self._display_loop, daemon=True)
        self._display_thread.start()

    def _display_loop(self):
        """Background thread: poll processes and update spinner display."""
        while not self._stop_event.is_set():
            with self._lock:
                for entry in self._entries:
                    if entry["done"]:
                        continue
                    ret = entry["process"].poll()
                    if ret is not None:
                        entry["done"] = True
                        self._print_completed(entry)
                    else:
                        entry["frame"] = (entry["frame"] + 1) % len(SPINNER_FRAMES)
                        self._print_spinner(entry)

            # Stop the display thread when all downloads are finished
            with self._lock:
                if all(e["done"] for e in self._entries):
                    self._stop_event.set()

            time.sleep(0.18)

    def _print_spinner(self, entry: dict):
        """Print (overwrite) the spinner line for an active download.

        Uses \r to return to the start of the line and ANSI \033[K to clear
        any leftover characters from a previously longer line.
        """
        spinner = SPINNER_FRAMES[entry["frame"]]
        url = entry["url_short"]
        sys.stdout.write(f"\r  {spinner} {url}{_CLEAR_EOL}")
        sys.stdout.flush()

    def _print_completed(self, entry: dict):
        """Print the checkmark line for a completed download."""
        url = entry["url_short"]
        sys.stdout.write(f"\r  {CHECKMARK} {url}{_CLEAR_EOL}\n")
        sys.stdout.flush()

    def wait_all(self):
        """Block until all tracked downloads are finished."""
        if self._display_thread is not None:
            self._display_thread.join()

    def cleanup_old(self, max_entries: int = 50):
        """Remove completed entries older than a threshold to keep the list tidy."""
        with self._lock:
            if len(self._entries) > max_entries:
                self._entries = [e for e in self._entries if not e["done"]]


def main():
    print("Watching clipboard for SonarCloud issue URLs...")
    print("Copy a link to trigger export. Press Ctrl+C to stop.\n")

    # Read the clipboard on startup so that whatever URL is already there
    # from a previous session is NOT re-fetched.
    try:
        last_url = pyperclip.paste().strip()
    except Exception:
        last_url = ""

    tracker = DownloadTracker()

    while True:
        try:
            current = pyperclip.paste().strip()
            if current != last_url and current.startswith("https://sonarcloud.io/") and URL_PATTERN.search(current):
                last_url = current
                url_short = current[:80] + ("..." if len(current) > 80 else "")
                proc = subprocess.Popen(
                    EXPORT_CMD + [current],
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                tracker.add(url_short, proc)
                tracker.cleanup_old()
            time.sleep(1)  # poll every second
        except KeyboardInterrupt:
            print("\nWaiting for active downloads to finish...")
            tracker.wait_all()
            print("Watcher stopped.")
            break
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
