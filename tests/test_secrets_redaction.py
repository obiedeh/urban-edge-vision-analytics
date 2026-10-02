from __future__ import annotations

import logging
import stat

import pytest

from store.secrets import SecretBox, SecretKeyMismatch
from vision.redaction import Redactor, install_logging_filter, mask_url


def test_secret_box_roundtrip_and_key_file_permissions(tmp_path) -> None:
    key_file = tmp_path / "secret.key"
    box = SecretBox(key_file=key_file)
    token = box.encrypt("hunter2")
    assert token.startswith("enc:v1:")
    assert "hunter2" not in token
    assert box.decrypt(token) == "hunter2"
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600
    # Second box with the same file decrypts.
    assert SecretBox(key_file=key_file).decrypt(token) == "hunter2"


def test_secret_box_rejects_other_key(tmp_path) -> None:
    token = SecretBox(key_file=tmp_path / "a.key").encrypt("x")
    with pytest.raises(SecretKeyMismatch):
        SecretBox(key_file=tmp_path / "b.key").decrypt(token)


def test_secret_box_passes_legacy_plaintext_through(tmp_path) -> None:
    box = SecretBox(key_file=tmp_path / "k")
    assert box.decrypt("plain") == "plain"
    assert box.encrypt("") == ""
    assert box.decrypt("") == ""


def test_mask_url_strips_userinfo_and_query_secrets() -> None:
    assert mask_url("rtsp://admin:pw@10.0.0.5:554/s1") == "rtsp://***:***@10.0.0.5:554/s1"
    assert mask_url("opening rtsp://a:b@h/x failed") == "opening rtsp://***:***@h/x failed"
    assert mask_url("http://h/api?user=a&password=zzz&x=1") == "http://h/api?user=a&password=***&x=1"
    assert mask_url("no creds here") == "no creds here"


def test_redactor_replaces_registered_secrets_including_quoted_forms() -> None:
    r = Redactor()
    r.register("p@ss word")
    text = "ffmpeg: rtsp://user:p%40ss%20word@cam/stream failed, pw was p@ss word"
    out = r.redact(text)
    assert "p@ss word" not in out
    assert "p%40ss%20word" not in out
    assert "rtsp://***:***@cam/stream" in out


def test_logging_filter_scrubs_records() -> None:
    from vision.redaction import REDACTOR

    REDACTOR.register("topsecret99")
    logger = logging.getLogger("redaction-test")
    install_logging_filter(logger)
    records: list[logging.LogRecord] = []

    class Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.info("connecting with %s", "topsecret99")
    assert records and "topsecret99" not in records[0].getMessage()
    assert "***" in records[0].getMessage()
