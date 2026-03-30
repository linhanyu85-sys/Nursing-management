from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "tts-service"
    service_port: int = 8009
    app_env: str = "local"
    app_version: str = "0.2.0"
    mock_mode: bool = False
    llm_force_enable: bool = False

    cosyvoice_base_url: str = "http://localhost:8102"

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
