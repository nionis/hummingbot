import re
from decimal import Decimal

BITFINEX_REST_URL = "https://api-pub.bitfinex.com/v2"
BITFINEX_REST_AUTH_URL = "https://api.bitfinex.com/v2"
BITFINEX_WS_URI = "wss://api-pub.bitfinex.com/ws/2"
BITFINEX_WS_AUTH_URI = "wss://api.bitfinex.com/ws/2"

TRADING_PAIR_SPLITTER = re.compile(r"^(\w+)(BTC|ETH|BNB|XRP|USD|USDT|USDC|USDS|TUSD|PAX|TRX|BUSD|NGN|LTC|ETC|XMR|DASH)$")


MIN_BASE_AMOUNT_INCREMENT = Decimal("0.01")


class SubmitOrder:
    OID = 0

    def __init__(self, oid):
        self.oid = str(oid)

    @classmethod
    def parse(cls, order_snapshot):
        return cls(order_snapshot[cls.OID])


class ContentEventType:
    ORDER_UPDATE = "ou"
    TRADE_UPDATE = "tu"
    TRADE_EXECUTE = "te"
    WALLET_SNAPSHOT = "ws"
    WALLET_UPDATE = "wu"
    HEART_BEAT = "hb"