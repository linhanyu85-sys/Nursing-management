from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    service_name: str = "agent-orchestrator"
    service_port: int = 8003
    app_env: str = "local"
    app_version: str = "0.3.0"
    mock_mode: bool = True
    llm_force_enable: bool = False
    local_only_mode: bool = True
    voice_llm_enabled: bool = False

    patient_context_service_url: str = "http://localhost:8002"
    recommendation_service_url: str = "http://localhost:8005"
    document_service_url: str = "http://localhost:8006"
    handover_service_url: str = "http://localhost:8004"
    collaboration_service_url: str = "http://localhost:8011"
    audit_service_url: str = "http://localhost:8007"
    multimodal_service_url: str = "http://localhost:8010"
    default_department_id: str = "dep-card-01"

    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_model_default: str = "qwen-max"
    bailian_model_complex: str = "qwen-plus"

    local_llm_enabled: bool = True
    local_llm_base_url: str = "http://127.0.0.1:9100/v1"
    local_llm_api_key: str = ""
    local_llm_model_primary: str = "minicpm3-4b-q4_k_m"
    local_llm_model_fallback: str = "qwen2.5-3b-instruct-q4_k_m"
    local_llm_model_planner: str = "qwen3-8b"
    local_llm_model_reasoning: str = "deepseek-r1-distill-qwen-7b"
    local_llm_model_custom: str = ""
    local_llm_model_multimodal: str = "medgemma-4b-it"
    local_llm_timeout_sec: int = 35

    agent_runtime_engine: str = "langgraph"
    agent_max_reflection_loops: int = 1
    agent_planner_llm_enabled: bool = True
    agent_planner_timeout_sec: int = 18
    agent_planner_max_steps: int = 8
    agent_memory_recall_limit: int = 6
    agent_queue_worker_enabled: bool = True
    agent_queue_poll_interval_sec: float = 1.0

    model_config = SettingsConfigDict(env_file=".env.local", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
