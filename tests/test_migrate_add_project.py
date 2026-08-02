"""migrate_add_project 스모크 테스트. 실제 볼트를 절대 건드리지 않고 tmp_path 로만 검증한다."""

import zipfile
from pathlib import Path

import pytest

import migrate_add_project
from notes.write_note import UNKNOWN_PROJECT

_TEMPLATE = "---\ndomain: 업무\n{extra}source: {source}\n---\n\n## 원문\n\n{body}\n"


def _write(work_dir: Path, name: str, source: str, body: str, project: str | None = None) -> Path:
    extra = f"project: {project}\n" if project is not None else ""
    path = work_dir / name
    path.write_text(_TEMPLATE.format(extra=extra, source=source, body=body), encoding="utf-8")
    return path


@pytest.fixture
def work_dir(tmp_path, monkeypatch):
    """migrate_add_project 의 VAULT/WORK_DIR 를 tmp_path 로 돌려, 실제 볼트를 절대 건드리지 않는다."""
    monkeypatch.setattr(migrate_add_project, "VAULT", tmp_path)
    wd = tmp_path / "10_Professional"
    wd.mkdir()
    monkeypatch.setattr(migrate_add_project, "WORK_DIR", wd)
    return wd


def test_detects_project_from_body_when_filename_has_no_identifier(work_dir):
    """파일명엔 식별자가 없어도 `## 원문` 본문에 있으면 잡아야 한다(파이프라인이 잡는 38건 케이스).

    filename 만 보던 옛 _plan_change 구현이면 이 노트를 놓친다."""
    note = _write(
        work_dir,
        "잡다한서류.md",
        source="잡다한서류.pdf",
        body="이 문서는 685-317 번지 현장 공사와 관련된 서류이다. 세부 사항은 첨부 참고.",
    )

    plan = migrate_add_project._plan_change(note)

    assert plan == (None, "성수동 리모델링")


def test_redetect_does_not_scan_full_text_for_circularity(work_dir):
    """frontmatter 의 project 값 자체가 등록된 식별자이므로, 본문 대신 노트 전체를 스캔하면
    노트가 이미 달고 있는 라벨과 스스로 매치되는 순환 논리가 된다(거짓 191/192 결과).
    파일명·본문 어디에도 식별자가 없으면 --redetect 는 이 노트를 미정으로 내려야 한다 —
    전체 텍스트를 스캔했다면 frontmatter 의 'project: 성수동 리모델링' 에 걸려 이 테스트가 실패한다."""
    note = _write(
        work_dir,
        "아무개서류.md",
        source="아무개서류.pdf",
        body="이번 주 회의에서는 일정 조율과 예산 검토를 진행했다. 다음 회차 일정은 추후 공지한다.",
        project="성수동 리모델링",
    )

    plan = migrate_add_project._plan_change(note, redetect=True)

    assert plan == ("성수동 리모델링", UNKNOWN_PROJECT)


def test_without_redetect_existing_project_without_evidence_is_left_alone(work_dir):
    """--redetect 없이는, 식별자가 확증하지 못하면 기존 project 값을 존중해 건드리지 않는다
    (review_pending.py 로 사람이 손으로 정한 값을 보호하기 위함)."""
    note = _write(
        work_dir,
        "확정노트.md",
        source="확정서류.pdf",
        body="특이사항 없는 일반 회의 내용을 정리한 문서입니다. 추가로 확인할 사항은 없습니다.",
        project="성수동 리모델링",
    )

    plan = migrate_add_project._plan_change(note, redetect=False)

    assert plan is None


def test_with_redetect_demotes_project_without_evidence(work_dir):
    """--redetect 는 위 보호를 끄고 처음부터 다시 판별한다 — 근거가 없으면 미정으로 내린다."""
    note = _write(
        work_dir,
        "확정노트.md",
        source="확정서류.pdf",
        body="특이사항 없는 일반 회의 내용을 정리한 문서입니다. 추가로 확인할 사항은 없습니다.",
        project="성수동 리모델링",
    )

    plan = migrate_add_project._plan_change(note, redetect=True)

    assert plan == ("성수동 리모델링", UNKNOWN_PROJECT)


def test_missing_project_field_falls_back_to_unknown_not_default(work_dir):
    """project 필드가 없고 식별자도 못 찾으면 미정으로 채운다 — 예전 기본 프로젝트로
    조용히 채우던 DEFAULT_PROJECT 동작은 더 이상 없어야 한다."""
    note = _write(
        work_dir,
        "알수없는서류.md",
        source="알수없는서류.pdf",
        body="특별한 식별자가 없는 일반 문서 내용입니다. 별다른 지번 언급이 없습니다.",
    )

    plan = migrate_add_project._plan_change(note)

    assert plan == (None, UNKNOWN_PROJECT)


def test_redetect_leaves_foreign_project_value_untouched(work_dir):
    """--redetect 는 PROJECT_REGISTRY 에 없는 값('기타' 등 사람이 직접 적은 값)은 건드리지
    않는다 — 파이프라인이 스스로 만들 수 없었던 값을 근거 없이 미정으로 강등하면
    정보를 파괴하는 것이다(오너가 지적한 pyRevit 노트 회귀 방지 테스트)."""
    note = _write(
        work_dir,
        "기타노트.md",
        source="기타서류.pdf",
        body="특이사항 없는 일반 문서 내용입니다. 등록된 프로젝트와 무관한 개인 메모.",
        project="기타",
    )

    plan = migrate_add_project._plan_change(note, redetect=True)

    assert plan is None


def test_redetect_promotes_unknown_project_when_identifier_found(work_dir):
    """미정 노트는 재판별 대상에 반드시 포함돼야 한다 — 레지스트리가 넓어져 본문에서
    식별자가 확인되면 실제 프로젝트로 승격될 수 있어야 한다(막는 건 강등뿐)."""
    note = _write(
        work_dir,
        "미정노트.md",
        source="미정서류.pdf",
        body="이 문서는 685-317 번지 현장 공사 관련 서류이다. 세부 내용은 첨부 참고.",
        project=UNKNOWN_PROJECT,
    )

    plan = migrate_add_project._plan_change(note, redetect=True)

    assert plan == (UNKNOWN_PROJECT, "성수동 리모델링")


def test_backup_uses_given_vault_not_module_global(tmp_path, monkeypatch):
    """review_pending.py 처럼 다른 모듈이 자기 VAULT 를 넘기면, 백업은 그 vault 만 담아야
    한다 — 인자를 안 받으면 모듈 전역 VAULT 가 그대로 쓰여, 테스트용 --fix 가 진짜
    옵시디언 볼트를 zip 떠버리는 사고로 이어진다."""
    other_vault = tmp_path / "other_vault"
    other_vault.mkdir()
    (other_vault / "이노트.md").write_text("내용", encoding="utf-8")

    global_vault = tmp_path / "global_vault"
    global_vault.mkdir()
    (global_vault / "건드리면안됨.md").write_text("내용", encoding="utf-8")
    monkeypatch.setattr(migrate_add_project, "VAULT", global_vault)
    monkeypatch.chdir(tmp_path)  # 백업 zip 이 저장소 안에 남지 않도록

    dest = migrate_add_project._backup(other_vault)

    with zipfile.ZipFile(dest) as zf:
        names = zf.namelist()

    assert names == ["이노트.md"]
