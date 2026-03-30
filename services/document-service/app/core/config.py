from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "document-service"
    service_port: int = 8006
    app_env: str = "local"
    app_version: str = "0.1.0"
    mock_mode: bool = True
    llm_force_enable: bool = False
    local_only_mode: bool = True

    patient_context_service_url: str = "http://localhost:8002"
    audit_service_url: str = "http://localhost:8007"
    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_model_default: str = "qwen-max"

    local_llm_enabled: bool = True
    local_llm_base_url: str = "http://127.0.0.1:9100/v1"
    local_llm_api_key: str = ""
    local_llm_model_primary: str = "minicpm3-4b-q4_k_m"
    local_llm_model_fallback: str = "qwen2.5-3b-instruct-q4_k_m"
    local_llm_timeout_sec: int = 35
    postgres_dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/ai_nursing"
    document_use_postgres: bool = True

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
