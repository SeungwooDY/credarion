from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    app_env: str = "development"
    anthropic_api_key: str | None = None
    invoice_upload_dir: str = "uploads/invoices"
    invoice_ocr_model: str = "claude-haiku-4-5-20251001"

    # --- Auth ---
    # Secret used to sign session tokens. MUST be overridden in production via
    # the AUTH_SECRET_KEY env var; the default below is for local dev only.
    auth_secret_key: str = "dev-insecure-secret-change-me-in-production"
    auth_token_ttl_hours: int = 24
    # Cookie that carries the session token. `secure` should be True in prod
    # (HTTPS only); kept False in dev so it works over http://localhost.
    auth_cookie_name: str = "credarion_session"
    auth_cookie_secure: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}


settings = Settings()  # type: ignore[call-arg]
