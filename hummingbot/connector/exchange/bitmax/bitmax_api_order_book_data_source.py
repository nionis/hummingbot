#!/usr/bin/env python
import asyncio
import logging
import aiohttp
import websockets
import ujson

from typing import Optional, List, Dict, Any, AsyncIterable
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.core.utils.async_utils import safe_gather
from hummingbot.logger import HummingbotLogger
from hummingbot.connector.exchange.bitmax.bitmax_active_order_tracker import BitmaxActiveOrderTracker
from hummingbot.connector.exchange.bitmax.bitmax_order_book import BitmaxOrderBook
from hummingbot.connector.exchange.bitmax.bitmax_utils import convert_from_exchange_trading_pair, convert_to_exchange_trading_pair, ms_timestamp_to_s
from hummingbot.connector.exchange.bitmax.bitmax_constants import EXCHANGE_NAME, REST_URL, WS_URL


class BitmaxAPIOrderBookDataSource(OrderBookTrackerDataSource):
    MAX_RETRIES = 20
    MESSAGE_TIMEOUT = 30.0
    SNAPSHOT_TIMEOUT = 10.0

    _logger: Optional[HummingbotLogger] = None

    @classmethod
    def logger(cls) -> HummingbotLogger:
        if cls._logger is None:
            cls._logger = logging.getLogger(__name__)
        return cls._logger

    def __init__(self, trading_pairs: List[str] = None):
        super().__init__(trading_pairs)
        self._trading_pairs: List[str] = trading_pairs
        self._snapshot_msg: Dict[str, any] = {}

    @classmethod
    async def get_last_traded_prices(cls, trading_pairs: List[str]) -> Dict[str, float]:
        result = {}

        async with aiohttp.ClientSession() as client:
            resp = await client.get(f"{REST_URL}/ticker")
            if resp.status != 200:
                raise IOError(
                    f"Error fetching last traded prices at {EXCHANGE_NAME}. "
                    f"HTTP status is {resp.status}."
                )

            resp_json = await resp.json()
            if resp_json.get("code") != 0:
                raise IOError(
                    f"Error fetching last traded prices at {EXCHANGE_NAME}. "
                    f"Error is {resp_json.message}."
                )

            for item in resp_json.get("data"):
                trading_pair: str = convert_from_exchange_trading_pair(item.get("symbol"))
                if trading_pair not in trading_pairs:
                    continue

                # we had to calculate mid price
                ask = float(item.get("ask")[0])
                bid = float(item.get("bid")[0])
                result[trading_pair] = (ask + bid) / 2

            return result

    @staticmethod
    async def fetch_trading_pairs() -> List[str]:
        async with aiohttp.ClientSession() as client:
            resp = await client.get(f"{REST_URL}/ticker")

            if resp.status != 200:
                # Do nothing if the request fails -- there will be no autocomplete for kucoin trading pairs
                return []

            data: Dict[str, Dict[str, Any]] = await resp.json()
            return [convert_from_exchange_trading_pair(item["symbol"]) for item in data["data"]]

    @staticmethod
    async def get_order_book_data(trading_pair: str) -> Dict[str, any]:
        """
        Get whole orderbook
        """
        async with aiohttp.ClientSession() as client:
            resp = await client.get(f"{REST_URL}/depth?symbol={convert_to_exchange_trading_pair(trading_pair)}")
            if resp.status != 200:
                raise IOError(
                    f"Error fetching OrderBook for {trading_pair} at {EXCHANGE_NAME}. "
                    f"HTTP status is {resp.status}."
                )

            data: List[Dict[str, Any]] = await safe_gather(resp.json())
            item = data[0]
            if item.get("code") != 0:
                raise IOError(
                    f"Error fetching OrderBook for {trading_pair} at {EXCHANGE_NAME}. "
                    f"Error is {item.message}."
                )

            return item["data"]

    async def get_new_order_book(self, trading_pair: str) -> OrderBook:
        snapshot: Dict[str, Any] = await self.get_order_book_data(trading_pair)
        snapshot_timestamp: float = snapshot.get("data").get("ts")
        snapshot_msg: OrderBookMessage = BitmaxOrderBook.snapshot_message_from_exchange(
            snapshot.get("data"),
            snapshot_timestamp,
            metadata={"trading_pair": trading_pair}
        )
        order_book = self.order_book_create_function()
        active_order_tracker: BitmaxActiveOrderTracker = BitmaxActiveOrderTracker()
        bids, asks = active_order_tracker.convert_snapshot_message_to_order_book_row(snapshot_msg)
        order_book.apply_snapshot(bids, asks, snapshot_msg.update_id)
        return order_book

    async def listen_for_trades(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        while True:
            try:
                trading_pairs = ",".join(list(
                    map(lambda trading_pair: convert_to_exchange_trading_pair(trading_pair), self._trading_pairs)
                ))
                payload = {
                    "op": "sub",
                    "ch": f"trades:{trading_pairs}"
                }

                async with websockets.connect(WS_URL) as ws:
                    ws: websockets.WebSocketClientProtocol = ws
                    await ws.send(ujson.dumps(payload))

                    async for raw_msg in self._inner_messages(ws):
                        try:
                            msg = ujson.loads(raw_msg)
                            if (msg is None or msg.get("m") != "trades"):
                                continue

                            trading_pair: str = convert_from_exchange_trading_pair(msg.get("symbol"))

                            for trade in msg.get("data"):
                                trade_timestamp: int = ms_timestamp_to_s(trade.get("ts"))
                                trade_msg: OrderBookMessage = BitmaxOrderBook.trade_message_from_exchange(
                                    trade,
                                    trade_timestamp,
                                    metadata={"trading_pair": trading_pair}
                                )
                                output.put_nowait(trade_msg)
                        except Exception:
                            raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().debug(str(e))
                self.logger().error("Unexpected error with WebSocket connection. Retrying after 30 seconds...",
                                    exc_info=True)
                await asyncio.sleep(30.0)

    async def listen_for_order_book_diffs(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        while True:
            try:
                trading_pairs = ",".join(list(
                    map(lambda trading_pair: convert_to_exchange_trading_pair(trading_pair), self._trading_pairs)
                ))
                ch = f"bbo:{trading_pairs}"
                payload = {
                    "op": "sub",
                    "ch": ch
                }

                async with websockets.connect(WS_URL) as ws:
                    ws: websockets.WebSocketClientProtocol = ws
                    await ws.send(ujson.dumps(payload))

                    async for raw_msg in self._inner_messages(ws):
                        try:
                            msg = ujson.loads(raw_msg)
                            if (msg is None or msg.get("m") != "bbo"):
                                continue

                            msg_timestamp: int = ms_timestamp_to_s(msg.get("data").get("ts"))
                            trading_pair: str = convert_from_exchange_trading_pair(msg.get("symbol"))
                            order_book_message: OrderBookMessage = BitmaxOrderBook.diff_message_from_exchange(
                                msg.get("data"),
                                msg_timestamp,
                                metadata={"trading_pair": trading_pair}
                            )
                            output.put_nowait(order_book_message)
                        except Exception:
                            raise
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.logger().debug(str(e))
                self.logger().error("Unexpected error with WebSocket connection. Retrying after 30 seconds...",
                                    exc_info=True)
                await asyncio.sleep(30.0)

    async def listen_for_order_book_snapshots(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        while True:
            try:
                trading_pairs = ",".join(list(
                    map(lambda trading_pair: convert_to_exchange_trading_pair(trading_pair), self._trading_pairs)
                ))
                ch = f"depth:{trading_pairs}"
                payload = {
                    "op": "sub",
                    "ch": ch
                }

                async with websockets.connect(WS_URL) as ws:
                    ws: websockets.WebSocketClientProtocol = ws
                    await ws.send(ujson.dumps(payload))

                    async for raw_msg in self._inner_messages(ws):
                        try:
                            msg = ujson.loads(raw_msg)
                            if (msg is None or msg.get("m") != "depth"):
                                continue

                            msg_timestamp: int = ms_timestamp_to_s(msg.get("data").get("ts"))
                            trading_pair: str = convert_from_exchange_trading_pair(msg.get("symbol"))
                            order_book_message: OrderBookMessage = BitmaxOrderBook.snapshot_message_from_exchange(
                                msg.get("data"),
                                msg_timestamp,
                                metadata={"trading_pair": trading_pair}
                            )
                            output.put_nowait(order_book_message)
                        except Exception:
                            raise
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger().error("Unexpected error with WebSocket connection. Retrying after 30 seconds...",
                                    exc_info=True)
                await asyncio.sleep(30.0)

    async def _inner_messages(
        self,
        ws: websockets.WebSocketClientProtocol
    ) -> AsyncIterable[str]:
        # Terminate the recv() loop as soon as the next message timed out, so the outer loop can reconnect.
        try:
            while True:
                try:
                    raw_msg: str = await asyncio.wait_for(ws.recv(), timeout=self.MESSAGE_TIMEOUT)
                    yield raw_msg
                except asyncio.TimeoutError:
                    try:
                        pong_waiter = await ws.ping()
                        await asyncio.wait_for(pong_waiter, timeout=self.PING_TIMEOUT)
                    except asyncio.TimeoutError:
                        raise
        except asyncio.TimeoutError:
            self.logger().warning("WebSocket ping timed out. Going to reconnect...")
            return
        except websockets.ConnectionClosed:
            return
        finally:
            await ws.close()