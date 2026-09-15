"""Prepare vision inputs with the standalone extractor's image pipeline."""

import base64
import warnings
from io import BytesIO

from PIL import Image, ImageOps, UnidentifiedImageError


def normalize_image(data: bytes) -> str:
    """Validate, orient, flatten transparency and encode without resizing."""
    if not data:
        raise ValueError("An uploaded image is empty.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Only JPEG, PNG, and WebP images are supported.")
                if image.width * image.height > 20_000_000:
                    raise ValueError("Image exceeds the pixel limit.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValueError("Animated images are not supported.")
                image.verify()

            with Image.open(BytesIO(data)) as source:
                image = ImageOps.exif_transpose(source).convert("RGBA")
                background = Image.new("RGBA", image.size, "white")
                image = Image.alpha_composite(background, image).convert("RGB")
                with BytesIO() as output:
                    image.save(output, format="JPEG", quality=95, subsampling=0)
                    normalized = output.getvalue()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise ValueError("Image exceeds the safe decoding limit.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("An uploaded file is not a valid, complete image.") from exc

    if len(normalized) > 10 * 1024 * 1024:
        raise ValueError("Decoded image exceeds the upload limit.")
    return "data:image/jpeg;base64," + base64.b64encode(normalized).decode("ascii")
