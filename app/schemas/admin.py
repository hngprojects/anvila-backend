import uuid

from pydantic import BaseModel


class UpgradeUserRequest(BaseModel):
    user_id: uuid.UUID
