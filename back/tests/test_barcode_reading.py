"""Pure unit tests for decode_barcode — no DB, no HTTP.

A real barcode is generated in-fixture via zxing-cpp's own write_barcode
(the same library this module uses to decode) rather than versioning a
binary image fixture in git — no extra test dependency needed.
"""
import io

import zxingcpp
from PIL import Image

from app.services.barcode_reading import decode_barcode


def _barcode_png_bytes(text: str, barcode_format: "zxingcpp.BarcodeFormat" = zxingcpp.BarcodeFormat.Code128) -> bytes:
    bitmap = zxingcpp.write_barcode(barcode_format, text, 300, 80)
    image = Image.frombuffer("L", (bitmap.shape[1], bitmap.shape[0]), bytes(bitmap), "raw", "L", 0, 1)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def test_decode_barcode_returns_none_for_non_image_bytes():
    # The same fake, non-image bytes used elsewhere in this suite (e.g.
    # test_traite_processing.py's _make_traite_with_documents) — never a
    # decodable image, must never raise.
    assert decode_barcode(b"fake-scan-bytes-recto") is None


def test_decode_barcode_returns_none_for_empty_bytes():
    assert decode_barcode(b"") is None


def test_decode_barcode_returns_none_for_a_real_image_with_no_barcode():
    """A plain, uniform image is a perfectly valid image — just one with
    nothing decodable in it, same honest-absence treatment as a genuinely
    blank RIB box."""
    buffer = io.BytesIO()
    Image.new("L", (200, 200), color=255).save(buffer, format="PNG")
    assert decode_barcode(buffer.getvalue()) is None


def test_decode_barcode_decodes_a_real_generated_barcode():
    png_bytes = _barcode_png_bytes("011570763437")
    assert decode_barcode(png_bytes) == "011570763437"


def test_decode_barcode_works_across_symbologies():
    """numero_lcn's real printed barcode's exact symbology isn't
    guaranteed — decode_barcode doesn't restrict formats, so any
    zxing-cpp-supported symbology should round-trip."""
    png_bytes = _barcode_png_bytes("999999999999", zxingcpp.BarcodeFormat.Code39)
    assert decode_barcode(png_bytes) == "999999999999"
