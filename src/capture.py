"""Screen capture module using mss + PIL."""

from __future__ import annotations

import io
from typing import Optional

import mss
from PIL import Image

MAX_DIM = 768


def get_primary_monitor() -> dict:
    """Return the primary monitor bounds from mss."""
    with mss.mss() as sct:
        # monitors[0] is the "all monitors" virtual screen; [1] is the primary
        return dict(sct.monitors[1])


def capture_screen(region: Optional[dict] = None) -> bytes:
    """Capture screen (or region), resize to fit 768x768, return JPEG bytes.

    Args:
        region: Optional dict with keys top, left, width, height.
                If None, captures the primary monitor.

    Returns:
        JPEG-encoded bytes of the captured frame.
    """
    with mss.mss() as sct:
        monitor = region or sct.monitors[1]
        screenshot = sct.grab(monitor)

    img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)

    # Check for all-black frame (macOS Screen Recording permission issue)
    if img.getextrema() == ((0, 0), (0, 0), (0, 0)):
        print(
            "WARNING: Captured frame is all-black. "
            "Grant Screen Recording permission in System Settings > Privacy & Security."
        )

    # Resize to fit within MAX_DIM x MAX_DIM, preserving aspect ratio
    img.thumbnail((MAX_DIM, MAX_DIM), Image.LANCZOS)

    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=80)
    return buf.getvalue()


if __name__ == "__main__":
    # Quick standalone test: save a frame to disk
    frame = capture_screen()
    with open("test_capture.jpg", "wb") as f:
        f.write(frame)
    print(f"Saved test_capture.jpg ({len(frame)} bytes)")
