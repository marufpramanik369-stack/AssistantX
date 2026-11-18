import py_compile
import shutil
import sys
from pathlib import Path

# Put this file in C:\AssistantX or C:\AssistantX\voice, then run it with python.
HERE = Path(__file__).resolve().parent
if HERE.name.lower() == "voice":
    TARGET = HERE / "recognizer.py"
else:
    TARGET = HERE / "voice" / "recognizer.py"
BACKUP = Path(str(TARGET) + ".bak2")

ANCHOR = "            detected_locale = _detect_spoken_locale(audio)\n"

NEW = (
    "            _clip_seconds = len(audio.frame_data) / float(\n"
    "                audio.sample_rate * audio.sample_width\n"
    "            )\n"
    "            print(f\"[CLIP] {_clip_seconds:.2f}s\")\n"
    "            if _clip_seconds < 0.6:\n"
    "                print(\"[CLIP] too short, ignored\")\n"
    "                raise RecognitionTimeoutError(\"Clip too short.\")\n"
    "\n"
)

if not TARGET.exists():
    print("ERROR: recognizer.py not found at:", TARGET)
    sys.exit(1)

src = TARGET.read_text(encoding="utf-8")

if "[CLIP]" in src:
    print("Already patched. Nothing to do.")
    sys.exit(0)

if src.count(ANCHOR) != 1:
    print("ERROR: expected line not found exactly once. File not changed.")
    print("anchor count:", src.count(ANCHOR))
    sys.exit(1)

shutil.copy(TARGET, BACKUP)

src = src.replace(ANCHOR, NEW + ANCHOR, 1)
TARGET.write_text(src, encoding="utf-8")

try:
    py_compile.compile(str(TARGET), doraise=True)
except py_compile.PyCompileError as exc:
    shutil.copy(BACKUP, TARGET)
    print("ERROR: syntax problem, original restored.")
    print(exc)
    sys.exit(1)

print("PATCHED OK:", TARGET)
print("Backup saved as:", BACKUP)

