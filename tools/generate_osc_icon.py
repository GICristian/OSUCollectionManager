"""Regenerează ``assets/OSC.ico`` din ``logo.png`` (rulare: ``python tools/generate_osc_icon.py``)."""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    src = root / "logo.png"
    if not src.is_file():
        raise SystemExit(f"Lipsește {src}")
    out_dir = root / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / "OSC.ico"
    im = Image.open(src).convert("RGBA")
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(dst, format="ICO", sizes=sizes)
    print(f"Scris {dst} ({dst.stat().st_size} octeți)")


if __name__ == "__main__":
    main()
