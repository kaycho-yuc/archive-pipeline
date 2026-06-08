import json

import pytest

from classifier import classify as classify_module
from classifier.classify import Classification, classify


def _fake_response(payload: dict):
    return lambda messages, model, temperature=0.0: json.dumps(payload)


def test_classify_parses_valid_response(monkeypatch):
    payload = {
        "domain": "업무",
        "category": "회의록",
        "tags": ["주간회의", "진행상황"],
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
        tags=["주간회의", "진행상황"],
    )


def test_classify_normalizes_tags_with_spaces(monkeypatch):
    payload = {"domain": "업무", "tags": ["성수동 현장", "성수동 현장", "공정표"]}
    monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))

    result = classify("내용")

    assert result.tags == ["성수동-현장", "공정표"]  # 공백→-, 중복 제거


def test_classify_rejects_invalid_domain(monkeypatch):
    payload = {"domain": "기타", "category": "x", "title": "t", "summary": "s"}
    monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))

    with pytest.raises(ValueError):
        classify("내용")


def test_classify_rejects_empty_text():
    with pytest.raises(ValueError):
        classify("   ")


def test_classify_defaults_missing_optional_fields(monkeypatch):
    # domain 만 있고 category/title/summary 가 빠진 응답도 기본값으로 살린다.
    payload = {"domain": "업무"}
    monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))

    result = classify("내용")

    assert result.domain == "업무"
    assert result.category == "미분류"
    assert result.title == "제목 없음"
    assert result.summary == ""
    assert result.tags == []


def test_classify_retries_then_succeeds(monkeypatch):
    # 첫 호출은 domain 누락(실패), 다음 호출은 정상 → 재시도로 성공해야 한다.
    responses = iter(
        [
            json.dumps({"category": "x", "title": "t", "summary": "s"}),
            json.dumps({"domain": "개인", "category": "메모", "title": "t", "summary": "s"}),
        ]
    )
    monkeypatch.setattr(
        classify_module,
        "_call_ollama",
        lambda messages, model, temperature=0.0: next(responses),
    )

    result = classify("내용")

    assert result.domain == "개인"
    assert result.category == "메모"
