from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def is_development_name(environment: str) -> bool:
    # the exact name once trimmed and lower-cased. "prod" or "staging" is never development and neither is
    # an empty or unknown value. Development is something a developer states, never something that is assumed.
    return environment.strip().lower() == "development"


# every relaxation that development allows, in one place. Each one is read through `settings.is_development` or one
# of the properties below, so this list is the whole set. Nothing else behaves differently in development.
DEVELOPMENT_ONLY = (
    "open registration (POST /auth/register and a first provider sign-in), unless REGISTRATION_OPEN says otherwise",
    "the interactive API docs and the schema (/docs, /redoc, /openapi.json)",
    "cookies without the Secure flag",
    "http webhook addresses (a private address is still refused)",
    "the contact form without Turnstile",
    "a SECRET_KEY shorter than 32 characters or with a placeholder word in it",
    "the ?token= form of the live socket address, unless WS_TOKEN_IN_URL says otherwise",
    "INFO level logging of the app's own loggers",
    "emails that cannot be sent are skipped and not treated as a failure",
    "the demo feed (/demo/start and /demo/stop)",
    "a database on this machine or the compose network only (otherwise the start is refused)",
)

# database hosts a development start accepts. Development switches security controls off, so it must not be able
# to run against a database on another machine by mistake
_LOCAL_DATABASE_HOSTS = ("localhost", "127.0.0.1", "::1", "db", "host.docker.internal")


