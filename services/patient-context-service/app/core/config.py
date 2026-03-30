from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = 'patient-context-service'
    service_port: int = 8002
    app_env: str = 'local'
    app_version: str = '0.1.0'
    mock_mode: bool = True
    db_error_fallback_to_mock: bool = False
    mock_case_store_path: str = 'data/mock_patient_cases.json'

    postgres_dsn: str = 'postgresql+asyncpg://postgres:postgres@localhost:5432/ai_nursing'
    include_virtual_empty_beds: bool = False
    virtual_bed_no_start: int = 1
    virtual_bed_no_end: int = 40
    qdrant_url: str = 'http://localhost:6333'
    nats_url: str = 'nats://localhost:4222'
    document_service_url: str = 'http://localhost:8006'
    bailian_api_key: str = ''
    bailian_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'

    model_config = SettingsConfigDict(env_file='.env.local', env_file_encoding='utf-8', extra='ignore')


settings = Settings()
