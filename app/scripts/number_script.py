from datetime import datetime, timedelta, timezone
import asyncio
from app.scripts.script import Script
from app.settings import settings
import httpx
import re
from aiolimiter import AsyncLimiter
from typing import override, Optional, Set, Dict
from pydantic import BaseModel
from loguru import logger
from contextlib import asynccontextmanager
from aiofiles import open as aioopen
from app.exceptions.database import DatabaseException
from httpx import PoolTimeout


class NumberScript(Script):
    def __init__(self):
        self.himera_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self.server_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
        self.himera_limiter = AsyncLimiter(max_rate=10, time_period=1)

        self.get_semaphore = asyncio.Semaphore(50)
        self.add_semaphore = asyncio.Semaphore(10)

        # Load settings once
        self.HIMERA_USERNAME = settings.HIMERA_USERNAME.get_secret_value()
        self.HIMERA_PASSWORD = settings.HIMERA_PASSWORD.get_secret_value()
        self.API_AUTH_URL = settings.API_AUTH_URL
        self.API_FINANCE_URL = settings.API_FINANCE_URL

        # Metrics
        self.himera_request_count = 0
        self.database_hit_count = 0
        self.tokens_taken = 0

        # Token caching
        self.token_cache = {"token": None, "expiry": None}
        self.token_lock = asyncio.Lock()

        # Pre-compiled regex patterns
        self.record_pattern = re.compile(
            r"^([А-ЯЁа-яё]+\s+[А-ЯЁа-яё]+\s+[А-ЯЁа-яё]+)\s+(\d{2}\.\d{2}\.\d{4})\s*\n(?:Доход:\s*)?([\d.,]+)",
            re.MULTILINE,
        )
        self.phone_clean_pattern = re.compile(r"\D")
        self.phone_validate_pattern = re.compile(r"^9\d{9}$")

    @asynccontextmanager
    async def _get_token_context(self):
        """Context manager for token handling with automatic refresh."""
        async with self.token_lock:
            now = datetime.now(timezone.utc)
            if not self.token_cache["token"] or self.token_cache["expiry"] <= now:
                await self._refresh_token()
            yield self.token_cache["token"]

    async def _refresh_token(self):
        """Refresh the authentication token."""
        auth_payload = {
            "username": self.HIMERA_USERNAME,
            "password": self.HIMERA_PASSWORD,
        }
        response = await self.himera_client.post(self.API_AUTH_URL, json=auth_payload)
        self.tokens_taken += 1

        if response.status_code == 200:
            auth_data = response.json()
            if token := auth_data.get("token"):
                self.token_cache = {
                    "token": token,
                    "expiry": datetime.now(timezone.utc) + timedelta(hours=1),
                }

    async def fetch_himera_response(
        self,
        lastname: str,
        firstname: str,
        middlename: str,
        birthday: str,
        max_attempts: int = 3,
    ) -> Dict:
        """Fetch data from Himera API with retry logic."""
        headers = {
            "Authorization": f"Bearer {self.token_cache['token']}",
            "Content-Type": "application/json",
        }
        payload = {
            "lastname": lastname,
            "firstname": firstname,
            "middlename": middlename,
            "birthday": birthday,
        }

        last_exception = None
        for attempt in range(max_attempts):
            try:
                async with self.himera_limiter:
                    response = await self.himera_client.post(
                        self.API_FINANCE_URL,
                        headers=headers,
                        json=payload,
                    )
                    self.himera_request_count += 1

                    if response.status_code == 200:
                        return response.json()
                    elif response.status_code == 401:
                        await self._refresh_token()
                        headers["Authorization"] = f"Bearer {self.token_cache['token']}"
            except Exception as e:
                last_exception = e
                await asyncio.sleep(min(attempt * 0.5, 2))  # Exponential backoff

        return {
            "error": str(last_exception) if last_exception else "Ошибка после попыток"
        }

    async def process_record(self, full_name: str, birthday: str) -> str:
        """Process a single record with enhanced logging."""
        try:
            lastname, firstname, middlename = full_name.strip().split()
        except ValueError:
            logger.warning(f"Invalid name format: {full_name}")
            return "Ошибка: неверный формат ФИО"

        logger.debug(
            f"Processing record: {lastname} {firstname} {middlename} {birthday}"
        )

        # Try database first
        if base_response := await self.get_from_database(
            lastname, firstname, middlename, birthday
        ):
            self.database_hit_count += 1
            if phones := await self.extract_phones_from_response(base_response):
                return self._format_phones(phones)
            return "Телефоны не найдены."
        else:
            logger.debug("Not found in database, querying API")

        # Fallback to API
        response_data = await self.fetch_himera_response(
            lastname, firstname, middlename, birthday
        )
        if "error" in response_data:
            logger.error(f"API error: {response_data['error']}")
            return f"Error: {response_data['error']}"

        logger.debug("Caching API response in database")
        asyncio.create_task(
            self.add_to_database(
                lastname, firstname, middlename, birthday, response_data
            )
        )

        if phones := await self.extract_phones_from_response(response_data):
            return self._format_phones(phones)

        logger.debug("No phones found")
        return "Телефоны не найдены."

    def _format_phones(self, phones: Set[str]) -> str:
        """Format phone numbers for output."""
        return "\n".join(f"t.me/+{phone} {phone}" for phone in sorted(phones))

    async def process_file(self, file_path: str) -> str:
        """Process file content and return formatted results."""
        async with self._get_token_context():
            if not self.token_cache["token"]:
                return "Ошибка авторизации в API"

            try:
                async with aioopen(file_path, "r", encoding="utf-8") as f:
                    content = await f.read()

                processed_content = await self.process_file_content(content)

                async with aioopen(f"_{file_path}", "w", encoding="utf-8") as f:
                    await f.write(processed_content)

                return processed_content
            except IOError as e:
                logger.error(f"File processing error: {e}")
                return f"Ошибка обработки файла: {e}"

    async def extract_phones_from_response(self, response: Dict) -> Set[str]:
        """Extract and validate phone numbers from API response."""
        phones = response.get("phones", [])
        if not phones:
            return set()

        result = set()
        for phone in phones:
            cleaned = self.phone_clean_pattern.sub("", phone)
            if self.phone_validate_pattern.fullmatch(cleaned):
                result.add(f"7{cleaned}")
        return result

    async def process_file_content(self, content: str) -> str:
        """Process file content and append phone numbers."""
        matches = list(self.record_pattern.finditer(content))
        if not matches:
            return content

        # Process records in parallel
        tasks = [
            self.process_record(match.group(1), match.group(2)) for match in matches
        ]
        responses = await asyncio.gather(*tasks)

        # Rebuild content with responses
        parts = []
        last_end = 0
        for match, response in zip(matches, responses):
            parts.append(content[last_end : match.end()])
            parts.append("\n" + response)
            last_end = match.end()
        parts.append(content[last_end:])

        return "".join(parts)

    async def get_from_database(
        self, lastname: str, firstname: str, middlename: str, birthday: str
    ) -> Optional[Dict]:
        """Retrieve data from local database with improved logging."""
        payload = {
            "last_name": lastname,
            "first_name": firstname,
            "middle_name": middlename,
            "birthday": birthday,
        }

        try:
            async with self.get_semaphore:
                finance_id = self._generate_record_id(
                    lastname, firstname, middlename, birthday
                )
                response = await self.server_client.post(
                    f"http://127.0.0.1:8000/get_finance/{finance_id}",
                    json=payload,
                )

                if response.status_code == 200:
                    data = response.json()
                    if finance_data := data.get("finance"):
                        return finance_data
                    logger.warning(f"{payload}")
                else:
                    logger.warning(
                        f"Database error: status {response.status_code}, response: {response.text}"
                    )
        except PoolTimeout as e:
            raise DatabaseException(e)
        except Exception as e:
            logger.error(f"Database request failed: {repr(e)}")
        return None

    async def add_to_database(
        self,
        lastname: str,
        firstname: str,
        middlename: str,
        birthday: str,
        response_data: Dict,
    ) -> None:
        """Add data to local database with required ID field."""
        # Генерируем уникальный ID на основе ФИО и даты рождения
        record_id = self._generate_record_id(lastname, firstname, middlename, birthday)

        finance_full = {
            "id": record_id,
            "last_name": lastname,
            "first_name": firstname,
            "middle_name": middlename,
            "birthday": birthday,
            **response_data,
        }

        try:
            async with self.add_semaphore:
                response = await self.server_client.post(
                    "http://127.0.0.1:8000/add_finance", json=finance_full, timeout=10.0
                )

                if response.status_code == 200:
                    logger.debug("Successfully added to database")
                else:
                    logger.error(
                        f"Database add error: {response.status_code}, response: {response.text}"
                    )
        except Exception as e:
            logger.error(f"Database add failed: {repr(e)}")

    def _generate_record_id(
        self, lastname: str, firstname: str, middlename: str, birthday: str
    ) -> str:
        """Generate consistent unique ID based on personal data."""
        from hashlib import sha256
        import json

        # Создаем строку для хеширования
        data_str = json.dumps(
            {
                "last_name": lastname.lower().strip(),
                "first_name": firstname.lower().strip(),
                "middle_name": middlename.lower().strip(),
                "birthday": birthday.strip(),
            },
            sort_keys=True,
            ensure_ascii=False,
        )

        # Генерируем SHA256 хеш
        return sha256(data_str.encode("utf-8")).hexdigest()

    @override
    class Result(BaseModel):
        file_path: str
        himera_api_reqs: int
        base_hits: int
        tokens_taken: int

    @override
    async def run(self, file_path: str) -> Result:
        """Main execution method."""
        await self.process_file(file_path)
        return self.Result(
            file_path=file_path,
            himera_api_reqs=self.himera_request_count,
            base_hits=self.database_hit_count,
            tokens_taken=self.tokens_taken,
        )
