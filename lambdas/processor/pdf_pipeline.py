"""Pure PDF processing pipeline (no AWS calls) so it is easy to unit-test.

validate -> repair -> normalize to A4 + compress -> strip metadata + linearize
"""
import io
import logging
from dataclasses import dataclass

import pikepdf
from pypdf import PdfReader, PdfWriter, Transformation

logger = logging.getLogger(__name__)

A4_W, A4_H = 595.276, 841.890  # points (1/72 inch)


class PdfValidationError(Exception):
    """The input is not an acceptable PDF. Permanent failure - do not retry."""


@dataclass
class ProcessResult:
    data: bytes
    pages: int
    input_bytes: int
    output_bytes: int
    images_recompressed: int


def validate_and_repair(data: bytes, max_bytes: int, max_pages: int):
    """Validate the upload and return (repaired_bytes, page_count)."""
    if not data:
        raise PdfValidationError("file is empty")
    if len(data) > max_bytes:
        raise PdfValidationError(f"file is larger than {max_bytes // (1024 * 1024)} MB")
    if data[:1024].find(b"%PDF-") == -1:
        raise PdfValidationError("missing %PDF header - not a PDF file")
    try:
        # pikepdf/qpdf transparently reconstructs broken xref tables.
        pdf = pikepdf.open(io.BytesIO(data))
    except pikepdf.PasswordError as exc:
        raise PdfValidationError("PDF is password-protected") from exc
    except Exception as exc:  # pikepdf.PdfError and friends
        raise PdfValidationError(f"PDF cannot be read or repaired: {str(exc)[:200]}") from exc

    with pdf:
        pages = len(pdf.pages)
        if pages == 0:
            raise PdfValidationError("PDF has no pages")
        if pages > max_pages:
            raise PdfValidationError(f"PDF has {pages} pages; the limit is {max_pages}")
        # Drop active content that runs on open.
        root = pdf.Root
        for key in ("/OpenAction", "/AA"):
            if key in root:
                del root[key]
        names = root.get("/Names")
        if names is not None and "/JavaScript" in names:
            del names["/JavaScript"]
        out = io.BytesIO()
        pdf.save(out)
    return out.getvalue(), pages


def normalize_a4(data: bytes, image_quality: int = 70):
    """Scale + centre every page onto A4 (orientation preserved) and compress."""
    reader = PdfReader(io.BytesIO(data))
    writer = PdfWriter()
    recompressed = 0

    for src in reader.pages:
        src.transfer_rotation_to_content()
        box = src.cropbox
        w, h = float(box.width), float(box.height)
        if w <= 0 or h <= 0:
            raise PdfValidationError("page has an invalid size")
        tw, th = (A4_H, A4_W) if w > h else (A4_W, A4_H)
        scale = min(tw / w, th / h)
        tx = (tw - w * scale) / 2 - float(box.left) * scale
        ty = (th - h * scale) / 2 - float(box.bottom) * scale
        page = writer.add_blank_page(width=tw, height=th)
        page.merge_transformed_page(src, Transformation().scale(scale, scale).translate(tx, ty))

        if image_quality > 0:
            try:
                for image in page.images:
                    try:
                        image.replace(image.image, quality=image_quality)
                        recompressed += 1
                    except Exception as exc:  # exotic colour spaces / filters: keep original
                        logger.warning("image not recompressed: %s", exc)
            except Exception as exc:
                logger.warning("could not enumerate images: %s", exc)
        page.compress_content_streams()

    writer.compress_identical_objects(remove_identicals=True, remove_orphans=True)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue(), recompressed


def finalize(data: bytes) -> bytes:
    """Strip metadata, then write a compressed, linearized (fast web view) PDF."""
    with pikepdf.open(io.BytesIO(data)) as pdf:
        if "/Info" in pdf.trailer:
            del pdf.trailer["/Info"]
        for holder in [pdf.Root, *pdf.pages]:
            for key in ("/Metadata", "/PieceInfo"):
                if key in holder:
                    del holder[key]
        out = io.BytesIO()
        pdf.save(
            out,
            linearize=True,
            compress_streams=True,
            recompress_flate=True,
            object_stream_mode=pikepdf.ObjectStreamMode.generate,
        )
    return out.getvalue()


def process_pdf(data: bytes, *, max_bytes: int, max_pages: int, image_quality: int = 70) -> ProcessResult:
    input_bytes = len(data)
    repaired, pages = validate_and_repair(data, max_bytes, max_pages)
    normalized, recompressed = normalize_a4(repaired, image_quality)
    final = finalize(normalized)
    # Sanity check: the result must be readable and keep the page count.
    if len(PdfReader(io.BytesIO(final)).pages) != pages:
        raise RuntimeError("page count changed during processing")
    return ProcessResult(final, pages, input_bytes, len(final), recompressed)
