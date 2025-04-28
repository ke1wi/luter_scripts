from typing import Optional

from pydantic import SecretStr, HttpUrl
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DEVELOPMENT: bool = True
    NGROK_AUTHTOKEN: SecretStr
    PORT: int

    TOKEN: SecretStr
    ADMIN_IDS: list[int]
    TELEGRAM_SECRET: SecretStr
    BASE_URL: HttpUrl = HttpUrl("http://localhost:8000")
    WEBHOOK_PATH: str = "/webhook"

    HIMERA_USERNAME: SecretStr = "cahase3500@hupoi.com"
    HIMERA_PASSWORD: SecretStr = "gcxT79fFI^Fc5zfK"
    API_AUTH_URL: str = "https://himera-search.biz/api/v2/rest/auth/login"
    API_FINANCE_URL: str = (
        "https://himera-search.biz/closed-data/getFinanceDataByFioDob"
    )

    MONGO_URI: str
    MONGO_DB_NAME: str
    MONGO_COLLECTION_NAME: str

    @property
    def WEBHOOK_URL(self) -> str:
        return f"{self.BASE_URL}{self.WEBHOOK_PATH}"

    model_config = SettingsConfigDict(
        env_file=(".env", "stack.env"), env_file_encoding="utf-8", extra="ignore"
    )


settings = Settings()  # ignore: [call-arg]
