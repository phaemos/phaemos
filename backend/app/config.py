from pydantic_settings import BaseSettings, SettingsConfigDict


# I extend BaseSettings from Pydantic's BaseModel so each field is type-validated automatically
class Settings(BaseSettings):
    # I use SettingsConfigDict to tell pydantic-settings where to load values from
    # env_file=".env" means I read values from a local .env file if present
    # extra="ignore" means I silently discard any .env keys that aren't declared as fields here
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # I require this field - no default means the app won't start if it's missing
    database_url: str
    # I make fields with defaults optional; I use the default when the env var isn't set
    redis_url: str = "redis://localhost:6379"
    # I require secret_key with no default - never hard-code secrets in source code
    secret_key: str
    # I use HS256 (HMAC-SHA256) as the signing algorithm to create and verify JWT tokens
    algorithm: str = "HS256"
    # I shorten access tokens to 15 minutes so a stolen token has minimal blast radius;
    # the refresh token (7-day httpOnly cookie) handles silent renewal.
    access_token_expire_minutes: int = 15
    # I accept a comma-separated list of frontend URLs allowed to call this API via CORS
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

    # -- OAuth providers --
    google_client_id:     str = ""
    google_client_secret: str = ""
    google_redirect_uri:  str = "http://localhost:8000/api/v1/auth/google/callback"
    github_client_id:     str = ""
    github_client_secret: str = ""
    github_redirect_uri:  str = "http://localhost:8000/api/v1/auth/github/callback"

    # -- Notifications --
    discord_webhook_url: str = ""  # leave empty to disable Discord alerts
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""  # recipient address for alert emails

    # -- OTA firmware --
    firmware_storage_path: str = "./firmware_uploads"

    # I use @property to turn this into a read-only attribute so callers write settings.origins not settings.origins()
    @property
    def origins(self) -> list[str]:
        # I split the comma-separated string into a list and strip any accidental whitespace around each entry
        return [o.strip() for o in self.allowed_origins.split(",")]


# I instantiate once at import time; every module that imports 'settings' shares this same object
settings = Settings()
