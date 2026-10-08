from pydantic_settings import BaseSettings, SettingsConfigDict


# extend BaseSettings from Pydantic's BaseModel so each field is type-validated automatically
class Settings(BaseSettings):
    # use SettingsConfigDict to tell pydantic-settings where to load values from
    # env_file=".env" means values are read from a local .env file if present
    # extra="ignore" silently discards any .env keys that aren't declared as fields here
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # require this field - no default means the app won't start if it's missing
    database_url: str
    # make fields with defaults optional; the default applies when the env var isn't set
    redis_url: str = "redis://localhost:6379"
    # require secret_key with no default - never hard-code secrets in source code
    secret_key: str
    # use HS256 (HMAC-SHA256) as the signing algorithm to create and verify JWT tokens
    algorithm: str = "HS256"
    # shorten access tokens to 15 minutes so a stolen token has minimal blast radius;
    # the refresh token (7-day httpOnly cookie) handles silent renewal.
    access_token_expire_minutes: int = 15
    # accept a comma-separated list of frontend URLs allowed to call this API via CORS
    allowed_origins: str = "http://localhost:3000"
    # addresses allowed to set X-Real-IP, normally the reverse proxy. The private
    # ranges cover Nginx reaching the API through Docker's network or the host.
    trusted_proxies: str = "127.0.0.1/32,::1/128,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    environment: str = "development"

    # -- OAuth providers --
    google_client_id:     str = ""
    google_client_secret: str = ""
    google_redirect_uri:  str = "http://localhost:8000/api/v1/auth/google/callback"
    github_client_id:     str = ""
    github_client_secret: str = ""
    github_redirect_uri:  str = "http://localhost:8000/api/v1/auth/github/callback"
    microsoft_client_id:     str = ""
    microsoft_client_secret: str = ""
    microsoft_redirect_uri:  str = "http://localhost:8000/api/v1/auth/microsoft/callback"
    # "common" accepts personal and work or school accounts; a tenant id limits sign-in to one organisation
    microsoft_tenant:        str = "common"

    # -- Notifications --
    discord_webhook_url: str = ""  # leave empty to disable Discord alerts
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alert_email_to: str = ""  # recipient address for alert emails

    # -- Resend email (invitation flow) - graceful no-op when key is placeholder --
    resend_api_key: str = "placeholder"
    from_email:     str = "no-reply@phaemos.com"

    # -- SMS (Brevo) - graceful no-op when key is empty or placeholder --
    brevo_api_key:   str = ""
    brevo_sms_sender: str = "PHAEMOS"  # max 11 chars, no spaces

    # -- Cloudflare Turnstile (contact form) --
    turnstile_secret_key: str = ""
    contact_email_to: str = "contact@phaemos.com"

    # -- OTA firmware --
    firmware_storage_path: str = "./firmware_uploads"

    # use @property to turn this into a read-only attribute so callers write settings.origins not settings.origins()
    @property
    def origins(self) -> list[str]:
        # split the comma-separated string into a list and strip any accidental whitespace around each entry
        return [o.strip() for o in self.allowed_origins.split(",")]


# instantiate once at import time; every module that imports 'settings' shares this same object
settings = Settings()
