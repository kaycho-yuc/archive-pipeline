import zipfile
from pathlib import Path

import openpyxl
import pytest
import docx

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


def test_extract_xlsx_text(tmp_path):
    xlsx = tmp_path / "sample.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "견적"
    ws.append(["항목", "금액"])
    ws.append(["철근공사", "5000000"])
    wb.save(xlsx)
    text = extract_text(xlsx)
    assert "견적" in text
    assert "철근공사" in text
    assert "5000000" in text


def test_extract_docx_text(tmp_path):
    docx_file = tmp_path / "sample.docx"
    doc = docx.Document()
    doc.add_paragraph("공사 계약서")
    doc.add_paragraph("제1조 총칙")
    doc.save(str(docx_file))
    text = extract_text(docx_file)
    assert "공사 계약서" in text
    assert "제1조 총칙" in text


def test_extract_xml_tax_invoice(tmp_path):
    """국세청 전자세금계산서 스키마(네임스페이스 포함)에서 핵심 필드를 뽑는다."""
    xml = tmp_path / "tax.xml"
    xml.write_text(
        """<?xml version="1.0" encoding="UTF-8"?>
<TaxInvoice xmlns="urn:kr:or:nts:standard">
  <ExchangedDocument><IssueDate>2026-02-04</IssueDate></ExchangedDocument>
  <TaxInvoiceTradeSettlement>
    <SellerParty><Party>
      <SpecifiedOrganization><NameName>누리구조</NameName></SpecifiedOrganization>
      <CompanyRegNumNumber>1234567890</CompanyRegNumNumber>
    </Party></SellerParty>
    <BuyerParty><Party>
      <SpecifiedOrganization><NameName>케이씨건설</NameName></SpecifiedOrganization>
      <CompanyRegNumNumber>9876543210</CompanyRegNumNumber>
    </Party></BuyerParty>
    <ChargeTotal>5000000</ChargeTotal>
    <TaxTotal>500000</TaxTotal>
    <GrandTotal>5500000</GrandTotal>
  </TaxInvoiceTradeSettlement>
  <TaxInvoiceTradeLineItem><ItemName>구조설계 계약금</ItemName></TaxInvoiceTradeLineItem>
</TaxInvoice>
""",
        encoding="utf-8",
    )
    text = extract_text(xml)
    assert "전자세금계산서" in text
    assert "누리구조" in text
    assert "케이씨건설" in text
    assert "5500000" in text
    assert "2026-02-04" in text
    assert "구조설계 계약금" in text


def test_extract_xml_generic_fallback(tmp_path):
    """세금계산서가 아닌 일반 XML 은 모든 요소 텍스트를 모은다."""
    xml = tmp_path / "note.xml"
    xml.write_text(
        '<?xml version="1.0"?><root><memo>회의 메모</memo><item>안건 검토</item></root>',
        encoding="utf-8",
    )
    text = extract_text(xml)
    assert "회의 메모" in text
    assert "안건 검토" in text


def test_extract_unsupported_extension():
    with pytest.raises(ValueError):
        extract_text(Path("unsupported.xyz"))
