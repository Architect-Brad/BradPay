# BradUSSD - USSD menu engine
# Compatible with Africa's Talking USSD API

import logging
from data import (
    get_user_by_phone_or_email,
    get_balance,
    create_transaction,
    verify_pin,
)

logger = logging.getLogger(__name__)

# In-memory session store: {session_id: {"phone": ..., "state": ...}}
_sessions = {}


def _get_session(session_id):
    return _sessions.get(session_id)


def _set_session(session_id, phone, state):
    _sessions[session_id] = {"phone": phone, "state": state}


def _clear_session(session_id):
    _sessions.pop(session_id, None)


def handle_ussd(session_id, phone_number, text):
    phone_number = phone_number.strip()
    normalized_phone = phone_number
    if normalized_phone.startswith("+"):
        normalized_phone = normalized_phone[1:]

    session = _get_session(session_id)

    if text == "" or text is None:
        # New session
        user = get_user_by_phone_or_email(normalized_phone)
        if not user:
            user = get_user_by_phone_or_email(phone_number)
        if not user:
            return _respond("END", "You are not registered on BradPay.\nPlease sign up first at the BradPay app.")

        _set_session(session_id, phone_number, {"state": "main", "user": user})
        return _main_menu()

    parts = text.split("*")
    current_input = parts[0]

    if not session:
        return _respond("END", "Session expired. Please try again.")

    user = session["state"].get("user")

    # Main menu router
    if session["state"].get("state") == "main":
        if current_input == "1":
            return _handle_balance(user)
        elif current_input == "2":
            session["state"] = {"state": "send_phone", "user": user}
            return _respond("CON", "Enter recipient phone:")
        elif current_input == "3":
            return _handle_deposit(user)
        elif current_input == "4":
            return _handle_withdraw()
        elif current_input == "5":
            session["state"] = {"state": "account_menu", "user": user}
            return _account_menu()
        else:
            return _main_menu()

    # Send flow
    if session["state"].get("state") == "send_phone":
        recipient_phone = parts[0] if len(parts) >= 1 else ""
        session["state"] = {"state": "send_amount", "user": user, "recipient_phone": recipient_phone}
        return _respond("CON", "Enter amount (KES):")

    if session["state"].get("state") == "send_amount":
        amount_str = parts[0] if len(parts) >= 1 else "0"
        try:
            amount_cents = int(float(amount_str) * 100)
        except ValueError:
            return _respond("CON", "Invalid amount. Enter amount (KES):")
        if amount_cents < 100:
            return _respond("CON", "Minimum amount is KES 1.00.\nEnter amount (KES):")
        session["state"]["amount"] = amount_cents
        session["state"]["state"] = "send_pin"
        return _respond("CON", f"Send KES {amount_str} to {session['state']['recipient_phone']}?\nEnter your PIN:")

    if session["state"].get("state") == "send_pin":
        pin = parts[0] if len(parts) >= 1 else ""
        if len(pin) < 4:
            return _respond("CON", "Invalid PIN. Enter your PIN:")

        recipient_phone = session["state"]["recipient_phone"]
        amount_cents = session["state"]["amount"]
        sender_uid = user["firebase_uid"]

        if not verify_pin(sender_uid, pin):
            _clear_session(session_id)
            return _respond("END", "Failed: Incorrect PIN.")

        # Normalize recipient phone
        rp = ''.join(c for c in recipient_phone if c.isdigit())
        if rp.startswith('0'):
            rp = '254' + rp[1:]
        if rp.startswith('+'):
            rp = rp[1:]
        if not rp.startswith('254'):
            rp = '254' + rp

        recipient_user = get_user_by_phone_or_email(rp)
        if not recipient_user:
            _clear_session(session_id)
            return _respond("END", f"Failed: Recipient {recipient_phone} not found on BradPay.")

        result = create_transaction(sender_uid, recipient_user["firebase_uid"], amount_cents)
        if isinstance(result, tuple):
            err = result[0].get("error", "Transaction failed")
            _clear_session(session_id)
            return _respond("END", f"Failed: {err}")

        new_balance = get_balance(sender_uid) or 0
        _clear_session(session_id)
        return _respond("END",
            f"Sent KES {amount_cents / 100:.2f} to {recipient_phone}.\n"
            f"New balance: KES {new_balance / 100:.2f}")

    # Account menu
    if session["state"].get("state") == "account_menu":
        if current_input == "1":
            return _respond("END", f"Your UID: {user['firebase_uid']}")
        elif current_input == "2":
            phone_display = user.get("phone", phone_number)
            return _respond("END", f"Your Phone: {phone_display}")
        elif current_input == "3":
            session["state"] = {"state": "main", "user": user}
            return _main_menu()
        else:
            return _account_menu()

    # Fallback
    session["state"] = {"state": "main", "user": user}
    return _main_menu()


def _respond(type_, message):
    return {"response": f"{type_} {message}"}


def _main_menu():
    return _respond("CON",
        "BradPay\n"
        "1. Check Balance\n"
        "2. Send Money\n"
        "3. Deposit\n"
        "4. Withdraw\n"
        "5. My Account")


def _handle_balance(user):
    balance = get_balance(user["firebase_uid"]) or 0
    uid_short = user["firebase_uid"][:8] if len(user["firebase_uid"]) > 8 else user["firebase_uid"]
    return _respond("END",
        f"Your KES balance: KES {balance / 100:.2f}\n"
        f"Your BradPay ID: BP-{uid_short}")


def _handle_deposit(user):
    uid_short = user["firebase_uid"][:8] if len(user["firebase_uid"]) > 8 else user["firebase_uid"]
    return _respond("END",
        "To deposit, use M-PESA Paybill 384384\n"
        f"Account BP-{uid_short}\n"
        "Or visit the BradPay app.")


def _handle_withdraw():
    return _respond("END",
        "To withdraw, visit the BradPay app.")


def _account_menu():
    return _respond("CON",
        "1. My UID\n"
        "2. My Phone\n"
        "3. Back")
