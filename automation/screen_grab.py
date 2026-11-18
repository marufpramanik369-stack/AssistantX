"""automation/screen_grab.py - standalone screenshot helper (run as a script, not imported).

Usage:  python screen_grab.py MODE [DELAY_SECONDS]
MODE = full | left | right | top | bottom | center | area
Prints the saved file path on success, CANCELLED if the user cancelled the area pick,
or  ERROR: ...  (exit code 1) on failure.  Needs Pillow (pip install pillow).
"""
import ctypes
import sys
import time
from datetime import datetime
from pathlib import Path


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _folder() -> Path:
    d = Path.home() / "Pictures" / "AssistantX Screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def crop_box(mode, w, h):
    if mode == "left":
        return (0, 0, w // 2, h)
    if mode == "right":
        return (w // 2, 0, w, h)
    if mode == "top":
        return (0, 0, w, h // 2)
    if mode == "bottom":
        return (0, h // 2, w, h)
    if mode == "center":
        return (w // 4, h // 4, w * 3 // 4, h * 3 // 4)
    return (0, 0, w, h)


def _pick_area(img):
    """Show the frozen screen full-screen; the user drags a rectangle. Esc cancels."""
    import tkinter as tk
    from PIL import ImageTk

    root = tk.Tk()
    root.attributes("-fullscreen", True)
    root.attributes("-topmost", True)
    root.config(cursor="cross")
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    w, h = img.size
    shown = img.resize((sw, sh)) if (sw, sh) != (w, h) else img
    photo = ImageTk.PhotoImage(shown)
    canvas = tk.Canvas(root, width=sw, height=sh, highlightthickness=0, bg="black")
    canvas.pack(fill="both", expand=True)
    canvas.create_image(0, 0, image=photo, anchor="nw")
    canvas.create_text(sw // 2, 36, text="Drag to select the area  -  Esc to cancel",
                       fill="yellow", font=("Segoe UI", 20, "bold"))
    state = {"x": 0, "y": 0, "rect": None, "box": None}

    def down(e):
        state["x"], state["y"] = e.x, e.y
        state["rect"] = canvas.create_rectangle(e.x, e.y, e.x, e.y, outline="red", width=3)

    def move(e):
        if state["rect"] is not None:
            canvas.coords(state["rect"], state["x"], state["y"], e.x, e.y)

    def up(e):
        x1, x2 = sorted((state["x"], e.x))
        y1, y2 = sorted((state["y"], e.y))
        if x2 - x1 >= 5 and y2 - y1 >= 5:
            state["box"] = (x1, y1, x2, y2)
        root.destroy()

    canvas.bind("<ButtonPress-1>", down)
    canvas.bind("<B1-Motion>", move)
    canvas.bind("<ButtonRelease-1>", up)
    root.bind("<Escape>", lambda e: root.destroy())
    root.focus_force()
    root.mainloop()
    box = state["box"]
    if box is None:
        return None
    sx, sy = w / sw, h / sh
    return (int(box[0] * sx), int(box[1] * sy), int(box[2] * sx), int(box[3] * sy))


def main(argv) -> int:
    mode = argv[1] if len(argv) > 1 else "full"
    try:
        delay = float(argv[2]) if len(argv) > 2 else 0.0
    except ValueError:
        delay = 0.0
    _dpi_aware()
    try:
        from PIL import ImageGrab
    except ImportError:
        print("ERROR: Pillow is missing (run: python -m pip install pillow)")
        return 1
    try:
        time.sleep(max(0.3, delay))
        img = ImageGrab.grab()
        if mode == "area":
            box = _pick_area(img)
            if box is None:
                print("CANCELLED")
                return 0
        else:
            box = crop_box(mode, *img.size)
        out = img.crop(box)
        path = _folder() / f"{mode}_{datetime.now():%Y%m%d_%H%M%S}.png"
        out.save(path)
        print(path)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc.__class__.__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
