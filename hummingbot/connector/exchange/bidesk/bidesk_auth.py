import hmac
import hashlib
import urllib
import time
import math
from typing import Dict, Any


class BideskAuth():
    """
    Auth class required by bidesk API
    Learn more at https://github.com/bidesk/bidesk-api-docs/blob/master/doc/REST%20API%20EN.md#endpoint-security-type
    """
    def __init__(self, api_key: str, secret_key: str):
        self.api_key = api_key
        self.secret_key = secret_key

    def gen_auth_dict(self, data: Dict[str, Any] = {}) -> Dict[str, Any]:
        """
        Generates authentication signature and various other data needed by the exchange
        :return: a dictionary of request info including the request signature
        """

        data.update({
            "timestamp": math.floor(time.time() * 1000),
            "recvWindow": 5000
        })

        payload = urllib.parse.urlencode(data)

        data.update({
            "signature": hmac.new(
                self.secret_key.encode("utf-8"),
                payload.encode("utf-8"),
                hashlib.sha256
            ).hexdigest()
        })

        return urllib.parse.urlencode(data)

    def get_auth_headers(self) -> Dict[str, Any]:
        """
        Generates authentication headers required by bidesk
        :return: a dictionary of auth headers
        """

        return {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-BH-APIKEY": self.api_key
        }
