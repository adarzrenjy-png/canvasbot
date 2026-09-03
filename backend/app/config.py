from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Adaptive Academic Planner"
    database_url: str = f"sqlite:///{ROOT_DIR / 'planner.db'}"
    frontend_origin: str = "http://localhost:5173"
    demo_mode: bool = True
    api_prefix: str = "/api/v1"
    canvas_allowed_origins: str = "https://rutgers.instructure.com,https://netid.rutgers.edu"
    canvas_scan_interval_hours: int = 8
    canvas_worker_model: str = "glm-5.3-flash"
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    mcp_write_token: str = ""
    mcp_remote_enabled: bool = False

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")


settings = Settings()
