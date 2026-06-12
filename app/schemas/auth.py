"""Pydantic v2 schemas cho auth."""
import uuid

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Trả về sau login/refresh. Refresh token nằm ở cookie, KHÔNG ở body."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # giây
    csrf_token: str  # client gửi lại qua header X-CSRF-Token


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID | None
    role: str
    full_name: str
    phone: str
    email: str | None
