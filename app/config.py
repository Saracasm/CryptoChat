from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    openrouter_api_key: str
    openrouter_model: str = "google/gemma-4-26b-a4b-it:free"

    model_config = SettingsConfigDict(env_file=".env")
    
settings = Settings()