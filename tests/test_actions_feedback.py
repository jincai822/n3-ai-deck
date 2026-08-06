from __future__ import annotations

import io

import pytest
from PIL import Image

from streamdock_n3.actions.feedback import (
    KEY_IMAGE_SIZE,
    STATE_COLORS,
    FeedbackState,
    render_state_image,
    write_key_image,
)
from streamdock_n3.hardware.contracts import AdapterCommand, Operation
from streamdock_n3.hardware.vendor_backend import _frames_for_command

_NODE = "vendor-node"

_COLOR_TOLERANCE = 30


def _decode(jpeg: bytes) -> Image.Image:
    return Image.open(io.BytesIO(jpeg)).convert("RGB")


def _pixel(jpeg: bytes, x: int, y: int) -> tuple[int, int, int]:
    return _decode(jpeg).getpixel((x, y))


def _close_to(actual: tuple[int, int, int], expected: tuple[int, int, int]) -> bool:
    return all(abs(actual[i] - expected[i]) <= _COLOR_TOLERANCE for i in range(3))


class FakeTransport:
    """Fake vendor transport; records every frame, never touches real nodes."""

    def __init__(
        self,
        *,
        open_error: OSError | None = None,
        write_error_at: int | None = None,
    ) -> None:
        self.open_error = open_error
        self.write_error_at = write_error_at
        self.open_calls: list[str] = []
        self.frames: list[bytes] = []
        self.drain_calls = 0
        self.close_calls = 0

    def open_read_write(self, node: str) -> int:
        self.open_calls.append(node)
        if self.open_error is not None:
            raise self.open_error
        return 41

    def write(self, fd: int, data: bytes) -> None:
        del fd
        if self.write_error_at is not None and len(self.frames) == self.write_error_at:
            raise OSError("scripted write failure")
        self.frames.append(bytes(data))

    def drain_acks(self, fd: int) -> int:
        del fd
        self.drain_calls += 1
        return 0

    def close(self, fd: int) -> None:
        del fd
        self.close_calls += 1


def test_feedback_state_enum_matches_the_design() -> None:
    assert [state.value for state in FeedbackState] == [
        "running",
        "success",
        "failure",
        "timeout",
    ]
    assert len(set(STATE_COLORS.values())) == len(FeedbackState)


@pytest.mark.parametrize("state", list(FeedbackState))
def test_render_state_image_returns_a_72x72_jpeg_for_every_state(state: FeedbackState) -> None:
    jpeg = render_state_image(state)

    assert isinstance(jpeg, bytes)
    assert jpeg.startswith(b"\xff\xd8")  # JPEG SOI marker
    assert _decode(jpeg).size == (KEY_IMAGE_SIZE, KEY_IMAGE_SIZE)


@pytest.mark.parametrize("state", list(FeedbackState))
def test_render_state_image_dominant_color_matches_the_state(state: FeedbackState) -> None:
    jpeg = render_state_image(state)

    assert _close_to(_pixel(jpeg, 2, 2), STATE_COLORS[state])
    assert _close_to(_pixel(jpeg, KEY_IMAGE_SIZE - 3, KEY_IMAGE_SIZE - 3), STATE_COLORS[state])


@pytest.mark.parametrize("state", list(FeedbackState))
def test_render_state_image_accepts_an_optional_text_line(state: FeedbackState) -> None:
    jpeg = render_state_image(state, text="first line summary")

    assert _decode(jpeg).size == (KEY_IMAGE_SIZE, KEY_IMAGE_SIZE)
    # The text is centered; the corners stay the solid state color.
    assert _close_to(_pixel(jpeg, 2, 2), STATE_COLORS[state])


def test_render_state_image_truncates_long_text_to_fit() -> None:
    jpeg = render_state_image(FeedbackState.SUCCESS, text="x" * 500)

    assert isinstance(jpeg, bytes)
    assert _decode(jpeg).size == (KEY_IMAGE_SIZE, KEY_IMAGE_SIZE)


def test_render_state_image_uses_only_the_first_line() -> None:
    jpeg = render_state_image(FeedbackState.SUCCESS, text="first line\nsecond line")

    assert isinstance(jpeg, bytes)
    assert _decode(jpeg).size == (KEY_IMAGE_SIZE, KEY_IMAGE_SIZE)


def test_render_state_image_rejects_bad_arguments() -> None:
    with pytest.raises(TypeError):
        render_state_image("running")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        render_state_image(FeedbackState.SUCCESS, text=42)  # type: ignore[arg-type]


def test_write_key_image_success_writes_the_bat_frames_and_closes() -> None:
    transport = FakeTransport()
    jpeg = render_state_image(FeedbackState.SUCCESS)

    ok = write_key_image(_NODE, 1, jpeg, transport)

    assert ok is True
    assert transport.open_calls == [_NODE]
    expected = list(_frames_for_command(AdapterCommand(Operation.SET_KEY_IMAGE, key=1, image=jpeg)))
    assert transport.frames == expected
    assert transport.drain_calls == len(expected)
    assert transport.close_calls == 1


def test_write_key_image_open_failure_returns_false() -> None:
    transport = FakeTransport(open_error=OSError("no write node"))
    jpeg = render_state_image(FeedbackState.SUCCESS)

    ok = write_key_image(_NODE, 1, jpeg, transport)

    assert ok is False
    assert transport.open_calls == [_NODE]
    assert transport.frames == []
    assert transport.close_calls == 0


def test_write_key_image_write_failure_returns_false_and_still_closes() -> None:
    transport = FakeTransport(write_error_at=0)
    jpeg = render_state_image(FeedbackState.SUCCESS)

    ok = write_key_image(_NODE, 1, jpeg, transport)

    assert ok is False
    assert transport.close_calls == 1
    assert transport.drain_calls == 0


def test_write_key_image_never_raises_on_transport_exceptions() -> None:
    class ExplodingTransport:
        def __init__(self, error: Exception) -> None:
            self.error = error

        def open_read_write(self, node: str) -> int:
            raise self.error

        def write(self, fd: int, frame: bytes) -> None:
            raise self.error

        def drain_acks(self, fd: int) -> int:
            raise self.error

        def close(self, fd: int) -> None:
            raise self.error

    jpeg = render_state_image(FeedbackState.SUCCESS)
    for error in (ValueError("bad frame"), RuntimeError("transport boom")):
        transport = ExplodingTransport(error)
        assert write_key_image(_NODE, 1, jpeg, transport) is False


def test_write_key_image_rejects_bad_arguments() -> None:
    jpeg = render_state_image(FeedbackState.SUCCESS)

    with pytest.raises(ValueError):
        write_key_image("", 1, jpeg, FakeTransport())
    with pytest.raises(ValueError):
        write_key_image(_NODE, 1, b"", FakeTransport())
    with pytest.raises(ValueError):
        write_key_image(_NODE, 1, "not bytes", FakeTransport())  # type: ignore[arg-type]


def test_write_key_image_out_of_range_key_returns_false() -> None:
    jpeg = render_state_image(FeedbackState.SUCCESS)
    transport = FakeTransport()

    assert write_key_image(_NODE, 0, jpeg, transport) is False
    assert write_key_image(_NODE, 7, jpeg, transport) is False
    assert transport.open_calls == []
