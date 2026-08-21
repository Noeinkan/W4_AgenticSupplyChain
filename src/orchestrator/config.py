from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Data backend: "memory" needs nothing installed; "db" uses Postgres and
    # silently falls back to memory when the database is unreachable.
    data_backend: str = "memory"

    # Database
    database_url: str = "postgresql+asyncpg://scuser:scpassword@localhost:5432/supplychain"
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "supplychain"
    db_user: str = "scuser"
    db_password: str = "scpassword"

    # LLM: one of none | ollama | gemini | openai | anthropic.
    # "none" is fully deterministic and costs nothing.
    llm_provider: str = "none"
    llm_model: str = ""  # blank = provider default

    gemini_api_key: str = ""
    google_api_key: str = ""  # accepted as an alias for gemini_api_key
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"

    # External data APIs. IMF PortWatch, NOAA and the Comtrade public preview
    # need no key at all; these unlock the higher-volume sources.
    comtrade_api_key: str = ""
    openweathermap_api_key: str = ""
    newsapi_key: str = ""
    marine_traffic_api_key: str = ""
    enable_ingestion: bool = False

    # NOAA asks unauthenticated clients to identify themselves; requests with a
    # generic agent are throttled. An email address is the convention.
    noaa_user_agent: str = "supply-chain-orchestrator (github.com/agentic-supply-chain)"

    # Cap on live events held in the catalog, so a misbehaving feed cannot grow
    # it without bound.
    ingestion_max_events: int = 250

    # App settings
    debug: bool = False
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # HITL governance
    default_approval_timeout_hours: int = 24
    auto_approve_cost_threshold_usd: float = 10_000.0

    # Simulation
    default_mc_iterations: int = 1000
    max_mc_iterations: int = 50_000

    # Agent engine: the native pipeline runs without LangGraph installed.
    use_langgraph: bool = False

    # Sovereign / air-gapped mode: forces llm_provider to "ollama".
    sovereign_mode: bool = False
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.1:8b"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
