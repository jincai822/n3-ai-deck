"""LCD key feedback: state images and transport-bound key-image writes.

P3 of the M4 design (sections 4.5-4.6 of
docs/superpowers/specs/2026-08-05-m4-ai-workflow-design.md): the renderer
turns one workflow state into a 72x72 JPEG the LCD can display, reusing the
icons.py centering pattern; the writer pushes one key image through the
G7-validated BAT frame pipeline as a per-call open/write/drain/close
transaction. The writer is exception-safe on the device path: any failure
returns False and it never raises.
"""

from __future__ import annotations

import contextlib
import io
from enum import StrEnum

from PIL import Image, ImageDraw, ImageFont

from streamdock_n3.hardware.contracts import AdapterCommand, Operation
from streamdock_n3.hardware.vendor_backend import VendorHidTransport, _frames_for_command

KEY_IMAGE_SIZE = 72
_STATE_FONT_SIZE = 16
_TEXT_FONT_SIZE = 11
_TEXT_COLOR = (255, 255, 255)
_JPEG_QUALITY = 95


class FeedbackState(StrEnum):
    """LCD feedback state for one dispatched action."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"


STATE_COLORS: dict[FeedbackState, tuple[int, int, int]] = {
    FeedbackState.RUNNING: (240, 200, 0),
    FeedbackState.SUCCESS: (24, 132, 82),
    FeedbackState.FAILURE: (181, 40, 40),
    FeedbackState.TIMEOUT: (230, 126, 34),
}


def render_state_image(state: FeedbackState, text: str | None = None) -> bytes:
    """Render one 72x72 state JPEG: the state word large, optional text line below."""
    if not isinstance(state, FeedbackState):
        raise TypeError("state must be a FeedbackState")
    if text is not None and not isinstance(text, str):
        raise TypeError("text must be a string or None")
    image = Image.new("RGB", (KEY_IMAGE_SIZE, KEY_IMAGE_SIZE), STATE_COLORS[state])
    draw = ImageDraw.Draw(image)
    state_font = ImageFont.load_default(size=_STATE_FONT_SIZE)
    lines = [state.value.upper()]
    fonts = [state_font]
    if text:
        text_line = text.strip().splitlines()[0]
        text_font = ImageFont.load_default(size=_TEXT_FONT_SIZE)
        text_line = _truncate_to_fit(draw, text_line, text_font, KEY_IMAGE_SIZE - 8)
        lines.append(text_line)
        fonts.append(text_font)
    line_boxes = [
        draw.textbbox((0, 0), line, font=font) for line, font in zip(lines, fonts, strict=True)
    ]
    total_height = sum(box[3] - box[1] for box in line_boxes) + 2 * (len(line_boxes) - 1)
    y = (image.height - total_height) // 2
    for line, box, font in zip(lines, line_boxes, fonts, strict=True):
        width = box[2] - box[0]
        x = (image.width - width) // 2
        draw.text((x, y), line, fill=_TEXT_COLOR, font=font)
        y += box[3] - box[1] + 2
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=_JPEG_QUALITY)
    return buffer.getvalue()


def write_key_image(
    node: str,
    key: int,
    jpeg: bytes,
    transport: VendorHidTransport,
) -> bool:
    """Write one key image via the BAT frame pipeline; False on any failure."""
    if not isinstance(node, str) or not node:
        raise ValueError("node must be a non-empty path")
    if not isinstance(jpeg, bytes) or not jpeg:
        raise ValueError("jpeg must be non-empty bytes")
    try:
        command = AdapterCommand(Operation.SET_KEY_IMAGE, key=key, image=jpeg)
        frames = _frames_for_command(command)
        fd = transport.open_read_write(node)
    except Exception:
        return False
    try:
        for frame in frames:
            transport.write(fd, frame)
            transport.drain_acks(fd)
    except Exception:
        return False
    finally:
        with contextlib.suppress(Exception):
            transport.close(fd)
    return True


def _truncate_to_fit(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    max_width: int,
) -> str:
    """Truncate one line with an ellipsis so it fits the LCD key width."""
    if draw.textlength(text, font=font) <= max_width:
        return text
    ellipsis = "\u2026"
    shortened = text
    while shortened and draw.textlength(shortened + ellipsis, font=font) > max_width:
        shortened = shortened[:-1]
    return shortened + ellipsis if shortened else ""
