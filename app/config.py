

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    openrouter_api_key: str

    openrouter_model: str = "inclusionai/ling-3.0-flash:free"

    model_config = SettingsConfigDict(env_file=".env")

settings = Settings()