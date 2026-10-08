"""Utilities for handling, compressing, and encoding images for multimodal model requests."""

from __future__ import annotations

import base64
import io
import mimetypes
import time
from pathlib import Path
from typing import Any

from .config import CAPTURE_DIR

SUPPORTED_IMAGE_EXTENSIONS: set[str] = {
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tiff",
    ".tif",
    ".gif",
}


def is_image_file(path_or_name: str | Path) -> bool:
    """Return True if the given path or filename has a supported image extension."""
    if not path_or_name:
        return False
    ext = Path(path_or_name).suffix.lower()
    return ext in SUPPORTED_IMAGE_EXTENSIONS


def encode_image_to_data_url(source: Any, max_dim: int = 1536) -> str:
    """Encode an image (path, bytes, QImage, or QPixmap) into a base64 Data URL.

    Downscales images exceeding max_dim on their longest edge to prevent token
    explosion, excessive payload sizes, and memory overhead.
    """
    if isinstance(source, str) and source.startswith("data:image/"):
        return source

    # Case 1: Qt QImage or QPixmap
    try:
        from pymol.Qt import QtCore, QtGui

        if isinstance(source, QtGui.QPixmap):
            source = source.toImage()

        if isinstance(source, QtGui.QImage):
            if source.isNull():
                raise ValueError("Encountered null QImage")
            w, h = source.width(), source.height()
            if max(w, h) > max_dim:
                source = source.scaled(
                    max_dim,
                    max_dim,
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
            byte_array = QtCore.QByteArray()
            buffer = QtCore.QBuffer(byte_array)
            buffer.open(QtCore.QIODevice.WriteOnly)
            has_alpha = source.hasAlphaChannel()
            fmt = "PNG" if has_alpha else "JPEG"
            quality = 90 if fmt == "JPEG" else -1
            source.save(buffer, fmt, quality)
            raw_bytes = bytes(byte_array)
            mime = "image/png" if fmt == "PNG" else "image/jpeg"
            b64_str = base64.b64encode(raw_bytes).decode("ascii")
            return f"data:{mime};base64,{b64_str}"
    except ImportError:
        pass

    # Case 2: Local file path or Path object
    if isinstance(source, (str, Path)):
        img_path = Path(source).expanduser().resolve()
        if not img_path.is_file():
            raise FileNotFoundError(f"Image file does not exist: {img_path.name}")

        # Try using PIL for efficient reading & downscaling if installed
        try:
            from PIL import Image

            with Image.open(img_path) as im:
                w, h = im.size
                if max(w, h) > max_dim:
                    im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                buf = io.BytesIO()
                has_alpha = im.mode in ("RGBA", "LA") or (
                    im.mode == "P" and "transparency" in im.info
                )
                fmt = "PNG" if has_alpha else "JPEG"
                if fmt == "JPEG" and im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(buf, format=fmt, quality=88, optimize=True)
                raw_bytes = buf.getvalue()
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                b64_str = base64.b64encode(raw_bytes).decode("ascii")
                return f"data:{mime};base64,{b64_str}"
        except ImportError:
            # Fallback to direct raw file bytes if PIL is unavailable
            raw_bytes = img_path.read_bytes()
            mime = mimetypes.guess_type(img_path.name)[0] or "image/jpeg"
            b64_str = base64.b64encode(raw_bytes).decode("ascii")
            return f"data:{mime};base64,{b64_str}"

    # Case 3: Raw bytes
    if isinstance(source, (bytes, bytearray)):
        try:
            from PIL import Image

            buf_in = io.BytesIO(source)
            with Image.open(buf_in) as im:
                w, h = im.size
                if max(w, h) > max_dim:
                    im.thumbnail((max_dim, max_dim), Image.Resampling.LANCZOS)
                buf_out = io.BytesIO()
                has_alpha = im.mode in ("RGBA", "LA")
                fmt = "PNG" if has_alpha else "JPEG"
                if fmt == "JPEG" and im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(buf_out, format=fmt, quality=88, optimize=True)
                raw_bytes = buf_out.getvalue()
                mime = "image/png" if fmt == "PNG" else "image/jpeg"
                b64_str = base64.b64encode(raw_bytes).decode("ascii")
                return f"data:{mime};base64,{b64_str}"
        except Exception:
            b64_str = base64.b64encode(source).decode("ascii")
            return f"data:image/jpeg;base64,{b64_str}"

    raise TypeError(f"Unsupported image source type: {type(source)}")


def capture_pymol_viewport(output_path: Path | None = None) -> Path | None:
    """Capture current PyMOL 3D viewport and save it as a PNG file."""
    try:
        from pymol import cmd

        CAPTURE_DIR.mkdir(parents=True, exist_ok=True)
        if output_path is None:
            timestamp = int(time.time() * 1000)
            output_path = CAPTURE_DIR / f"viewport_{timestamp}.png"
        else:
            output_path = Path(output_path).expanduser().resolve()

        # Ray=0 for fast viewport snapshot without raytracing delay
        cmd.png(str(output_path), ray=0, quiet=1)
        if output_path.is_file() and output_path.stat().st_size > 0:
            return output_path
    except Exception:
        pass
    return None
