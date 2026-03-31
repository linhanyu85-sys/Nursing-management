from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "multimodal-med-service"
    service_port: int = 8010
    app_env: str = "local"
    app_version: str = "0.1.0"
    mock_mode: bool = True
    llm_force_enable: bool = False

    medgemma_base_url: str = "http://localhost:8103"
    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_multimodal_model: str = "qwen-vl-max-latest"

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
