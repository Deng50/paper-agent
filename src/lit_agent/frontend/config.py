"""Frontend settings load .env for local Streamlit, as well as container env vars."""

from pydantic_settings import BaseSettings, SettingsConfigDict


class FrontendSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")
    api_base_url: str = "http://localhost:8000"
    api_token: str = ""


settings = FrontendSettings()
