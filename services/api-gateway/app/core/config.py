from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "api-gateway"
    service_port: int = 8000
    app_env: str = "local"
    app_version: str = "0.1.0"
    mock_mode: bool = True

    cors_origins: str = "*"

    auth_service_url: str = "http://localhost:8012"
    patient_context_service_url: str = "http://localhost:8002"
    agent_orchestrator_service_url: str = "http://localhost:8003"
    handover_service_url: str = "http://localhost:8004"
    recommendation_service_url: str = "http://localhost:8005"
    document_service_url: str = "http://localhost:8006"
    audit_service_url: str = "http://localhost:8007"
    asr_service_url: str = "http://localhost:8008"
    tts_service_url: str = "http://localhost:8009"
    multimodal_service_url: str = "http://localhost:8010"
    collaboration_service_url: str = "http://localhost:8011"
    device_gateway_service_url: str = "http://localhost:8013"

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
