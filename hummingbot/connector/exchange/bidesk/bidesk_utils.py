import re
import math
from typing import Optional, Tuple

from hummingbot.connector.exchange.bidesk.bidesk_constants import API_REASONS
from hummingbot.client.config.config_var import ConfigVar
from hummingbot.client.config.config_methods import using_exchange

TRADING_PAIR_SPLITTER = re.compile(r"^(\w+)(USDT|BTC|ETH)$")

CENTRALIZED = True

EXAMPLE_PAIR = "BTCUSDT"

# DEFAULT_FEES = [0.1, 0.1]

# HBOT_BROKER_ID = "HBOT-"


# # deeply merge two dictionaries
# def merge_dicts(source: Dict, destination: Dict) -> Dict:
#     for key, value in source.items():
#         if isinstance(value, dict):
#             # get node or create one
#             node = destination.setdefault(key, {})
#             merge_dicts(value, node)
#         else:
#             destination[key] = value

#     return destination


# # join paths
# def join_paths(*paths: List[str]) -> str:
#     return "/".join(paths)


# # get timestamp in milliseconds
# def get_ms_timestamp() -> int:
#     return get_tracking_nonce_low_res()


# convert milliseconds timestamp to seconds
def ms_timestamp_to_s(ms: int) -> int:
    return math.floor(ms / 1e3)


def split_trading_pair(trading_pair: str) -> Optional[Tuple[str, str]]:
    try:
        m = TRADING_PAIR_SPLITTER.match(trading_pair)
        return m.group(1), m.group(2)
    except Exception:
        return None


def convert_from_exchange_trading_pair(exchange_trading_pair: str) -> Optional[str]:
    if split_trading_pair(exchange_trading_pair) is None:
        return None
    base_asset, quote_asset = split_trading_pair(exchange_trading_pair)
    return f"{base_asset}-{quote_asset}"


def convert_to_exchange_trading_pair(hb_trading_pair: str) -> str:
    return hb_trading_pair.replace("-", "")


# def get_new_client_order_id(is_buy: bool, trading_pair: str) -> str:
#     side = "B" if is_buy else "S"
#     return f"{HBOT_BROKER_ID}{side}-{trading_pair}-{get_tracking_nonce()}"


def get_api_reason(code: str) -> str:
    return API_REASONS.get(int(code), code)


KEYS = {
    "bidesk_api_key":
        ConfigVar(key="bidesk_api_key",
                  prompt="Enter your Bidesk API key >>> ",
                  required_if=using_exchange("bidesk"),
                  is_secure=True,
                  is_connect_key=True),
    "bidesk_secret_key":
        ConfigVar(key="bidesk_secret_key",
                  prompt="Enter your Bidesk secret key >>> ",
                  required_if=using_exchange("bidesk"),
                  is_secure=True,
                  is_connect_key=True),
}
