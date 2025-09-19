
import logging
import json
import time
from typing import List, Dict, Any, Optional
import requests
from requests_oauthlib import OAuth1Session


def _extract_qty_safely(ro, first_ord, inst):
    """
    Attempts to extract a numeric quantity from various possible E*TRADE fields.
    Returns a float or None.
    """
    def _pick(*keys):
        for k in keys:
            if not k:
                continue
            try:
                v = k
                # if k is a path-like lookup, skip (we already pass values not keys here)
            except Exception:
                v = None
            if v is not None:
                return v
        return None

    # Pull from common locations
    qty_v = None
    try:
        qty_v = (
            (inst or {}).get("quantity")
            or (inst or {}).get("orderedQuantity")
            or (first_ord or {}).get("orderedQuantity")
            or (first_ord or {}).get("quantity")
            or (ro or {}).get("orderedQuantity")
            or (ro or {}).get("quantity")
        )
    except Exception:
        qty_v = None

    # String clean
    if isinstance(qty_v, str):
        if qty_v.strip().lower() in ("", "none", "null", "nan"):
            qty_v = None

    # Convert to float if possible
    try:
        return float(qty_v) if qty_v is not None else None
    except Exception:
        return None


SB = "SB"
PROD = "PROD"

REQ_TOKEN_URL = {
    SB: "https://apisb.etrade.com/oauth/request_token",
    PROD: "https://api.etrade.com/oauth/request_token",
}
AUTH_URL = {
    SB: "https://us.etrade.com/e/t/etws/authorize",
    PROD: "https://us.etrade.com/e/t/etws/authorize",
}
ACCESS_TOKEN_URL = {
    SB: "https://apisb.etrade.com/oauth/access_token",
    PROD: "https://api.etrade.com/oauth/access_token",
}
ACCOUNTS_LIST_URL = {
    SB: "https://apisb.etrade.com/v1/accounts/list.json",
    PROD: "https://api.etrade.com/v1/accounts/list.json",
}
ORDERS_URL = {
    SB: "https://apisb.etrade.com/v1/accounts/{accountIdKey}/orders.json",
    PROD: "https://api.etrade.com/v1/accounts/{accountIdKey}/orders.json",
}
ORDER_CHANGE_PREVIEW = {
    SB: "https://apisb.etrade.com/v1/accounts/{accountIdKey}/orders/{orderId}/change/preview.json",
    PROD: "https://api.etrade.com/v1/accounts/{accountIdKey}/orders/{orderId}/change/preview.json",
}
ORDER_CHANGE_PLACE = {
    SB: "https://apisb.etrade.com/v1/accounts/{accountIdKey}/orders/{orderId}/change/place.json",
    PROD: "https://api.etrade.com/v1/accounts/{accountIdKey}/orders/{orderId}/change/place.json",
}

class ETradeAPI:
    def __init__(self, consumer_key: str, consumer_secret: str, env: str=SB):
        self.consumer_key = consumer_key.strip()
        self.consumer_secret = consumer_secret.strip()
        self.env = env
        self.oauth = OAuth1Session(self.consumer_key, client_secret=self.consumer_secret, callback_uri="oob")
        self.access_token = None
        self.access_token_secret = None
        self.session = None
        self.log = logging.getLogger("etrade_api")

    # --- PIN auth helpers ---
    def get_request_token(self):
        url = REQ_TOKEN_URL[self.env]
        self.log.info("Requesting token at %s", url)
        resp = self.oauth.fetch_request_token(url)
        token = resp["oauth_token"]
        secret = resp["oauth_token_secret"]
        auth_url = AUTH_URL[self.env] + f"?key={self.consumer_key}&token={token}"
        return token, secret, auth_url

    def get_access_token(self, request_token: str, request_secret: str, verifier: str):
        oauth = OAuth1Session(self.consumer_key, client_secret=self.consumer_secret,
                              resource_owner_key=request_token, resource_owner_secret=request_secret)
        url = ACCESS_TOKEN_URL[self.env]
        self.log.info("Exchanging verifier for access token at %s", url)
        tokens = oauth.fetch_access_token(url, verifier=verifier)
        self.access_token = tokens["oauth_token"]
        self.access_token_secret = tokens["oauth_token_secret"]
        # build signed session
        self.session = OAuth1Session(self.consumer_key, client_secret=self.consumer_secret,
                                     resource_owner_key=self.access_token,
                                     resource_owner_secret=self.access_token_secret)
        return self.access_token, self.access_token_secret


