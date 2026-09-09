from __future__ import annotations

import hashlib
import io
import warnings
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
MAX_INPUT_WIDTH = 8_000
MAX_INPUT_HEIGHT = 8_000
MAX_INPUT_PIXELS = 40_000_000
MAX_FULL_DIMENSION = 2_000
THUMBNAIL_SIZE = 200
FULL_JPEG_QUALITY = 90
THUMBNAIL_JPEG_QUALITY = 88
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}


class ImageProcessingError(ValueError):
    """Raised when an uploaded image is invalid or outside admin limits."""


@dataclass(frozen=True)
class ProcessedImage:
    source_format: str
    source_bytes: int
    source_width: int
    source_height: int
    full_width: int
    full_height: int
    full_bytes: bytes
    full_sha256: str
    thumb_width: int
    thumb_height: int
    thumb_bytes: bytes
    thumb_sha256: str


def _flatten_to_rgb(image: Image.Image) -> Image.Image:
    """Return an RGB image, compositing transparency onto white when needed."""
    if image.mode == "RGB":
        return image.copy()

    has_transparency = (
        image.mode in {"RGBA", "LA"}
        or (image.mode == "P" and "transparency" in image.info)
    )
    if has_transparency:
        rgba = image.convert("RGBA")
        canvas = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        canvas.alpha_composite(rgba)
        return canvas.convert("RGB")

    return image.convert("RGB")


def _jpeg_bytes(image: Image.Image, *, quality: int) -> bytes:
    buffer = io.BytesIO()
    image.save(
        buffer,
        format="JPEG",
        quality=quality,
        optimize=True,
        progressive=True,
    )
    return buffer.getvalue()


def process_image_upload(data: bytes) -> ProcessedImage:
    """
    Decode an uploaded image entirely from memory and return normalized JPEG bytes.

    The raw upload is never written to disk by this function.
    """
    source_bytes = len(data)
    if source_bytes == 0:
        raise ImageProcessingError("Image upload is empty")
    if source_bytes > MAX_UPLOAD_BYTES:
        raise ImageProcessingError("Image exceeds the 5 MB upload limit")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as opened:
                source_format = (opened.format or "").upper()
                if source_format not in ALLOWED_FORMATS:
                    raise ImageProcessingError(
                        "Unsupported image format. Use JPEG, PNG or WebP."
                    )

                if getattr(opened, "n_frames", 1) != 1:
                    raise ImageProcessingError("Animated or multi-frame images are not supported")

                width, height = opened.size
                if width <= 0 or height <= 0:
                    raise ImageProcessingError("Image has invalid dimensions")
                if width > MAX_INPUT_WIDTH or height > MAX_INPUT_HEIGHT:
                    raise ImageProcessingError(
                        f"Image dimensions may not exceed {MAX_INPUT_WIDTH}×{MAX_INPUT_HEIGHT} pixels"
                    )
                if width * height > MAX_INPUT_PIXELS:
                    raise ImageProcessingError("Image may not exceed 40 megapixels")

                # Force complete decoding while the source exists only in memory.
                opened.load()
                oriented = ImageOps.exif_transpose(opened)
                source_width, source_height = oriented.size
                rgb = _flatten_to_rgb(oriented)

    except ImageProcessingError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning, OSError) as exc:
        raise ImageProcessingError("Unable to decode a valid JPEG, PNG or WebP image") from exc

    try:
        # Public full-size image: preserve aspect ratio, never upscale, max long edge 2000px.
        full = rgb.copy()
        full.thumbnail(
            (MAX_FULL_DIMENSION, MAX_FULL_DIMENSION),
            Image.Resampling.LANCZOS,
        )
        full_width, full_height = full.size
        full_bytes = _jpeg_bytes(full, quality=FULL_JPEG_QUALITY)

        # Match the established notebook behavior: centered square crop, then 200×200 LANCZOS.
        thumb = ImageOps.fit(
            rgb,
            (THUMBNAIL_SIZE, THUMBNAIL_SIZE),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.5),
        )
        thumb_bytes = _jpeg_bytes(thumb, quality=THUMBNAIL_JPEG_QUALITY)
    finally:
        rgb.close()
        if "full" in locals():
            full.close()
        if "thumb" in locals():
            thumb.close()

    return ProcessedImage(
        source_format=source_format,
        source_bytes=source_bytes,
        source_width=source_width,
        source_height=source_height,
        full_width=full_width,
        full_height=full_height,
        full_bytes=full_bytes,
        full_sha256=hashlib.sha256(full_bytes).hexdigest(),
        thumb_width=THUMBNAIL_SIZE,
        thumb_height=THUMBNAIL_SIZE,
        thumb_bytes=thumb_bytes,
        thumb_sha256=hashlib.sha256(thumb_bytes).hexdigest(),
    )
