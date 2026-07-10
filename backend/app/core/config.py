from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/strategos_db"
    REDIS_URL: str = "redis://localhost:6379/0"

    # App environment (align with client-portal APP_ENV)
    APP_ENV: str = "development"

    # JWT settings
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30  # Token expires in 30 minutes
    ALGORITHM: str = "HS256"  # JWT algorithm

    # Email settings
    # Resend settings
    RESEND_FROM_EMAIL: str = "noreply@example.com"
    RESEND_API_KEY: str = "your-resend-key"

    # Frontend URL for email links (verification, password reset, etc.)
    FRONTEND_URL: str = "http://localhost:3000"

    # The actual key should be in the environment variable or .env file
    SECRET_KEY: str = "fallback-secret-c3d4e5f60718293a4b5c6d7e8f90a1b2c3d4e5f60718293a4b5c6d7e8f90"

    # CORS settings as list of strings
    CORS_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:3002"]

    # Sentry settings (align with client-portal naming where possible)
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.0
    SENTRY_PROFILES_SAMPLE_RATE: float = 0.0

    # Business Central integration mode. "mock" (default) serves committed
    # fixtures with no network calls or credentials; "live" talks to the real
    # Business Central REST API using the BC_* settings below.
    BUSINESS_CENTRAL_MODE: str = "mock"

    # Business Central live-client connection settings. Only consulted when
    # BUSINESS_CENTRAL_MODE="live". Tenant/company IDs and credentials are blank
    # by default and MUST come from the environment (.env, git-ignored) — never
    # commit real values. Publisher/group/version/environment carry the confirmed
    # non-secret defaults for the Strategos custom API (see docs/postman/).
    BC_TENANT_ID: str = ""
    BC_ENVIRONMENT: str = "RESTSTR"
    BC_COMPANY_ID: str = ""
    BC_CLIENT_ID: str = ""
    BC_CLIENT_SECRET: str = ""
    BC_PUBLISHER: str = "strategos"
    BC_API_GROUP: str = "integrations"
    BC_API_VERSION: str = "v1.0"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
