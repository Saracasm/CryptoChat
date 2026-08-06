

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    openrouter_api_key: str
    gemini_api_key: str

    openrouter_model: str = "inclusionai/ling-3.0-flash:free"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    logfire_token: str | None = None

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()