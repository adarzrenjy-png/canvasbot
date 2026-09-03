from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Adaptive Academic Planner"
    database_url: str = f"sqlite:///{ROOT_DIR / 'planner.db'}"
    frontend_origin: str = "http://localhost:5173"
    # Additional browser origins allowed to call the local API. The packaged
    # desktop app loads the UI from disk, and Chromium sends "null" as the
    # Origin for file:// documents.
    extra_ui_origins: str = "null,http://localhost:5173,http://127.0.0.1:5173"
    # Off by default: a new install starts empty and fills from Canvas. Set
    # DEMO_MODE=true to seed the sample courses used by the demo walkthrough.
    demo_mode: bool = False
    api_prefix: str = "/api/v1"
    canvas_allowed_origins: str = "https://rutgers.instructure.com,https://netid.rutgers.edu"
    canvas_scan_interval_hours: int = 8
    canvas_worker_model: str = "glm-5.3-flash"
    zai_base_url: str = "https://api.z.ai/api/paas/v4"
    mcp_write_token: str = ""
    mcp_remote_enabled: bool = False
    # Shared secret the desktop app presents when pushing provider API keys into
    # this process. Generated per launch; empty in development leaves the
    # endpoint open on loopback.
    runtime_token: str = ""

    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    @property
    def allowed_ui_origins(self) -> list[str]:
        """Every browser origin permitted to reach the local API, de-duplicated."""
        origins = [self.frontend_origin, *self.extra_ui_origins.split(",")]
        return list(dict.fromkeys(origin.strip() for origin in origins if origin.strip()))


settings = Settings()
