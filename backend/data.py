import os

if os.environ.get("FIREBASE_SERVICE_ACCOUNT"):
    from firestore_db import (
        init_db,
        create_user,
        get_user_by_firebase_uid,
        get_user_by_id,
        verify_pin,
        get_balance,
        create_transaction,
        get_transactions,
        get_user_by_phone_or_email,
        create_order,
        cancel_order,
        get_orders,
        get_order_book,
        execute_trade,
        get_trades,
        get_user_with_locked,
    )
else:
    from models import (
        init_db,
        create_user,
        get_user_by_firebase_uid,
        get_user_by_id,
        verify_pin,
        get_balance,
        create_transaction,
        get_transactions,
        get_user_by_phone_or_email,
        create_order,
        cancel_order,
        get_orders,
        get_order_book,
        execute_trade,
        get_trades,
        get_user_with_locked,
    )
