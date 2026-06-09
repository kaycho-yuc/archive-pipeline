import zipfile
from pathlib import Path

import pytest

from extractors.extract import extract_text

FIXTURES = Path(__file__).parent / "fixtures"


def _make_hwpx(path: Path, paragraphs: list[str]) -> None:
    """테스트용 최소 HWPX(zip+OWPML) 파일을 만든다."""
    runs = "".join(f'<hp:t xmlns:hp="x">{p}</hp:t>' for p in paragraphs)
    section = f'<?xml version="1.0"?><hp:sec xmlns:hp="x">{runs}</hp:sec>'
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Contents/section0.xml", section)


def test_extract_plain_text():
    assert extract_text(FIXTURES / "sample.txt") == "안녕하세요, 테스트 텍스트입니다."


def test_extract_pdf_text():
    text = extract_text(FIXTURES / "sample.pdf")
    assert "Hello PDF" in text


def test_extract_hwpx_text(tmp_path):
    hwpx = tmp_path / "sample.hwpx"
    _make_hwpx(hwpx, ["계약서 제목", "제1조 목적"])
    text = extract_text(hwpx)
    assert "계약서 제목" in text
    assert "제1조 목적" in text


def test_extract_unsupported_extension():
    with pytest.raises(ValueError):
        extract_text(Path("unsupported.xyz"))
