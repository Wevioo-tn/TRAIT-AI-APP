"""Barcode decoding — numero_lcn's second, independent verification source.

Per the functional spec (Synthèse d'analyse : Traite, "N° L-CN"): "OCR
texte haut droite + lecture code-barres bas = double vérification
croisée". Until this module, numero_lcn had exactly one source (the vision
model's own OCR reading, cross-checked only against its own second
occurrence) — the barcode printed at the bottom of the document was never
decoded at all.

Deliberately real image processing, not a VLM prompt: a vision-capable
LLM doesn't reliably decode a barcode's exact digits — that's a classic,
deterministic image-processing problem, not a language one. ``zxing-cpp``
is a self-contained Python wheel (no ``libzbar0``-style system package to
add to the Dockerfile, unlike ``pyzbar``) — revisit that choice if it
behaves poorly on real scans, per the ticket that introduced it.
"""
import io
import logging

import zxingcpp
from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)


def decode_barcode(image_bytes: bytes) -> str | None:
    """Returns the first decoded barcode's raw text, or None for anything
    that isn't a decodable barcode on this image — a cropped/rotated/
    low-quality scan, a genuinely absent barcode, or bytes that aren't
    even a valid image. Never raises: a barcode is a bonus verification
    signal here, not a required field, so a failed decode is exactly as
    unremarkable as an illegible RIB box — never a pipeline error."""
    try:
        image = Image.open(io.BytesIO(image_bytes))
    except (UnidentifiedImageError, OSError):
        return None

    try:
        results = zxingcpp.read_barcodes(image)
    except Exception:
        logger.warning("Échec de décodage code-barres (image non exploitable).", exc_info=True)
        return None

    if not results:
        return None
    return results[0].text or None