# extend BaseSettings from Pydantic's BaseModel so each field is type-validated automatically
class Settings(BaseSettings):
    # use SettingsConfigDict to tell pydantic-settings where to load values from
    # env_file=".env" means values are read from a local .env file if present
    # extra="ignore" silently discards any .env keys that aren't declared as fields here
    # hide_input_in_errors keeps the value out of a start-up error. Without it pydantic prints the head
    # and tail of the offending input and for a check across settings the whole set of them, which
    # put pieces of the signing key and other secrets in the container log. The error still names
    # the setting and says what is wrong
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

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
    # addresses allowed to set X-Real-IP, normally the reverse proxy. Empty by default: with none configured every
    # forwarded header is ignored and the client is whoever connected. Set it to the one address the proxy connects
    # from (see docs/deployment.md). A broad private range here lets any client choose its own rate limit identity.
    trusted_proxies: str = ""
    # production unless a developer states development. An unset, empty or unknown value is production.
    environment: str = "production"
    # the key used before SECRET_KEY, accepted to VERIFY tokens and decrypt stored secrets only, so the key can be
    # rotated without signing everyone out at once. Remove it once the old tokens have expired (30 days).
    secret_key_previous: str = ""
    # whether every access token must name a live session (the sid claim). Always true outside development. It can
    # be turned off in development only, so tests and tools can mint tokens without a session.
    require_session_id: bool = True
    # log the body of an email that could not be sent (development only). It can hold a link with a token
    log_email_bodies: bool = False
    # whether strangers may create an account (POST /auth/register and a first OAuth sign-in);
    # left unset it follows the environment: open in development, closed everywhere else. An
    # open registration makes a viewer. A viewer reads every machine.
    registration_open: bool | None = None
    # whether the live readings socket still accepts its token in the URL (?token=). The URL form
    # puts the token in proxy and server logs, so it is meant to go once the dashboard sends the
    # token as the first message. Left unset it follows the environment: allowed in development
    # and refused everywhere else.
    ws_token_in_url: bool | None = None
    # most live sockets one account and one address may hold at once. Nginx limits sockets per
    # address too, but not in development, so the API counts them as well.
    # the named limit classes. A limit is "<count>/<second|minute|hour|day>". The default for a route with no limit of its own is
    # `anonymous` for a caller with no credential and `signed_in` for an account or API token. A device key has its own allowance
    # (the ingest limit) and is not counted here
    # the release the API belongs to, shown at GET /. Set by the deploy (the signed tag). The API version is the path (/api/v1)
    release_version: str = "unreleased"
    rate_limit_anonymous: str = "120/minute"
    rate_limit_signed_in: str = "600/minute"
    rate_limit_write: str = "120/minute"
    rate_limit_sensitive: str = "20/hour"
    ws_max_per_user: int = 5
    ws_max_per_address: int = 20
    # a sign-in session ends this many days after it began, however often it is refreshed. A
    # refresh token that is used before it lapses would otherwise keep a copy alive for ever
    session_max_days: int = 30
    # a refresh token that was swapped for a new one is accepted again for this many seconds and gets the same
    # new token back. After that, presenting it is treated as a stolen copy and ends the session
    refresh_grace_seconds: int = 10
    # how often one account may change its sign-in address. Each change mails the old address, so the limit
    # also stops the service being used to mail someone repeatedly
    email_changes_per_hour: int = 3
    email_changes_per_day: int = 5
    # which of the allowed origins may send cookies with a request. Unset it is the first one (the
    # dashboard, which signs in and refreshes with its cookie). The others, such as the public site
    # that only calls the contact route, are allowed without credentials
    credentialed_origins: str = ""

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
    # comma-separated recipients for alert emails
    alert_email_to: str = ""
    # most alert emails and texts one day may send across every device. Each email
    # recipient counts, because Resend's free plan counts them and shares its daily
    # quota with the contact form and invitations.
    alert_email_daily_cap: int = 50
    alert_sms_daily_cap: int = 20
    # one machine's share of each daily cap and the part of it kept for critical alerts. A machine that trips rules all day
    # (a fault or a hostile key) can spend its own share and no more and a warning cannot use the reserve, so another
    # machine's critical alert is still sent. A share is never below 10 messages (or the whole cap when that is smaller) and
    # the reserve applies only to a cap of 10 or more
    alert_machine_share: float = 0.25
    alert_critical_reserve: float = 0.2
    # how long data is kept before the daily retention job deletes it. Open tickets and unresolved alerts are never
    # deleted. A value of 0 keeps that kind of data for ever. Readings are kept for 90 days.
    retention_closed_tickets_days: int = 730      # 24 months, from the ticket's last update
    retention_resolved_alerts_days: int = 365     # 12 months, from the time it was resolved
    retention_audit_days: int = 365               # 12 months
    # where the dashboard is served, with no trailing slash. Invitation links point here.
    dashboard_url: str = "http://localhost:3000"

    # -- Resend email (contact form, invitations, alert emails) --
    # an empty or "placeholder" key means email is not configured
    resend_api_key: str = "placeholder"
    from_email:     str = "no-reply@phaemos.com"

    # -- SMS (Brevo) - graceful no-op when key is empty or placeholder --
    brevo_api_key:   str = ""
    brevo_sms_sender: str = "PHAEMOS"  # max 11 chars, no spaces

    # -- Cloudflare Turnstile (contact form) --
    turnstile_secret_key: str = ""
    contact_email_to: str = "contact@phaemos.com"

    # -- ML model --
    # where the trained model is read and written. The default is the ml/ folder beside the
    # code. Production points it at a mounted volume so a rebuilt container keeps the model.
    model_path: str = str(Path(__file__).resolve().parent.parent / "ml" / "model.pkl")
    # how many machines get an anomaly model of their own, oldest machines first. A machine beyond the cap is scored by its
    # node type's model. A model is about 3.6 MB on disk and about the same in memory in each API worker, so the default of
    # 24 is about 90 MB a worker: 4 workers hold about 350 MB. Raise it only with the memory for it
    ml_max_machine_models: int = 24

    # -- OTA firmware --
    firmware_storage_path: str = "./firmware_uploads"

    # one place that decides what counts as development: the exact name once trimmed and
    # lower-cased. A value such as "prod" or "staging" is therefore never development.
    @property
    def is_development(self) -> bool:
        return is_development_name(self.environment)

    @property
    def ws_token_in_url_allowed(self) -> bool:
        if self.ws_token_in_url is None:
            return self.is_development
        return self.ws_token_in_url

    @property
    def registration_is_open(self) -> bool:
        if self.registration_open is None:
            return self.is_development
        return self.registration_open

    @property
    def session_id_required(self) -> bool:
        return True if not self.is_development else self.require_session_id

    @property
    def trusted_proxy_networks(self) -> list[str]:
        return [n.strip() for n in self.trusted_proxies.split(",") if n.strip()]

    def proxy_mode(self) -> tuple[str, str | None]:
        """How forwarded headers are treated, for the start-up log and a warning when that is risky."""
        networks = self.trusted_proxy_networks
        if not networks:
            return "none: forwarded headers are ignored and the client is whoever connected", None
        text = ", ".join(networks)
        warning = None
        if not self.is_development:
            import ipaddress
            for network in networks:
                net = ipaddress.ip_network(network, strict=False)
                if net.is_private and net.num_addresses > 256:
                    warning = (
                        f"TRUSTED_PROXIES trusts {network}, a wide private range. Any client that reaches the API "
                        "from inside it can choose its own rate limit identity. Trust the one proxy address instead"
                    )
        return f"trusting X-Real-IP from {text}", warning

    # refuse to start with an empty signing key anywhere. Outside development also refuse
    # one that is short or looks like a placeholder or one of the public test keys: every
    # access and refresh token would be forgeable from the example file or this repository.
    @model_validator(mode="after")
    def _refuse_unsafe_secret_key(self) -> "Settings":
        key = self.secret_key.strip().lower()
        if not key:
            raise ValueError("SECRET_KEY must not be empty (generate one with: openssl rand -hex 32)")
        if self.is_development:
            # development switches security controls off, so it only runs against a database on this machine
            from urllib.parse import urlsplit
            host = (urlsplit(self.database_url).hostname or "").lower()
            if host not in _LOCAL_DATABASE_HOSTS:
                raise ValueError(
                    "ENVIRONMENT=development is only allowed with a database on this machine "
                    "(localhost, 127.0.0.1, db or host.docker.internal). Set ENVIRONMENT=production for any other database"
                )
            return self
        weak_words = ("change", "placeholder", "example", "secret", "test")
        if len(key) < 32 or any(word in key for word in weak_words):
            raise ValueError(
                "SECRET_KEY must be a random value of at least 32 characters outside development "
                "(generate one with: openssl rand -hex 32)"
            )
        return self

    # use @property to turn this into a read-only attribute so callers write settings.origins not settings.origins()
    @property
    def credentialed_origin_list(self) -> list[str]:
        if self.credentialed_origins.strip():
            return [o.strip() for o in self.credentialed_origins.split(",") if o.strip()]
        return self.origins[:1]

    @property
    def origins(self) -> list[str]:
        # split the comma-separated string into a list and strip any accidental whitespace around each entry
        return [o.strip() for o in self.allowed_origins.split(",")]


# instantiate once at import time; every module that imports 'settings' shares this same object
settings = Settings()
