
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    openrouter_api_key: str
    gemini_api_key: str

    openrouter_model: str = "inclusionai/ling-3.0-flash:free"
    gemini_embedding_model: str = "gemini-embedding-001"
    embedding_dimensions: int = 768
    logfire_token: str | None = None
    # Comma-separated list, e.g. "http://localhost:3000,http://1.2.3.4:3000".
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

settings = Settings()