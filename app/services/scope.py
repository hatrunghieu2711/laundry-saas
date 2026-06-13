"""Helper phân giải branch cho thao tác ghi (mở ca, tạo đơn...).

- owner: BẮT BUỘC chỉ định branch_id (owner không gắn cứng branch nào).
- staff/manager/shipper: dùng branch của mình; truyền branch khác -> 403.
"""
import uuid

from app.core.errors import APIError
from app.models.user import User


def resolve_write_branch(actor: User, branch_id: uuid.UUID | None) -> uuid.UUID:
    if actor.role == "owner":
        if branch_id is None:
            raise APIError(400, "BRANCH_REQUIRED", "Owner phải chỉ định branch_id")
        return branch_id
    if actor.branch_id is None:
        raise APIError(400, "BRANCH_REQUIRED", "Tài khoản chưa gắn chi nhánh")
    if branch_id is not None and branch_id != actor.branch_id:
        raise APIError(403, "FORBIDDEN", "Không thể thao tác ở chi nhánh khác")
    return actor.branch_id
