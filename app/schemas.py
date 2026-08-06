from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from typing import Literal

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


class VisualizationCreate(BaseModel):
    coin: str = Field(min_length=1, max_length=100)
    metric: Literal["price_usd", "daily_change_pct", "market_cap_usd", "volume_usd"] = "price_usd"
    days: int = Field(default=30, ge=1, le=365)


class PortfolioChartCreate(BaseModel):
    chart_type: Literal["allocation", "profit_loss", "cost_vs_value"] = "allocation"


class DataframeInfo(BaseModel):
    columns: list[str]
    row_count: int
    preview: list[dict]


class DataframeListResult(BaseModel):
    dataframes: dict[str, DataframeInfo]


class CustomChartRequest(BaseModel):
    dataframe: Literal["portfolio"] = "portfolio"
    code: str | None = Field(default=None, max_length=4000)
    prompt: str | None = Field(default=None, max_length=500)


class CustomChartResult(BaseModel):
    dataframe: str
    code: str
    chart: dict
    plan: dict | None = None


class DocumentUploadResult(BaseModel):
    document_id: UUID
    filename: str
    chunk_count: int
    char_count: int


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    filename: str
    content_type: str
    created_at: datetime
