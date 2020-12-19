#!/usr/bin/env python
import logging
import websockets
import asyncio
import ujson
from typing import Optional, Any, AsyncIterable, Dict

from hummingbot.logger import HummingbotLogger

from hummingbot.connector.exchange.bidesk.bidesk_constants import (
    WSS_URL
)
from hummingbot.connector.exchange.bidesk.bidesk_auth import BideskAuth
from hummingbot.connector.exchange.bidesk.bidesk_restful import BideskRestFul


class BideskWebsocket():
    MESSAGE_TIMEOUT = 30.0
    PING_TIMEOUT = 10.0
    _logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(
        self,
        auth: Optional[BideskAuth] = None
    ):
        self._auth: Optional[BideskAuth] = auth
        self._hasAuth = True if self._auth is not None else False
        self._stream_type = "private" if self._hasAuth else "public"
        self._client: Optional[websockets.WebSocketClientProtocol] = None
        self._restful = BideskRestFul(auth)

    # connect to exchange
    async def connect(self):
        try:
            listenKey: str = None

            # if auth class was passed into websocket class
            # we need to emit authenticated requests
            if self._stream_type == "private":
                res = await self._restful.post("/openapi/v1/userDataStream")
                listenKey = res.get("listenKey", None)

            url: str = f"{WSS_URL}/openapi/quote/ws/v1" if listenKey is None else f"{WSS_URL}/openapi/ws/{listenKey}"
            print(f"Connecting to bidesk websocket using {url}")
            self._client = await websockets.connect(url)

            return self
        except Exception as e:
            print(str(e))
            self.logger().error(f"Websocket error: '{str(e)}'", exc_info=True)

    # disconnect from exchange
    async def disconnect(self):
        if self._client is None:
            return

        await self._client.close()

    # emit messages
    async def emit(self, data: Dict[str, Any] = {}) -> int:
        await self._client.send(ujson.dumps(data))

    # receive & parse messages
    async def on_message(self) -> AsyncIterable[Any]:
        try:
            while True:
                try:
                    raw_msg_str: str = await asyncio.wait_for(self._client.recv(), timeout=self.MESSAGE_TIMEOUT)
                    raw_msg = ujson.loads(raw_msg_str)

                    yield raw_msg
                except asyncio.TimeoutError:
                    await asyncio.wait_for(self._client.ping(), timeout=self.PING_TIMEOUT)
        except asyncio.TimeoutError:
            self.logger().warning("WebSocket ping timed out. Going to reconnect...")
            return
        except websockets.exceptions.ConnectionClosed:
            return
        finally:
            await self.disconnect()
