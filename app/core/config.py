"""Cấu hình ứng dụng — đọc từ biến môi trường (.env)."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    app_name: str = "laundry-saas"
    app_env: str = "development"
    debug: bool = False

    # Database (SQLAlchemy async DSN)
    database_url: str

    # Redis
    redis_url: str

    # Auth
    jwt_secret: str = "change_me"
    jwt_algorithm: str = "HS256"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7

    # Cookie (refresh token httpOnly + CSRF double-submit)
    refresh_cookie_name: str = "refresh_token"
    csrf_cookie_name: str = "csrf_token"
    # Path hẹp: cookie refresh chỉ gửi tới các endpoint auth.
    auth_cookie_path: str = "/api/v1/auth"
    cookie_secure: bool = True
    cookie_samesite: str = "strict"

    # Rate limit trang tracking công khai (theo IP, fixed-window Redis).
    public_track_rate_limit: int = 30  # số request tối đa / cửa sổ / IP
    public_track_rate_window: int = 60  # độ dài cửa sổ (giây)

    # Hạn gói (subscription expiry, TÁI DÙNG cột current_period_end). WARN = số ngày
    # TRƯỚC hạn bắt đầu cảnh báo; GRACE = số ngày ÂN HẠN sau hạn (vẫn cho tạo đơn).
    # now > hạn + GRACE → CHẶN tạo đơn. NULL hạn = vô hạn (không bao giờ chặn).
    subscription_warn_days: int = 7
    subscription_grace_days: int = 3

    # Uploads (logo phiếu in). Thư mục nằm trong volume ./:/code → ra host
    # /opt/laundry-saas/uploads; nginx serve trực tiếp tại url_prefix.
    upload_dir: str = "/code/uploads"
    upload_url_prefix: str = "/uploads"
    logo_max_bytes: int = 512 * 1024  # ~500KB ảnh gốc tải lên
    logo_max_px: int = 480            # cạnh lớn nhất sau khi resize (đủ nét 80mm)


@lru_cache
def get_settings() -> Settings:
    """Singleton settings (cache để không đọc .env nhiều lần)."""
    return Settings()
