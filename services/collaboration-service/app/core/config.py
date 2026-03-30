from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = 'collaboration-service'
    service_port: int = 8011
    app_env: str = 'local'
    app_version: str = '0.1.0'
    mock_mode: bool = True

    postgres_dsn: str = 'postgresql+asyncpg://postgres:postgres@localhost:5432/ai_nursing'
    qdrant_url: str = 'http://localhost:6333'
    nats_url: str = 'nats://localhost:4222'
    bailian_api_key: str = ''
    bailian_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    patient_context_service_url: str = 'http://localhost:8002'

    model_config = SettingsConfigDict(env_file='.env.local', env_file_encoding='utf-8', extra='ignore')


settings = Settings()
