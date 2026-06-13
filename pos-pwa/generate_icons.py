"""Sinh icon PWA (placeholder) bằng thư viện chuẩn — không cần Pillow.

Vẽ nền cam #F97316 + vòng tròn trắng (motif "cửa máy giặt") cho dễ nhận diện.
Chạy: python3 generate_icons.py  (ghi ra public/).
Thay bằng icon thiết kế thật khi có brand asset.
"""
import struct
import zlib
from pathlib import Path

ORANGE = (249, 115, 22)   # #F97316
WHITE = (255, 255, 255)

PUBLIC = Path(__file__).parent / "public"


def _png(size: int, path: Path) -> None:
    cx = cy = (size - 1) / 2
    r_out = size * 0.34
    r_in = size * 0.20
    rows = bytearray()
    for y in range(size):
        rows.append(0)  # filter type 0 cho mỗi scanline
        for x in range(size):
            d2 = (x - cx) ** 2 + (y - cy) ** 2
            # Vòng trắng (ring): giữa r_in và r_out là trắng, còn lại cam.
            color = WHITE if r_in ** 2 <= d2 <= r_out ** 2 else ORANGE
            rows.extend(color)
            rows.append(255)  # alpha

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = tag + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(bytes(rows), 9))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    print(f"wrote {path} ({size}x{size})")


if __name__ == "__main__":
    PUBLIC.mkdir(exist_ok=True)
    _png(192, PUBLIC / "pwa-192x192.png")
    _png(512, PUBLIC / "pwa-512x512.png")
    _png(512, PUBLIC / "maskable-512x512.png")
    _png(180, PUBLIC / "apple-touch-icon.png")
