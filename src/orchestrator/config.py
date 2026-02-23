from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://scuser:scpassword@localhost:5432/supplychain"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "supplychain"
    db_user: str = "scuser"
    db_password: str = "scpassword"

    # LLM
    anthropic_api_key: str = ""
    openai_api_key: str = ""  # For text-embedding-ada-002

    # External data APIs
    comtrade_api_key: str = ""
    openweathermap_api_key: str = ""
    newsapi_key: str = ""
    marine_traffic_api_key: str = ""

    # App settings
    debug: bool = False
    log_level: str = "INFO"

    # HITL governance
    default_approval_timeout_hours: int = 24
    auto_approve_cost_threshold_usd: float = 10_000.0

    # Simulation
    default_mc_iterations: int = 1000
    max_mc_iterations: int = 10_000

    # Sovereign / air-gapped mode
    sovereign_mode: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3:70b"


settings = Settings()
