from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    openrouter_api_key: str
    openrouter_model: str = "openai/gpt-oss-20b:free"

    model_config = SettingsConfigDict(env_file=".env")
    
settings = Settings()