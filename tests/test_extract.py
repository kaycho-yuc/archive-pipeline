from pathlib import Path

import pytest

from extractors.extract import extract_text

FIXTURES = Path(__file__).parent / "fixtures"


def test_extract_plain_text():
    assert extract_text(FIXTURES / "sample.txt") == "안녕하세요, 테스트 텍스트입니다."


def test_extract_pdf_text():
    text = extract_text(FIXTURES / "sample.pdf")
    assert "Hello PDF" in text


def test_extract_unsupported_extension():
    with pytest.raises(ValueError):
        extract_text(Path("unsupported.xyz"))
