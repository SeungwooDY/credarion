from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import model_validator

# Local-dev-only signing key. If this value is still in place in production the
# session-token HMAC is forgeable by anyone who has read the source, so it is
# rejected at startup (see _enforce_production_security).
DEFAULT_AUTH_SECRET = "dev-insecure-secret-change-me-in-production"


class Settings(BaseSettings):
    database_url: str
    app_env: str = "development"
    anthropic_api_key: str | None = None
    invoice_upload_dir: str = "uploads/invoices"
    invoice_ocr_model: str = "claude-haiku-4-5-20251001"

    # --- Auth ---
    # Secret used to sign session tokens. MUST be overridden in production via
    # the AUTH_SECRET_KEY env var; the default below is for local dev only.
    auth_secret_key: str = DEFAULT_AUTH_SECRET
    auth_token_ttl_hours: int = 24
    # Cookie that carries the session token. `secure` should be True in prod
    # (HTTPS only); kept False in dev so it works over http://localhost.
    auth_cookie_name: str = "credarion_session"
    auth_cookie_secure: bool = False

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "prod"}

    @model_validator(mode="after")
    def _enforce_production_security(self) -> "Settings":
        """Fail closed on insecure auth config in production.

        Raises if the default signing key is still in place (token forgery
        risk), and forces the session cookie's Secure flag on so it can never
        traverse plaintext HTTP regardless of the env default.
        """
        if self.is_production:
            if self.auth_secret_key == DEFAULT_AUTH_SECRET:
                raise ValueError(
                    "AUTH_SECRET_KEY must be set to a strong, unique value in "
                    "production; the built-in development default is insecure "
                    "and allows session-token forgery."
                )
            self.auth_cookie_secure = True
        return self


settings = Settings()  # type: ignore[call-arg]
