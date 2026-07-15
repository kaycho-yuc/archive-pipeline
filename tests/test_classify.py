import json

import pytest

from classifier import classify as classify_module
from classifier.classify import (
    KIND_PROJECT,
    KIND_REFERENCE,
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
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))

    result = classify("내용", source_name="전자세금계산서 20260131_ANA건축.pdf")

    assert result.category == "세금계산서"
    assert result.counterparty == "ANA건축"
    assert result.doc_date == "2026-01-31"
    assert result.title == "2026-01-31 세금계산서 - ANA건축"
    assert result.tags == ["근생", "리모델링"]


def test_classify_filename_forces_category_override(monkeypatch):
    # '주간운동리뷰' 파일은 모델이 다른 유형을 줘도 category=운동리뷰 로 강제된다.
    payload = {"domain": "개인", "category": "보고서", "doc_date": "2026-06-01"}
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))

    result = classify("내용", source_name="2026-06-01_주간운동리뷰.md")

    assert result.category == "운동리뷰"  # 모델의 '보고서' 대신 강제
    assert result.title == "2026-06-01 운동리뷰"  # 제목 유형 슬롯도 운동리뷰


def test_classify_no_override_without_marker(monkeypatch):
    # 표지 단어가 없으면 모델 category 를 그대로 쓴다.
    payload = {"domain": "개인", "category": "보고서"}
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))

    result = classify("내용", source_name="2026-06-18 13회차 운동일지.md")

    assert result.category == "보고서"


def test_classify_drops_malformed_doc_date(monkeypatch):
    for bad in ("작성일 미상", "2026-02-32", "2026-13-01"):  # 형식오류 + 없는 날짜
        payload = {"domain": "업무", "category": "견적서", "doc_date": bad}
        monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))
        result = classify("내용")
        assert result.doc_date == "", bad
        assert result.title == "견적서"


def test_classify_normalizes_tags_with_spaces(monkeypatch):
    payload = {"domain": "업무", "tags": ["성수동 현장", "성수동 현장", "공정표"]}
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))

    result = classify("내용")

    assert result.tags == ["성수동-현장", "공정표"]  # 공백→-, 중복 제거


def test_classify_rejects_invalid_domain(monkeypatch):
    payload = {"domain": "기타", "category": "x", "title": "t", "summary": "s"}
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))

    with pytest.raises(ValueError):
        classify("내용")


def test_classify_rejects_empty_text():
    with pytest.raises(ValueError):
        classify("   ")


def test_classify_defaults_missing_optional_fields(monkeypatch):
    # domain 만 있고 category/title/summary 가 빠진 응답도 기본값으로 살린다.
    payload = {"domain": "업무"}
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))

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
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))

    assert classify("빈 양식 ...").kind == KIND_REFERENCE


def test_classify_kind_defaults_to_project_when_missing_or_unknown(monkeypatch):
    # kind 누락 또는 알 수 없는 값이면 안전하게 프로젝트자료로 둔다(실데이터 보호).
    for payload in ({"domain": "업무"}, {"domain": "업무", "kind": "기타"}):
        monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))
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
        "_call_llm",
        lambda messages, model, temperature=0.0: next(responses),
    )

    result = classify("내용")

    assert result.domain == "개인"
    assert result.category == "메모"


# --- Track 1: 동적 프로젝트 분류 ---

from classifier.classify import PROJECT_NAME, detect_project  # noqa: E402


def test_detect_project_by_filename_identifier():
    # 파일명에 지번(685-317)이 있으면 기본 프로젝트로 판별. 하이픈·공백 무시 매칭.
    assert detect_project("685-317 대수선허가 필증.pdf") == PROJECT_NAME
    assert detect_project("685 383 증축.pdf") == PROJECT_NAME
    assert detect_project("성수동1가 도급계약.pdf") == PROJECT_NAME


def test_detect_project_from_body_when_filename_lacks_id():
    assert detect_project("계약서.pdf", "본문에 685-317 지번이 나온다") == PROJECT_NAME


def test_detect_project_none_when_no_identifier():
    assert detect_project("일반 회의록.pdf", "지번 없는 내용") == ""


def test_detect_project_extra_registry(monkeypatch):
    # 2번째 프로젝트가 등록되면 그 식별자로 판별된다.
    monkeypatch.setattr(
        classify_module,
        "PROJECT_REGISTRY",
        {PROJECT_NAME: ["685-317"], "판교 오피스": ["521-3", "판교"]},
    )
    assert detect_project("521-3 판교 계약.pdf") == "판교 오피스"
    assert detect_project("685-317 성수 계약.pdf") == PROJECT_NAME


def test_classify_assigns_detected_project(monkeypatch):
    payload = {"domain": "업무", "category": "허가서", "summary": "s"}
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))
    result = classify("내용", source_name="685-317 대수선허가 필증.pdf")
    assert result.project == PROJECT_NAME


def test_classify_personal_has_no_project(monkeypatch):
    payload = {"domain": "개인", "category": "메모", "summary": "s"}
    monkeypatch.setattr(classify_module, "_call_llm", _fake_response(payload))
    result = classify("내용", source_name="685-317 메모.md")
    assert result.project == ""  # 개인 노트엔 프로젝트를 부여하지 않는다
