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

    # Auth — khai báo sẵn, skeleton chưa dùng
    jwt_secret: str = "change_me"
    jwt_access_ttl_minutes: int = 30
    jwt_refresh_ttl_days: int = 7


@lru_cache
def get_settings() -> Settings:
    """Singleton settings (cache để không đọc .env nhiều lần)."""
    return Settings()
