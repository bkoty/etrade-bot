
import logging
from typing import List, Dict, Any, Optional

class OrderRotator:
    def __init__(self, api, dry_run: bool=True):
        self.api = api
        self.dry_run = dry_run
        self.log = logging.getLogger("rotator")

    def preview_open_orders(self, account_id_key: str, symbols: Optional[str], side_filter: str) -> List[Dict[str,Any]]:
        sym = None
        if symbols:
            # If multiple, API supports single symbol per call; choose first for preview convenience
            sym = symbols.split(",")[0].strip()
        return self.api.list_open_orders(account_id_key, symbol=sym, count=50, side_filter=side_filter)

    def build_change_payload(self, order: Dict[str,Any], session: str, duration: str) -> Dict[str,Any]:
        # Minimal, correct shape; GUI chooses which fields
        instr = {
            "Product": {"securityType":"EQ", "symbol": order["symbol"]},
            "orderAction": order["side"],
            "quantityType": "QUANTITY",
            "quantity": order["qty"],
        }
        if order.get("priceType","LIMIT").upper()=="LIMIT" and order.get("price") is not None:
            instr["limitPrice"] = float(order["price"])
        req = {
            "PreviewOrderRequest": {
                "orderType": "EQ",
                "clientOrderId": int(time.time()*1000),
                "Order": [{
                    "allOrNone": False,
                    "priceType": order.get("priceType","LIMIT"),
                    "orderTerm": duration,
                    "marketSession": session,
                    "Instrument": [instr],
                }]
            }
        }
        return req
