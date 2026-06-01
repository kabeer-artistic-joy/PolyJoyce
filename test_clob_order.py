"""
Diagnostic: validate the deposit-wallet (signature_type=3) order flow end-to-end.

Places a far-from-market limit buy (5 shares at price 0.01) on a current 5-min
crypto market, then immediately cancels. Max exposure if anything goes wrong: $0.05.

Run from the project root:
    .venv/bin/python test_clob_order.py
"""
import os
import time
import requests
from dotenv import load_dotenv
from py_clob_client_v2.client import ClobClient
from py_clob_client_v2.clob_types import OrderArgs, OrderPayload
from py_clob_client_v2.order_builder.constants import BUY
from py_clob_client_v2.order_utils.model.signature_type_v2 import SignatureTypeV2

GAMMA = "https://gamma-api.polymarket.com"
CLOB  = "https://clob.polymarket.com"


def find_live_market():
    """Find a 5-min crypto market closing soon."""
    now = int(time.time())
    next_close = (now // 300 + 1) * 300
    for offset in range(0, 6):
        close_ts = next_close + offset * 300
        for prefix in ["eth-updown-5m", "btc-updown-5m"]:
            slug = f"{prefix}-{close_ts - 300}"
            r = requests.get(f"{GAMMA}/markets?slug={slug}", timeout=10).json()
            if isinstance(r, list) and r:
                m = r[0]
                cid = m.get("conditionId")
                if not cid:
                    continue
                # Pull CLOB-side details
                mc = requests.get(f"{CLOB}/markets/{cid}", timeout=10).json()
                if not mc.get("accepting_orders"):
                    continue
                # Pick first token (doesn't matter which — bid is so low it can't fill)
                tok = mc["tokens"][0]
                return {
                    "slug": slug,
                    "condition_id": cid,
                    "token_id": tok["token_id"],
                    "outcome": tok["outcome"],
                    "min_order_size": mc.get("minimum_order_size", 5),
                    "min_tick": mc.get("minimum_tick_size", 0.01),
                }
    return None


def main():
    load_dotenv("/Users/jonnybelton/conductor/workspaces/5m-poly-bot/miami/.env")
    pk    = os.getenv("POLY_PRIVATE_KEY", "").strip()
    proxy = os.getenv("POLY_PROXY_WALLET", "").strip()
    if not pk or not proxy:
        raise SystemExit("Missing POLY_PRIVATE_KEY or POLY_PROXY_WALLET in .env")
    pk_norm = pk if pk.startswith("0x") else "0x" + pk

    market = find_live_market()
    if not market:
        raise SystemExit("No live 5-min crypto market found")
    print(f"Using market: {market['slug']}")
    print(f"  Token ({market['outcome']}): {market['token_id']}")
    print(f"  Min order size: {market['min_order_size']}  tick: {market['min_tick']}")
    print()

    print(f"Initialising ClobClient with signature_type=POLY_1271 ({SignatureTypeV2.POLY_1271.value})")
    client = ClobClient(
        host=CLOB,
        key=pk_norm,
        chain_id=137,
        signature_type=SignatureTypeV2.POLY_1271,
        funder=proxy,
    )
    client.set_api_creds(client.create_or_derive_api_key())
    print("Auth OK")
    print()

    price = 0.01
    size  = max(5, int(market["min_order_size"]))
    print(f"Placing limit BUY: {size} shares at ${price}  (max cost: ${price * size:.2f})")

    try:
        resp = client.create_and_post_order(
            OrderArgs(token_id=market["token_id"], price=price, size=size, side=BUY)
        )
        print(f"Response: {resp}")
    except Exception as e:
        print(f"FAILED to post order: {e}")
        return

    order_id = resp.get("orderID") or resp.get("orderHash") or resp.get("id")
    status   = resp.get("status")
    print()
    print(f"order_id: {order_id}")
    print(f"status:   {status}")

    if order_id:
        print()
        print("Cancelling immediately...")
        try:
            cancel_resp = client.cancel_order(OrderPayload(orderID=order_id))
            print(f"Cancel response: {cancel_resp}")
        except Exception as e:
            print(f"Cancel failed: {e}")

    print()
    print("=== Open orders after cancel ===")
    try:
        opens = client.get_open_orders()
        print(opens)
    except Exception as e:
        print(f"get_open_orders failed: {e}")


if __name__ == "__main__":
    main()
