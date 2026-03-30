from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "device-gateway"
    service_port: int = 8081
    app_env: str = "local"
    app_version: str = "0.2.2"
    mock_mode: bool = False
    cors_origins: str = "*"

    device_public_ws_url: str = ""
    device_ws_path: str = "/xiaozhi/v1/"
    device_ws_version: int = 3
    device_ws_token: str = ""
    device_response_delay_ms: int = 0
    device_default_stt_text: str = "Voice received. Processing locally."
    device_default_tts_text: str = "Bed 23 is stable. Please continue close observation."
    device_session_prefix: str = "dev"
    device_capture_wait_ms: int = 220
    device_poll_interval_ms: int = 500
    device_poll_timeout_ms: int = 20000
    device_listen_silence_timeout_sec: int = 2
    device_listen_max_duration_sec: int = 7
    device_min_audio_bytes: int = 480
    device_max_audio_buffer_bytes: int = 786432
    device_turn_timeout_ms: int = 40000
    device_min_feedback_audio_bytes: int = 12000
    device_pipeline_mode: str = "realtime"
    device_stt_sample_rate: int = 16000
    device_tts_sample_rate: int = 16000
    device_tts_frame_duration_ms: int = 40
    device_tts_packet_pace_ms: int = 38
    device_tts_sentence_gap_ms: int = 0
    device_tts_max_chars: int = 100
    device_force_silent: bool = False

    firmware_version_floor: str = "0.0.0"
    firmware_url: str = "http://127.0.0.1/firmware-not-used.bin"

    api_gateway_url: str = "http://127.0.0.1:8000"
    asr_service_url: str = "http://127.0.0.1:8008"
    agent_orchestrator_service_url: str = "http://127.0.0.1:8003"
    tts_service_url: str = "http://127.0.0.1:8009"
    device_http_timeout_sec: int = 30
    device_id_default: str = "xiaozhi-device-local"
    device_department_id_default: str = "dep-card-01"
    device_owner_user_id: str = "u_linmeili"
    device_owner_username: str = "linmeili"

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
