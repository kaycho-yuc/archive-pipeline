import json

import notifier


def test_notify_skips_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert notifier.notify("hi") is False


def test_notify_posts_when_configured(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")

    sent = {}

    class _Resp:
        def read(self):
            return json.dumps({"ok": True}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_urlopen(url, data=None, timeout=0):
        sent["url"] = url
        sent["data"] = data
        return _Resp()

    monkeypatch.setattr(notifier.urllib.request, "urlopen", _fake_urlopen)

    assert notifier.notify("실패: a.pdf") is True
    assert "bottok" in sent["url"]
    assert b"123" in sent["data"]  # chat_id 가 본문에 들어감
