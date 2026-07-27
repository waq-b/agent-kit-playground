import logging

import agent_kit.notify as notify_mod


def test_empty_message_logs_warning_and_returns(monkeypatch, caplog):
    monkeypatch.setenv("NTFY_URL", "http://example.invalid/topic")
    with caplog.at_level(logging.WARNING):
        result = notify_mod.notify("")
    assert result is None
    assert any("length" in r.message for r in caplog.records)


def test_over_length_message_logs_warning_and_returns(monkeypatch, caplog):
    monkeypatch.setenv("NTFY_URL", "http://example.invalid/topic")
    with caplog.at_level(logging.WARNING):
        result = notify_mod.notify("x" * 5000)
    assert result is None
    assert any("length" in r.message for r in caplog.records)


def test_missing_ntfy_url_logs_warning(monkeypatch, caplog):
    monkeypatch.delenv("NTFY_URL", raising=False)
    with caplog.at_level(logging.WARNING):
        result = notify_mod.notify("hello")
    assert result is None
    assert any("NTFY_URL not set" in r.message for r in caplog.records)


def test_http_failure_logs_warning_and_does_not_raise(monkeypatch, caplog):
    monkeypatch.setenv("NTFY_URL", "http://example.invalid/topic")

    def fake_post(*args, **kwargs):
        raise ConnectionError("boom")

    monkeypatch.setattr(notify_mod.httpx, "post", fake_post)
    with caplog.at_level(logging.WARNING):
        result = notify_mod.notify("hello")
    assert result is None
    assert any("failed to send" in r.message for r in caplog.records)


def test_success_sends_no_warning(monkeypatch, caplog):
    monkeypatch.setenv("NTFY_URL", "http://example.invalid/topic")

    class FakeResponse:
        def raise_for_status(self) -> None:
            pass

    monkeypatch.setattr(notify_mod.httpx, "post", lambda *a, **kw: FakeResponse())
    with caplog.at_level(logging.WARNING):
        result = notify_mod.notify("hello")
    assert result is None
    assert not caplog.records
