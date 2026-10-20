"""Adattatore Claude: ignora gli eventi Copilot che importano .claude/settings.json.

Copilot documenta timestamp nel proprio payload (anche nel formato compatibile
PascalCase); Claude documenta transcript_path e nessun timestamp comune.
Non si cambia il motore Claude personalizzato: lo si invoca solo nel suo runtime.
"""
import json
import os
import subprocess
import sys
from pathlib import Path


def main():
    raw = sys.stdin.buffer.read()
    try:
        event = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(event, dict):
            raise ValueError("evento non valido")
        if "sessionId" in event or ("timestamp" in event and "permission_mode" not in event):
            print("{}")
            return 0
        name = event.get("hook_event_name")
        script = {"SessionStart": "modello_hook.py", "UserPromptSubmit": "modello_hook.py",
                  "PostToolUse": "learn_hook.py", "Stop": "learn_hook.py"}.get(name)
        if not script:
            print("{}")
            return 0
        run = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / script)],
                             input=raw, capture_output=True, timeout=175,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        sys.stdout.buffer.write(run.stdout)
        sys.stderr.buffer.write(run.stderr)
        return run.returncode
    except Exception as error:
        print(json.dumps({"systemMessage": "Teseo Claude: " + str(error)[:200]}))
        return 0


if __name__ == "__main__":
    sys.exit(main())
