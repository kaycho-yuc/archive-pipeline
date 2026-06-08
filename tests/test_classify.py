import json

import pytest

from classifier import classify as classify_module
from classifier.classify import Classification, classify


def _fake_response(payload: dict):
    return lambda messages, model: json.dumps(payload)


def test_classify_parses_valid_response(monkeypatch):
    payload = {
        "domain": "업무",
        "category": "회의록",
        "title": "주간 회의 정리",
        "summary": "이번 주 진행 상황을 정리한 회의록입니다.",
    }
    monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))

    result = classify("회의 내용 ...")

    assert result == Classification(
        domain="업무",
        category="회의록",
        title="주간 회의 정리",
        summary="이번 주 진행 상황을 정리한 회의록입니다.",
    )


def test_classify_rejects_invalid_domain(monkeypatch):
    payload = {"domain": "기타", "category": "x", "title": "t", "summary": "s"}
    monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))

    with pytest.raises(ValueError):
        classify("내용")


def test_classify_rejects_empty_text():
    with pytest.raises(ValueError):
        classify("   ")
