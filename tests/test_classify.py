import json

import pytest

from classifier import classify as classify_module
from classifier.classify import (
    KIND_PROJECT,
    KIND_REFERENCE,
    Classification,
    classify,
    compose_title,
)


def _fake_response(payload: dict):
    return lambda messages, model, temperature=0.0: json.dumps(payload)


def test_compose_title_format():
    # 명명규칙: YYYY-MM-DD <유형> - <상대방> (<부가, 상태>)
    assert (
        compose_title("용역계약서", "영진D&EC", "2026-02-04", "설비전기통신소방", "초안")
        == "2026-02-04 용역계약서 - 영진D&EC (설비전기통신소방, 초안)"
    )
    assert compose_title("세금계산서", "ANA건축", "2026-01-31") == "2026-01-31 세금계산서 - ANA건축"
    assert compose_title("회의록", "", "") == "회의록"  # 상대방·날짜 없으면 유형만


def test_classify_extracts_fields_and_composes_title(monkeypatch):
    payload = {
        "domain": "업무",
        "category": "세금계산서",
        "counterparty": "ANA건축",
        "doc_date": "2026-01-31",
        "tags": ["근생", "리모델링"],
        "summary": "ANA건축 세금계산서.",
    }
    monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))

    result = classify("내용", source_name="전자세금계산서 20260131_ANA건축.pdf")

    assert result.category == "세금계산서"
    assert result.counterparty == "ANA건축"
    assert result.doc_date == "2026-01-31"
    assert result.title == "2026-01-31 세금계산서 - ANA건축"
    assert result.tags == ["근생", "리모델링"]


def test_classify_drops_malformed_doc_date(monkeypatch):
    for bad in ("작성일 미상", "2026-02-32", "2026-13-01"):  # 형식오류 + 없는 날짜
        payload = {"domain": "업무", "category": "견적서", "doc_date": bad}
        monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))
        result = classify("내용")
        assert result.doc_date == "", bad
        assert result.title == "견적서"


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
    assert result.title == "미분류"  # 제목은 category 로 조립(상대방·날짜 없음)
    assert result.counterparty == ""
    assert result.doc_date == ""
    assert result.summary == ""
    assert result.tags == []


def test_classify_detects_reference_kind(monkeypatch):
    # 명시적으로 참고자료라고 응답하면 kind 가 참고자료여야 한다.
    payload = {"domain": "업무", "kind": "참고자료", "title": "표준 도급계약서 양식"}
    monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))

    assert classify("빈 양식 ...").kind == KIND_REFERENCE


def test_classify_kind_defaults_to_project_when_missing_or_unknown(monkeypatch):
    # kind 누락 또는 알 수 없는 값이면 안전하게 프로젝트자료로 둔다(실데이터 보호).
    for payload in ({"domain": "업무"}, {"domain": "업무", "kind": "기타"}):
        monkeypatch.setattr(classify_module, "_call_ollama", _fake_response(payload))
        assert classify("내용").kind == KIND_PROJECT


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