def get_transactions(self, account_id_key: str, start_date: str, end_date: str, symbol: str | None = None):
    """Fetch transactions for an account between dates [start_date, end_date].
    Dates can be 'YYYY-MM-DD' or any string; will be converted to MMDDYYYY per E*TRADE API.
    Returns a normalized list of dicts with keys: time, symbol, side, quantity, price, proceeds/amount, fees, orderId/transactionId.
    """
    import datetime as _dt
    import re as _re

    def _to_mmddyyyy(s: str) -> str:
        try:
            if _re.match(r"\d{2}/\d{2}/\d{4}$", s):
                m, d, y = s.split("/"); return f"{m}{d}{y}"
            if _re.match(r"\d{4}-\d{2}-\d{2}$", s):
                y, m, d = s.split("-"); return f"{m}{d}{y}"
        except Exception:
            pass
        try:
            dt = _dt.date.fromisoformat(s)
            return dt.strftime("%m%d%Y")
        except Exception:
            return s  # best effort

    base = "https://apisb.etrade.com" if self.env == SB else "https://api.etrade.com"
    url = f"{base}/v1/accounts/{account_id_key}/transactions.json"
    params = {
        "startDate": _to_mmddyyyy(start_date),
        "endDate": _to_mmddyyyy(end_date),
        "count": 50
    }
    if symbol:
        params["symbol"] = symbol

    out = []
    marker = None
    for _ in range(10):  # safety
        if marker:
            params["marker"] = marker
        resp = self.session.get(url, params=params, headers={"Accept":"application/json"})
        if resp.status_code >= 400:
            self.log.error("Transactions GET failed %s: %s", resp.status_code, resp.text)
            break
        data = resp.json() or {}
        txns = []
        # Expected shapes: TransactionListResponse.Transaction[] OR flattened fields
        try:
            txns = (data.get("TransactionListResponse", {}) or {}).get("Transaction", []) or []
        except Exception:
            txns = []
        for t in txns:
            # normalize
            row = {
                "time": t.get("transactionDate") or t.get("tradeDate") or t.get("date"),
                "symbol": (t.get("symbol") or t.get("symbolDescription") or ""),
                "side": t.get("transactionType") or t.get("type") or t.get("side"),
                "quantity": t.get("quantity") or t.get("shares") or t.get("qty"),
                "price": t.get("price") or t.get("averagePrice") or t.get("avgPrice"),
                "proceeds": t.get("amount") or t.get("proceeds") or 0,
                "fees": (t.get("fees") or 0) + (t.get("commission") or 0),
                "orderId": t.get("orderId"),
                "transactionId": t.get("transactionId") or t.get("id")
            }
            out.append(row)
        # pagination
        marker = (data.get("TransactionListResponse", {}) or {}).get("marker") or None
        more = (data.get("TransactionListResponse", {}) or {}).get("moreTransactions") or False
        if not more:
            break
    return out

    def _get(self, url: str, params: Optional[dict]=None) -> Any:
        resp = self.session.get(url, params=params, headers={"Accept":"application/json"})
        self.log.debug("GET %s → %s", resp.url, resp.status_code)
        if resp.status_code == 204:
            return {}
        resp.raise_for_status()
        return resp.json()

    # Accounts
    def get_accounts(self) -> List[Dict[str,Any]]:
        data = self._get(ACCOUNTS_LIST_URL[self.env])
        acct = data.get("AccountListResponse",{}).get("Accounts",{}).get("Account",[])
        # ensure list
        if isinstance(acct, dict):
            acct = [acct]
        out = []
        for a in acct:
            out.append({
                "idKey": a.get("accountIdKey") or a.get("accountId"),
                "id": a.get("accountId"),
                "name": (a.get("accountName") or a.get("accountDesc") or "").strip() or str(a.get("accountId")),
                "type": a.get("accountType"),
            })
        return out

    # Orders (paged)
    def list_open_orders(self, account_id_key: str, symbol: Optional[str]=None, count:int=50, side_filter: Optional[str]=None) -> List[Dict[str,Any]]:
        url = ORDERS_URL[self.env].format(accountIdKey=account_id_key)
        params = {"status":"OPEN","count":str(count)}
        if symbol:
            params["symbol"]=symbol
        orders: List[Dict[str,Any]] = []
        seen = 0
        marker = None
        raw_pages = 0
        while True:
            q = dict(params)
            if marker:
                q["marker"]=marker
            data = self._get(url, q)
            raw_pages += 1
            resp = data.get("OrdersResponse",{})
            raw_orders = resp.get("Order",[])
            if isinstance(raw_orders, dict):
                raw_orders = [raw_orders]
            # map fields
            for ro in raw_orders:
                # Some payloads nest instruments differently; handle both.
                first_ord = None
                if isinstance(ro.get("OrderDetail"), list) and ro["OrderDetail"]:
                    first_ord = ro["OrderDetail"][0]
                elif isinstance(ro.get("OrderDetail"), dict):
                    first_ord = ro["OrderDetail"]
                inst = None
                if first_ord:
                    if isinstance(first_ord.get("Instrument"), list) and first_ord["Instrument"]:
                        inst = first_ord["Instrument"][0]
                    elif isinstance(first_ord.get("Instrument"), dict):
                        inst = first_ord["Instrument"]
                product = (inst or {}).get("Product",{})
                symbol_v = product.get("symbol")
                action_v = (inst or {}).get("orderAction")
                qty_v = _extract_qty_safely(ro, first_ord, inst)
                limit_v = (inst or {}).get("limitPrice") or first_ord.get("limitPrice")
                stop_v = (inst or {}).get("stopPrice") or first_ord.get("stopPrice")
                side = "BUY" if str(action_v).upper().startswith("BUY") else "SELL" if str(action_v).upper().startswith("SELL") else action_v
                if side_filter and side and side_filter != "BOTH" and side.upper()!=side_filter.upper():
                    continue
                placed = ro.get("orderTime") or ro.get("placedTime") or ro.get("placedTimeUTC") or first_ord.get("orderCreatedTime")
                session = first_ord.get("marketSession") or ro.get("marketSession")
                duration = first_ord.get("orderTerm") or ro.get("orderTerm")
                orders.append({
                    "orderId": ro.get("orderId"),
                    "symbol": symbol_v,
                    "side": side,
                    "qty": qty_v,
                    "price": limit_v or stop_v,
                    "priceType": first_ord.get("priceType"),
                    "session": session,
                    "duration": duration,
                    "placedTime": placed,
                })
                seen += 1
            marker = resp.get("marker")
            if not marker:
                break
        self.log.info("Parsed %d orders across %d raw pages.", len(orders), raw_pages)
        return orders

    # Stubs for rotation (payloads not changed in this snippet)
