from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "asr-service"
    service_port: int = 8008
    app_env: str = "local"
    app_version: str = "0.2.1"
    mock_mode: bool = False
    llm_force_enable: bool = False

    funasr_base_url: str = "http://localhost:8101"
    asr_provider_priority: str = "local_first"
    funasr_timeout_sec: int = 4
    audit_service_url: str = "http://localhost:8007"
    local_asr_enabled: bool = True
    local_asr_model_size: str = "large-v3"
    local_asr_device: str = "cpu"
    local_asr_compute_type: str = "int8"
    local_asr_beam_size: int = 2
    local_asr_timeout_sec: int = 8
    local_asr_warmup_on_startup: bool = True
    local_asr_vad_min_silence_ms: int = 220
    local_asr_vad_speech_pad_ms: int = 100
    local_asr_download_root: str = "./data/local_asr"

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
