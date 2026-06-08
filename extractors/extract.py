"""파일 타입별 텍스트 추출 모듈."""

from pathlib import Path

import pdfplumber
import pytesseract
from PIL import Image

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
TEXT_EXTENSIONS = {".txt", ".md"}

OCR_LANGUAGES = "kor+eng"


def extract_pdf_text(file_path: Path) -> str:
    with pdfplumber.open(file_path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages).strip()


def extract_image_text(file_path: Path) -> str:
    with Image.open(file_path) as image:
        return pytesseract.image_to_string(image, lang=OCR_LANGUAGES).strip()


def extract_plain_text(file_path: Path) -> str:
    return file_path.read_text(encoding="utf-8").strip()


def extract_text(file_path: Path) -> str:
    """파일 확장자에 따라 적절한 추출 방식을 선택해 텍스트를 반환한다."""
    suffix = file_path.suffix.lower()

    if suffix in PDF_EXTENSIONS:
        return extract_pdf_text(file_path)
    if suffix in IMAGE_EXTENSIONS:
        return extract_image_text(file_path)
    if suffix in TEXT_EXTENSIONS:
        return extract_plain_text(file_path)

    raise ValueError(f"지원하지 않는 파일 형식입니다: {suffix}")
