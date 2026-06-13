"""Schema dùng chung: envelope phân trang cho mọi endpoint danh sách."""
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    """Envelope chuẩn cho list endpoint: items + total + limit/offset."""

    items: list[T]
    total: int
    limit: int
    offset: int
