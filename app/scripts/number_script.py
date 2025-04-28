from datetime import datetime, timedelta, timezone
import asyncio
from app.scripts.script import Script
from app.settings import settings
import httpx
import re
from aiolimiter import AsyncLimiter
from typing import override
from pydantic import BaseModel
from functools import lru_cache
from loguru import logger


class NumberScript(Script):
    def __init__(self):
        self.himera_client = httpx.AsyncClient()
        self.server_client = httpx.AsyncClient()
        self.rate_limiter = AsyncLimiter(max_rate=10, time_period=1)

        self.HIMERA_USERNAME = settings.HIMERA_USERNAME.get_secret_value()
        self.HIMERA_PASSWORD = settings.HIMERA_PASSWORD.get_secret_value()
        self.API_AUTH_URL = settings.API_AUTH_URL
        self.API_FINANCE_URL = settings.API_FINANCE_URL

        self.himera_request_count = 0
        self.database_hit_count = 0
        self.tokens_taken = 0

        self.token_cache = {"token": None, "expiry": None}
        self.token_lock = asyncio.Lock()
        self.record_pattern = re.compile(
            r"^([А-ЯЁа-яё]+\s+[А-ЯЁа-яё]+\s+[А-ЯЁа-яё]+)\s+(\d{2}\.\d{2}\.\d{4})\s*\n(?:Доход:\s*)?([\d.,]+)",
            re.MULTILINE,
        )

    async def get_himera_token(self):
        async with self.token_lock:
            if self.token_cache["token"] and self.token_cache["expiry"] > datetime.now(
                timezone.utc
            ):
                return self.token_cache["token"]

            auth_payload = {
                "username": self.HIMERA_USERNAME,
                "password": self.HIMERA_PASSWORD,
            }
            response = await self.himera_client.post(
                self.API_AUTH_URL, json=auth_payload
            )  # Increment Himera request counter
            self.tokens_taken += 1
            if response.status_code == 200:
                auth_data = response.json()
                token = auth_data.get("token")
                if token:
                    self.token_cache["token"] = token
                    self.token_cache["expiry"] = datetime.now(timezone.utc) + timedelta(
                        hours=1
                    )

                    return token
            return None

    async def fetch_himera_response(
        self,
        lastname: str,
        firstname: str,
        middlename: str,
        birthday: str,
        max_attempts=3,
    ):
        headers = {
            "Authorization": self.token_cache["token"],
            "Content-Type": "application/json",
        }
        payload = {
            "lastname": lastname,
            "firstname": firstname,
            "middlename": middlename,
            "birthday": birthday,
        }

        for attempt in range(1, max_attempts + 1):
            try:
                async with self.rate_limiter:
                    response = await self.himera_client.post(
                        self.API_FINANCE_URL,
                        headers=headers,
                        json=payload,
                    )
                    self.himera_request_count += 1
                    logger.debug("Himera API request")  # Increment Himera request counter
                    if response.status_code == 200:
                        return response.json()
            except Exception:
                await asyncio.sleep(1)
        return {"error": "Ошибка после попыток"}

    async def process_record(self, full_name: str, birthday: str):
        try:
            lastname, firstname, middlename = full_name.strip().split()
        except ValueError:
            return "Ошибка: неверный формат ФИО"

        base_response = await self.get_from_database(
            lastname, firstname, middlename, birthday
        )
        if base_response:
            self.database_hit_count += 1
            phones = await self.extract_phones_from_response(base_response)
            if phones:
                return "\n".join(f"t.me/+{phone} {phone}" for phone in sorted(phones))
            return "Телефоны не найдены."

        response_data = await self.fetch_himera_response(
            lastname, firstname, middlename, birthday
        )
        if "error" in response_data:
            return f"Ошибка: {response_data['error']}"

        await self.add_to_database(
            lastname, firstname, middlename, birthday, response_data
        )

        self.database_hit_count += 1  # Increment database request counter
        phones = await self.extract_phones_from_response(response_data)
        if phones:
            return "\n".join(f"t.me/+{phone} {phone}" for phone in sorted(phones))
        return "Телефоны не найдены."

    async def process_file(self, file_path: str) -> str:
        """Main function for processing a file"""
        token = await self.get_himera_token()
        if not token:
            return "Ошибка авторизации в API"

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        processed_content = await self.process_file_content(content)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(processed_content)

        return processed_content

    async def extract_phones_from_response(self, response: dict):
        phones = response.get("phones", [])
        if not phones:
            return set()
        return {
            f"7{re.sub(r'\D', '', phone)}"
            for phone in phones
            if re.fullmatch(r"9\d{9}", re.sub(r"\D", "", phone))
        }

    async def process_file_content(self, content: str) -> str:
        matches = list(self.record_pattern.finditer(content))
        if not matches:
            return content

        tasks = [
            self.process_record(match.group(1), match.group(2)) for match in matches
        ]
        responses = await asyncio.gather(*tasks)

        new_content = []
        last_end = 0
        for match, response in zip(matches, responses):
            new_content.append(content[last_end : match.end()])
            new_content.append("\n" + response)
            last_end = match.end()
        new_content.append(content[last_end:])

        return "".join(new_content)

    @lru_cache(maxsize=None)
    async def get_from_database(
        self, lastname: str, firstname: str, middlename: str, birthday: str
    ):

        payload = {
            "last_name": lastname,
            "first_name": firstname,
            "middle_name": middlename,
            "birthday": birthday,
        }

        try:  # Применяем лимитер для ngrok
            response = await self.server_client.post(
                f"http://127.0.0.1:8000/get_finance", json=payload
            )

            if response.status_code == 200:
                data: dict = response.json()
                return data.get("finance")
            else:
                logger.warning(f"Ошибка запроса к базе: статус {response.status_code}")
        except Exception as e:
            logger.warning(f"Ошибка при запросе к базе: {e}")
        return None

    async def add_to_database(
        self, lastname, firstname, middlename, birthday, response_data
    ):
        finance_full = {
            "id": None,
            "last_name": lastname,
            "first_name": firstname,
            "middle_name": middlename,
            "birthday": birthday,
            **response_data,
        }
        try:  # Применяем лимитер для ngrok
            response = await self.server_client.post(
                f"http://127.0.0.1:8000/add_finance",
                json=finance_full,
            )
            if response.status_code != 200:
                logger.error(f"Ошибка при отправке: {response.text}")
        except Exception as e:
            logger.error(f"Ошибка при отправке в базу: {e}")

    @override
    class Result(BaseModel):
        file_path: str
        himera_api_reqs: int
        base_hits: int
        tokens_taken: int

    @override
    async def run(self, file_path: str) -> Result:
        await self.process_file(file_path)
        return self.Result(
            file_path=file_path,
            himera_api_reqs=self.himera_request_count,
            base_hits=self.database_hit_count,
            tokens_taken=self.tokens_taken,
        )
