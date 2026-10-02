from __future__ import annotations

import pytest

from vision import probe as probe_mod
from vision.probe import classify_error, probe_stream


@pytest.mark.parametrize(
    "message,stage",
    [
        ("Server returned 401 Unauthorized", "auth"),
        ("method DESCRIBE failed: 404 Not Found", "path"),
        ("Connection refused", "reachability"),
        ("Connection timed out", "timeout"),
        ("Invalid data found when processing input", "codec"),
    ],
)
def test_classify_error(message: str, stage: str) -> None:
    assert classify_error(message)[0] == stage


def test_classify_error_redacts_unknown_messages() -> None:
    from vision.redaction import REDACTOR

    REDACTOR.register("sekrit")
    stage, text = classify_error("weird failure for rtsp://u:sekrit@h/x")
    assert stage == "decode"
    assert "sekrit" not in text


def test_probe_reports_unreachable_without_opening_stream(monkeypatch) -> None:
    monkeypatch.setattr(probe_mod, "tcp_reachable", lambda h, p, timeout=2.0: "Connection refused")
    result = probe_stream("rtsp://u:p@192.0.2.1:554/stream1", timeout_s=1)
    assert not result.ok
    assert result.stage == "reachability"
    assert "p@" not in (result.error or "")
    assert result.masked_url == "rtsp://***:***@192.0.2.1:554/stream1"


def test_probe_decodes_one_frame_with_fake_av(monkeypatch) -> None:
    from PIL import Image

    class FakeFrame:
        def to_image(self):
            return Image.new("RGB", (1280, 720), (10, 20, 30))

    class FakeCodec:
        name = "h264"

    class FakeStream:
        type = "video"
        codec_context = FakeCodec()
        average_rate = 15

    class FakeContainer:
        streams = [FakeStream()]

        def decode(self, video=0):
            yield FakeFrame()

        def close(self):
            pass

    import types

    fake_av = types.SimpleNamespace(open=lambda url, options=None, timeout=None: FakeContainer())
    monkeypatch.setitem(__import__("sys").modules, "av", fake_av)
    monkeypatch.setattr(probe_mod, "tcp_reachable", lambda h, p, timeout=2.0: None)
    result = probe_stream("rtsp://u:p@cam:554/stream1", timeout_s=2)
    assert result.ok and result.stage == "ok"
    assert (result.width, result.height) == (1280, 720)
    assert result.codec == "h264"
    assert result.thumbnail_jpeg and result.thumbnail_jpeg[:2] == b"\xff\xd8"
    data = result.to_dict()
    assert data["thumbnail_data_url"].startswith("data:image/jpeg;base64,")


def test_probe_classifies_auth_failure_from_av(monkeypatch) -> None:
    import types

    def boom(url, options=None, timeout=None):
        raise OSError("[rtsp @ 0x1] method DESCRIBE failed: 401 Unauthorized")

    monkeypatch.setitem(__import__("sys").modules, "av", types.SimpleNamespace(open=boom))
    monkeypatch.setattr(probe_mod, "tcp_reachable", lambda h, p, timeout=2.0: None)
    result = probe_stream("rtsp://u:p@cam:554/stream1", timeout_s=2)
    assert not result.ok and result.stage == "auth"
    assert "username and password" in (result.error or "")
