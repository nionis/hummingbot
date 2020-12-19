import asyncio
import unittest
from typing import Dict, Any

import conf
from hummingbot.connector.exchange.bidesk.bidesk_auth import BideskAuth
from hummingbot.connector.exchange.bidesk.bidesk_restful import BideskRestFul
from hummingbot.connector.exchange.bidesk.bidesk_websocket import BideskWebsocket


class TestAuth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ev_loop: asyncio.BaseEventLoop = asyncio.get_event_loop()
        api_key = conf.bidesk_api_key
        secret_key = conf.bidesk_secret_key
        cls.auth = BideskAuth(api_key, secret_key)

    async def get_account(self) -> Dict[Any, str]:
        return await BideskRestFul(self.auth).get("/openapi/v1/account")

    async def ws_con_public(self):
        wsClient = await BideskWebsocket().connect()
        await wsClient.emit({
            "symbol": "BTCUSDT",
            "topic": "trade",
            "event": "sub",
            "params": {
                "binary": False
            }
        })

        async for response in wsClient.on_message():
            return wsClient

    async def ws_con_private(self):
        wsClient = await BideskWebsocket(self.auth).connect()
        return wsClient

    def test_restful_auth(self):
        result = self.ev_loop.run_until_complete(self.get_account())
        assert type(result) == dict
        assert type(result["balances"]) == list

    def test_websocket_public(self):
        result = self.ev_loop.run_until_complete(self.ws_con_public())
        assert type(result) is not None

    def test_websocket_private(self):
        result = self.ev_loop.run_until_complete(self.ws_con_private())
        assert type(result) is not None
