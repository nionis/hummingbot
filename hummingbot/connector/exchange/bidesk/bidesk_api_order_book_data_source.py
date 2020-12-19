#!/usr/bin/env python
import asyncio
import logging
import time
import pandas as pd

from typing import Optional, List, Dict, Any
from hummingbot.core.data_type.order_book import OrderBook
from hummingbot.core.data_type.order_book_message import OrderBookMessage
from hummingbot.core.data_type.order_book_tracker_data_source import OrderBookTrackerDataSource
from hummingbot.logger import HummingbotLogger
from hummingbot.connector.exchange.bidesk.bidesk_restful import BideskRestFul
from hummingbot.connector.exchange.bidesk.bidesk_utils import (
    convert_to_exchange_trading_pair,
    convert_from_exchange_trading_pair,
    ms_timestamp_to_s
)
from hummingbot.connector.exchange.bidesk.bidesk_constants import (
    EXCHANGE_NAME
)
from hummingbot.connector.exchange.bidesk.bidesk_order_book import BideskOrderBook
from hummingbot.connector.exchange.bidesk.bidesk_active_order_tracker import BideskActiveOrderTracker
from hummingbot.connector.exchange.bidesk.bidesk_websocket import BideskWebsocket


class BideskAPIOrderBookDataSource(OrderBookTrackerDataSource):
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
        self._api = BideskRestFul()
        self._trading_pairs: List[str] = trading_pairs
        self._snapshot_msg: Dict[str, Any] = {}

    @classmethod
    async def get_prices(cls) -> Dict[str, float]:
        result: Dict[str, float] = {}
        response: List[Any] = await BideskRestFul().get("/openapi/quote/v1/ticker/price")

        for item in response:
            trading_pair = convert_to_exchange_trading_pair(item.get("symbol"))
            result[trading_pair] = item.get("price")

        return result

    @classmethod
    async def get_last_traded_prices(cls, trading_pairs: List[str]) -> Dict[str, float]:
        result: Dict[str, float] = {}
        prices = await cls.get_prices()

        for trading_pair in trading_pairs:
            exch_trading_pair = convert_to_exchange_trading_pair(trading_pair)
            if (prices.get(exch_trading_pair, None) is None):
                continue
            result[trading_pair] = float(prices.get(exch_trading_pair))

        return result

    @staticmethod
    async def fetch_trading_pairs() -> List[str]:
        trading_pairs: List[str] = []

        try:
            prices = await BideskAPIOrderBookDataSource.get_prices()
            trading_pairs = list(prices.keys())
        except Exception as e:
            print(str(e))
            # Do nothing, there will be no autocomplete
            pass

        return trading_pairs

    @staticmethod
    async def get_order_book_data(trading_pair: str) -> Dict[str, Any]:
        try:
            response = await BideskRestFul().get("/openapi/quote/v1/depth", {
                "symbol": convert_to_exchange_trading_pair(trading_pair),
                "limit": 100  # @TODO: setup limit to 0
            })
            return response
        except Exception as e:
            raise IOError(
                f"Error fetching OrderBook for {trading_pair} at {EXCHANGE_NAME}. ",
                str(e)
            )

    async def get_new_order_book(self, trading_pair: str) -> OrderBook:
        snapshot: Dict[str, Any] = await self.get_order_book_data(trading_pair)
        snapshot_timestamp: float = time.time()
        snapshot_msg: OrderBookMessage = BideskOrderBook.snapshot_message_from_exchange(
            snapshot,
            snapshot_timestamp,
            metadata={"trading_pair": trading_pair}
        )
        order_book = self.order_book_create_function()
        active_order_tracker: BideskActiveOrderTracker = BideskActiveOrderTracker()
        bids, asks = active_order_tracker.convert_snapshot_message_to_order_book_row(snapshot_msg)
        order_book.apply_snapshot(bids, asks, snapshot_msg.update_id)
        return order_book

    async def listen_for_trades(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        """
        Listen for trades using websocket trade channel
        """
        while True:
            try:
                ws = BideskWebsocket()

                await ws.connect()
                await ws.emit({
                    "symbol": ', '.join(map(lambda trading_pair: convert_to_exchange_trading_pair(str(trading_pair)), self._trading_pairs)),
                    "topic": "trade",
                    "event": "sub",
                    "params": {
                        "binary": False
                    }
                })

                async for message in ws.on_message():
                    if message.get("topic") != "trade":
                        continue

                    trading_pair = convert_from_exchange_trading_pair(message.get("symbol"))
                    for trade in message.get("data", list()):
                        trade: Dict[Any] = trade
                        trade_timestamp: int = ms_timestamp_to_s(trade.get("t"))
                        trade_msg: OrderBookMessage = BideskOrderBook.trade_message_from_exchange(
                            trade,
                            trade_timestamp,
                            metadata={"trading_pair": trading_pair}
                        )
                        output.put_nowait(trade_msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(str(e))
                self.logger().error("Unexpected error.", exc_info=True)
                await asyncio.sleep(5.0)
            finally:
                await ws.disconnect()

    async def listen_for_order_book_diffs(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        """
        Listen for orderbook diffs using websocket book channel
        """
        while True:
            try:
                ws = BideskWebsocket()

                await ws.connect()
                await ws.emit({
                    "symbol": ','.join(map(lambda trading_pair: convert_to_exchange_trading_pair(str(trading_pair)), self._trading_pairs)),
                    "topic": "depth",
                    "event": "sub",
                    "params": {
                        "binary": False
                    }
                })

                async for message in ws.on_message():
                    if message.get("topic") != "depth":
                        continue

                    trading_pair = convert_from_exchange_trading_pair(message.get("symbol"))
                    for depth in message.get("data", list()):
                        depth: Dict[Any] = depth
                        depth_timestamp: int = ms_timestamp_to_s(depth.get("t"))

                        orderbook_msg: OrderBookMessage = BideskOrderBook.diff_message_from_exchange(
                            depth,
                            depth_timestamp,
                            metadata={
                                "trading_pair": trading_pair,
                                "bids": depth.get("b"),
                                "asks": depth.get("a")
                            }
                        )
                        output.put_nowait(orderbook_msg)

            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(str(e))
                self.logger().network(
                    "Unexpected error with WebSocket connection.",
                    exc_info=True,
                    app_warning_msg="Unexpected error with WebSocket connection. Retrying in 30 seconds. "
                                    "Check network connection."
                )
                await asyncio.sleep(30.0)
            finally:
                await ws.disconnect()

    async def listen_for_order_book_snapshots(self, ev_loop: asyncio.BaseEventLoop, output: asyncio.Queue):
        """
        Listen for orderbook snapshots by fetching orderbook
        """
        while True:
            try:
                for trading_pair in self._trading_pairs:
                    try:
                        snapshot: Dict[str, any] = await self.get_order_book_data(trading_pair)
                        snapshot_timestamp: int = time.time()
                        snapshot_msg: OrderBookMessage = BideskOrderBook.snapshot_message_from_exchange(
                            snapshot,
                            snapshot_timestamp,
                            metadata={"trading_pair": trading_pair}
                        )
                        output.put_nowait(snapshot_msg)
                        self.logger().debug(f"Saved order book snapshot for {trading_pair}")
                        # Be careful not to go above API rate limits.
                        await asyncio.sleep(5.0)
                    except asyncio.CancelledError:
                        raise
                    except Exception as e:
                        print(str(e))
                        self.logger().network(
                            "Unexpected error with WebSocket connection.",
                            exc_info=True,
                            app_warning_msg="Unexpected error with WebSocket connection. Retrying in 5 seconds. "
                                            "Check network connection."
                        )
                        await asyncio.sleep(5.0)
                this_hour: pd.Timestamp = pd.Timestamp.utcnow().replace(minute=0, second=0, microsecond=0)
                next_hour: pd.Timestamp = this_hour + pd.Timedelta(hours=1)
                delta: float = next_hour.timestamp() - time.time()
                await asyncio.sleep(delta)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                print(str(e))
                self.logger().error("Unexpected error.", exc_info=True)
                await asyncio.sleep(5.0)
