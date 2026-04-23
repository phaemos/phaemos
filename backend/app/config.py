from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    redis_url: str = "redis://localhost:6379"
    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 60
    allowed_origins: str = "http://localhost:3000"
    environment: str = "development"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


settings = Settings()
