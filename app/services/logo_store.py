"""Lưu trữ ảnh logo phiếu in (Stage 5.3).

Owner upload ảnh (png/jpg) → validate + resize/optimize bằng Pillow → lưu PNG vào
thư mục tĩnh {upload_dir}/logo/{tenant_id}.png (nginx serve trực tiếp). Trả URL
kèm cache-bust (?v=mtime) để đổi logo là thấy ngay, không kẹt cache trình duyệt.

Tách riêng khỏi settings_service để cô lập I/O file + phụ thuộc Pillow.
"""
import io
import os
import uuid

from PIL import Image, UnidentifiedImageError

from app.core.config import get_settings
from app.core.errors import APIError

_ALLOWED_CT = {"image/png", "image/jpeg", "image/jpg"}


def _logo_dir() -> str:
    return os.path.join(get_settings().upload_dir, "logo")


def store_logo(tenant_id: uuid.UUID, raw: bytes, content_type: str | None) -> str:
    """Validate + tối ưu + ghi file. Trả URL tương đối (kèm cache-bust)."""
    settings = get_settings()

    if not raw:
        raise APIError(422, "EMPTY_FILE", "File rỗng")
    if len(raw) > settings.logo_max_bytes:
        kb = settings.logo_max_bytes // 1024
        raise APIError(413, "LOGO_TOO_LARGE", f"Ảnh quá lớn (tối đa ~{kb}KB)")
    if content_type and content_type.lower() not in _ALLOWED_CT:
        raise APIError(422, "INVALID_IMAGE_TYPE", "Chỉ nhận ảnh PNG hoặc JPG")

    # Mở + xác thực là ảnh thật (không chỉ tin content-type/đuôi file).
    try:
        img = Image.open(io.BytesIO(raw))
        img.load()
    except (UnidentifiedImageError, OSError):
        raise APIError(422, "INVALID_IMAGE", "Tệp không phải ảnh hợp lệ")

    if img.format not in ("PNG", "JPEG"):
        raise APIError(422, "INVALID_IMAGE_TYPE", "Chỉ nhận ảnh PNG hoặc JPG")

    # Giữ alpha cho PNG (logo trên nền trắng phiếu); JPEG → RGB.
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    # Resize giữ tỉ lệ, cạnh lớn nhất = logo_max_px (chỉ thu nhỏ, không phóng to).
    img.thumbnail((settings.logo_max_px, settings.logo_max_px), Image.LANCZOS)

    dest_dir = _logo_dir()
    os.makedirs(dest_dir, exist_ok=True)
    path = os.path.join(dest_dir, f"{tenant_id}.png")
    img.save(path, format="PNG", optimize=True)

    mtime = int(os.path.getmtime(path))
    return f"{settings.upload_url_prefix}/logo/{tenant_id}.png?v={mtime}"
