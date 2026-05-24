#!/usr/bin/env python3
"""
Watch the system clipboard for SonarCloud issue URLs and automatically
export them using export_sonar_issue.py.
Run once and leave it in the background. Press Ctrl+C to stop.
"""
import shutil
import subprocess
import sys
import time
import re

try:
    import pyperclip
except ImportError:
    print("pyperclip not installed. Run: pip install pyperclip", file=sys.stderr)
    sys.exit(1)

# Prefer the installed CLI command; fall back to running the script directly
if shutil.which("sonar-export"):
    EXPORT_CMD = ["sonar-export"]
else:
    EXPORT_SCRIPT = str(
        __import__("pathlib").Path(__file__).parent / "export_sonar_issue.py"
    )
    EXPORT_CMD = [sys.executable, EXPORT_SCRIPT]

# Regex to quickly identify a SonarCloud issue URL
URL_PATTERN = re.compile(
    r"https://sonarcloud\.io/project/issues\?.*?open=[A-Za-z0-9_-]+"
)


def main():
    print("Watching clipboard for SonarCloud issue URLs...")
    print("Copy a link to trigger export. Press Ctrl+C to stop.\n")
    last_url = ""

    while True:
        try:
            current = pyperclip.paste().strip()
            if current != last_url and URL_PATTERN.search(current):
                last_url = current
                print(f"Exporting: {current[:80]}...")
                subprocess.Popen(
                    EXPORT_CMD + [current],
                    creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
                )
            time.sleep(1)  # poll every second
        except KeyboardInterrupt:
            print("\nWatcher stopped.")
            break
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            time.sleep(5)


if __name__ == "__main__":
    main()
