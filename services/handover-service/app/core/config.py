from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "handover-service"
    service_port: int = 8004
    app_env: str = "local"
    app_version: str = "0.1.0"
    mock_mode: bool = True

    patient_context_service_url: str = "http://localhost:8002"
    audit_service_url: str = "http://localhost:8007"
    postgres_dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_nursing"
    handover_use_postgres: bool = True

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
