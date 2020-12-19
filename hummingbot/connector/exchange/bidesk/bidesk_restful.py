#!/usr/bin/env python
import aiohttp
from aiohttp import ClientSession
import logging
import urllib
from typing import Optional, Dict, Any, Literal

from hummingbot.logger import HummingbotLogger

from hummingbot.connector.exchange.bidesk.bidesk_constants import REST_URL
from hummingbot.connector.exchange.bidesk.bidesk_auth import BideskAuth


class BideskRestFul():
    _logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self, auth: Optional[BideskAuth] = None):
        self._auth: Optional[BideskAuth] = auth
        self._hasAuth = True if self._auth is not None else False
        self._headers = self._auth.get_auth_headers() if self._hasAuth else {}

    async def request(
        self,
        method: Literal["GET", "POST"],
        path: str,
        data: Dict[Any, str] = {}
    ) -> Dict[Any, str]:
        result: Dict[Any, str] = {}
        url = f"{REST_URL}{path}/?{self._auth.gen_auth_dict(data)}" if self._hasAuth else f"{REST_URL}{path}/?{urllib.parse.urlencode(data)}"

        self.logger().debug(f"Requesting {method}: {url}")

        async with aiohttp.ClientSession() as _client:
            client: ClientSession = _client

            resp = await client.request(method, url, headers=self._headers)
            if (resp.status != 200):
                raise IOError(f"Response from {method}:{url} has returned status code {resp.status}")

            result = await resp.json()
            if (type(result) is dict):
                code = result.get("code", None)
                if (code is not None and code < 0):
                    msg = result.get("msg")
                    raise IOError(f"Response from {method}:{url} has returned code {code} with message '{msg}'")

        return result

    async def get(self, path: str, data: Dict[Any, str] = {}) -> Dict[Any, str]:
        return await self.request("GET", path, data)

    async def post(self, path: str, data: Dict[Any, str] = {}) -> Dict[Any, str]:
        return await self.request("POST", path, data)
