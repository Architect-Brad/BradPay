import os


def get_orders_at_price(order_type, price):
    if os.environ.get("FIREBASE_SERVICE_ACCOUNT"):
        from firestore_db import _orders_collection
        db = _orders_collection().parent
        results = []
        for status in ("open", "partial"):
            docs = (
                db.collection("orders")
                .where("type", "==", order_type)
                .where("price", "==", price)
                .where("status", "==", status)
                .stream()
            )
            for d in docs:
                results.append({"id": d.id, **d.to_dict()})
        results.sort(key=lambda x: x.get("created_at", ""))
        return results
    else:
        from models import get_db
        conn = get_db()
        rows = conn.execute(
            """SELECT id, user_uid, amount, filled, price, type
               FROM orders WHERE type=? AND price=? AND status IN ('open','partial')
               ORDER BY created_at ASC""",
            (order_type, price),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]


def match_orders(new_order):
    """Called after a new order is placed. Checks if any orders can be matched."""
    from data import get_order_book, execute_trade

    order_book = get_order_book(limit=50)
    bids = order_book.get("bids", [])
    asks = order_book.get("asks", [])

    if not bids or not asks:
        return []

    results = []
    for bid in bids:
        for ask in asks:
            if bid["price"] < ask["price"]:
                continue
            match_amount = min(bid["amount"], ask["amount"])
            if match_amount <= 0:
                continue

            bid_orders = get_orders_at_price("buy", bid["price"])
            ask_orders = get_orders_at_price("sell", ask["price"])

            for bo in bid_orders:
                for ao in ask_orders:
                    if match_amount <= 0:
                        break
                    if bo.get("user_uid") and bo.get("user_uid") == ao.get("user_uid"):
                        continue
                    bo_remaining = bo["amount"] - bo.get("filled", 0)
                    ao_remaining = ao["amount"] - ao.get("filled", 0)
                    fill = min(bo_remaining, ao_remaining, match_amount)
                    if fill <= 0:
                        continue

                    trade_result = execute_trade(
                        buy_order_id=bo["id"],
                        sell_order_id=ao["id"],
                        buyer_uid=bo["user_uid"],
                        seller_uid=ao["user_uid"],
                        amount=fill,
                        price=min(bid["price"], ask["price"]),
                    )
                    if trade_result.get("success"):
                        results.append(trade_result)
                        match_amount -= fill
                        bid["amount"] -= fill
                        ask["amount"] -= fill
                if match_amount <= 0:
                    break

    return results