def preview_change(self, account_id_key: str, order_id: str, payload: dict) -> dict:
    """
    Preview a change to an existing order.
    Try PUT first, then fall back to POST if needed.
    """
    url = ORDER_CHANGE_PREVIEW[self.env].format(accountIdKey=account_id_key, orderId=order_id)
    headers = {"Accept": "application/json"}
    resp = self.session.put(url, json=payload, headers=headers)
    self.log.debug("PUT %s payload: %s", url, json.dumps(payload))
    if resp.status_code in (404, 405):
        resp = self.session.post(url, json=payload, headers=headers)
        self.log.debug("POST %s payload: %s", url, json.dumps(payload))
    resp.raise_for_status()
    return resp.json()

    def place_change(self, account_id_key: str, order_id: str, payload: dict) -> dict:
        url = ORDER_CHANGE_PLACE[self.env].format(accountIdKey=account_id_key, orderId=order_id)
        resp = self.session.post(url, json=payload, headers={"Accept":"application/json"})
        self.log.debug("POST %s payload: %s", url, json.dumps(payload))
        self.log.debug("→ %s %s", resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return resp.json()

def get_transactions(self, account_id_key: str, start_date, end_date, symbol: str | None = None, count: int = 500):
    import datetime as _dt
    def _coerce(d):
        if isinstance(d, _dt.date): return d
        s = str(d)
        try:
            return _dt.datetime.strptime(s, "%Y-%m-%d").date() if "-" in s else _dt.datetime.strptime(s, "%m/%d/%Y").date()
        except Exception:
            return _dt.date.today()
    s = _coerce(start_date); e = _coerce(end_date)

    base = "https://apisb.etrade.com" if self.env == SB else "https://api.etrade.com"
    url = f"{base}/v1/accounts/{account_id_key}/transactions"
    headers = {"Accept":"application/json"}
    params = {"startDate": s.strftime("%m%d%Y"), "endDate": e.strftime("%m%d%Y"), "count": int(count)}
    if symbol: params["symbol"] = symbol

    # Try with dates; if strict 400, retry with {}, then {"count": count}
    r = self.session.get(url, params=params, headers=headers)
    if r.status_code == 400:
        r = self.session.get(url, headers=headers)
        if r.status_code == 400:
            r = self.session.get(url, params={"count": int(count)}, headers=headers)
    r.raise_for_status()
    data = r.json() or {}
    txns = (data.get("TransactionListResponse") or {}).get("Transaction") or data.get("Transaction") or []
    out = []
    for t in txns:
        out.append({
            "time": t.get("transactionDate") or t.get("tradeDate") or t.get("date"),
            "symbol": t.get("symbol") or t.get("productSymbol") or t.get("securitySymbol") or t.get("symbolDescription"),
            "side": t.get("transactionType") or t.get("type") or t.get("side"),
            "quantity": t.get("quantity") or t.get("shares") or t.get("qty"),
            "price": t.get("price") or t.get("averagePrice") or t.get("avgPrice"),
            "proceeds": t.get("amount") or t.get("proceeds") or 0,
            "fees": (t.get("fees") or 0) + (t.get("commission") or 0),
            "orderId": t.get("orderId"),
            "transactionId": t.get("transactionId") or t.get("id")
        })
    return out
