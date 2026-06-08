"""파일 타입별 텍스트 추출 모듈."""

import io
from pathlib import Path

import fitz  # PyMuPDF: 스캔 PDF를 이미지로 렌더링해 OCR 하기 위함
import pdfplumber
import pytesseract
from PIL import Image, ImageOps

PDF_EXTENSIONS = {".pdf"}
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"}
TEXT_EXTENSIONS = {".txt", ".md"}

OCR_LANGUAGES = "kor+eng"

# 임베드 텍스트가 이 길이 미만이면 스캔 PDF로 보고 OCR 로 폴백한다.
MIN_PDF_TEXT_CHARS = 50

# OCR 렌더링 해상도. 높을수록 정확하지만 느리고 메모리를 더 쓴다.
PDF_OCR_DPI = 300

# 스캔 문서 OCR 설정. 한국어 스캔본은 이진화(흑백 변환) 없이는 인식률이 매우 낮다.
# 임계값보다 어두운 픽셀만 검정으로 만들어 글자와 배경을 분리한다.
OCR_BINARIZE_THRESHOLD = 150
# psm 6 = "하나의 균일한 텍스트 블록으로 간주" — 본문 위주 계약서 스캔에 가장 정확했다.
PDF_OCR_CONFIG = "--psm 6"


def _pdf_embedded_text(file_path: Path) -> str:
    with pdfplumber.open(file_path) as pdf:
        pages = [page.extract_text() or "" for page in pdf.pages]
    return "\n".join(pages).strip()


def _ocr_scanned_page(image: Image.Image) -> str:
    """스캔 페이지 이미지를 전처리(그레이스케일·대비·이진화)한 뒤 OCR 한다."""
    gray = ImageOps.autocontrast(image.convert("L"))
    binary = gray.point(lambda px: 0 if px < OCR_BINARIZE_THRESHOLD else 255, "1")
    return pytesseract.image_to_string(binary, lang=OCR_LANGUAGES, config=PDF_OCR_CONFIG)


def _pdf_ocr_text(file_path: Path) -> str:
    """PDF 각 페이지를 이미지로 렌더링한 뒤 전처리·OCR 해 텍스트를 뽑는다."""
    pages = []
    with fitz.open(file_path) as doc:
        for page in doc:
            pix = page.get_pixmap(dpi=PDF_OCR_DPI)
            with Image.open(io.BytesIO(pix.tobytes("png"))) as image:
                pages.append(_ocr_scanned_page(image))
    return "\n".join(pages).strip()


def extract_pdf_text(file_path: Path) -> str:
    """임베드 텍스트를 우선 추출하고, 비어 있으면(스캔 PDF) OCR 로 폴백한다."""
    text = _pdf_embedded_text(file_path)
    if len(text) >= MIN_PDF_TEXT_CHARS:
        return text

    ocr_text = _pdf_ocr_text(file_path)
    return ocr_text if len(ocr_text) > len(text) else text


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
