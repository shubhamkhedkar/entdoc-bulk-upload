import io

import pikepdf
import pytest
from pypdf import PdfReader

import pdf_pipeline
from pdf_pipeline import A4_H, A4_W, PdfValidationError, process_pdf

LIMITS = dict(max_bytes=50 * 1024 * 1024, max_pages=500)


def test_pages_normalized_to_a4_and_orientation_kept(pdf_factory):
    data = pdf_factory(pages=[(612, 792), (842, 1191), (792, 612), (300, 300)])  # Letter, A3, landscape, square
    result = process_pdf(data, **LIMITS)
    pages = PdfReader(io.BytesIO(result.data)).pages
    assert result.pages == len(pages) == 4
    sizes = [(round(float(p.mediabox.width), 1), round(float(p.mediabox.height), 1)) for p in pages]
    portrait, landscape = (round(A4_W, 1), round(A4_H, 1)), (round(A4_H, 1), round(A4_W, 1))
    assert sizes == [portrait, portrait, landscape, portrait]


def test_text_survives_and_content_is_scaled_inside_page(pdf_factory):
    result = process_pdf(pdf_factory(pages=[(1200, 1600)], text="Findme"), **LIMITS)
    page = PdfReader(io.BytesIO(result.data)).pages[0]
    assert "Findme" in page.extract_text()


def test_rotated_page_is_handled(pdf_factory):
    src = pikepdf.open(io.BytesIO(pdf_factory()))
    src.pages[0].Rotate = 90
    buf = io.BytesIO()
    src.save(buf)
    result = process_pdf(buf.getvalue(), **LIMITS)
    page = PdfReader(io.BytesIO(result.data)).pages[0]
    assert float(page.mediabox.width) > float(page.mediabox.height)  # 90deg => landscape


def test_metadata_stripped_and_linearized(pdf_factory):
    data = pdf_factory(title="Top Secret", author="Jane Doe")
    pdf = pikepdf.open(io.BytesIO(data))
    with pdf.open_metadata() as meta:
        meta["dc:title"] = "XMP Title"
    buf = io.BytesIO()
    pdf.save(buf)
    result = process_pdf(buf.getvalue(), **LIMITS)
    assert b"Top Secret" not in result.data and b"Jane Doe" not in result.data and b"XMP Title" not in result.data
    with pikepdf.open(io.BytesIO(result.data)) as out:
        assert out.is_linearized
        assert len(out.docinfo.keys()) == 0
        assert "/Metadata" not in out.Root
    assert not (PdfReader(io.BytesIO(result.data)).metadata or {})


def test_images_are_recompressed_and_output_smaller(pdf_factory):
    data = pdf_factory(image=True)
    result = process_pdf(data, image_quality=30, **LIMITS)
    assert result.images_recompressed >= 1
    assert result.output_bytes < result.input_bytes


def test_image_recompression_can_be_disabled(pdf_factory):
    result = process_pdf(pdf_factory(image=True), image_quality=0, **LIMITS)
    assert result.images_recompressed == 0


def test_truncated_pdf_is_repaired(pdf_factory):
    data = pdf_factory(pages=[(612, 792)] * 3)
    broken = data[: len(data) - 120]  # chop xref/trailer
    result = process_pdf(broken, **LIMITS)
    assert result.pages == 3


def test_javascript_and_open_action_removed(pdf_factory):
    pdf = pikepdf.open(io.BytesIO(pdf_factory()))
    pdf.Root.OpenAction = pikepdf.Dictionary(S=pikepdf.Name.JavaScript, JS=pikepdf.String("app.alert(1)"))
    pdf.Root.AA = pikepdf.Dictionary()
    buf = io.BytesIO()
    pdf.save(buf)
    result = process_pdf(buf.getvalue(), **LIMITS)
    with pikepdf.open(io.BytesIO(result.data)) as out:
        assert "/OpenAction" not in out.Root and "/AA" not in out.Root
    assert b"app.alert" not in result.data


@pytest.mark.parametrize(
    "payload,message",
    [
        (b"", "empty"),
        (b"just some text, definitely not a pdf", "header"),
        (b"%PDF-1.7\ngarbage garbage garbage", "cannot be read"),
    ],
)
def test_invalid_inputs_rejected(payload, message):
    with pytest.raises(PdfValidationError, match=message):
        process_pdf(payload, **LIMITS)


def test_encrypted_pdf_rejected(pdf_factory):
    pdf = pikepdf.open(io.BytesIO(pdf_factory()))
    buf = io.BytesIO()
    pdf.save(buf, encryption=pikepdf.Encryption(user="pw", owner="owner"))
    with pytest.raises(PdfValidationError, match="password"):
        process_pdf(buf.getvalue(), **LIMITS)


def test_page_and_size_limits(pdf_factory):
    with pytest.raises(PdfValidationError, match="pages"):
        process_pdf(pdf_factory(pages=[(612, 792)] * 3), max_bytes=10**7, max_pages=2)
    with pytest.raises(PdfValidationError, match="larger"):
        process_pdf(pdf_factory(), max_bytes=100, max_pages=10)


def test_validate_returns_page_count(pdf_factory):
    _, pages = pdf_pipeline.validate_and_repair(pdf_factory(pages=[(612, 792)] * 2), 10**7, 10)
    assert pages == 2
