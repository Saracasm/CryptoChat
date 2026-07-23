from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

class ProfileCreate(BaseModel):
    name: str

class MessageCreate(BaseModel):
    content: str

class ProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    created_at: datetime

class ConversationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    created_at: datetime

class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    role: str
    content: str
    seq: int
    created_at: datetime