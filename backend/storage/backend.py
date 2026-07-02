from abc import ABC, abstractmethod
from typing import Optional


class StorageBackend(ABC):

    @abstractmethod
    def init_schema(self):
        pass

    # ── Users ──

    @abstractmethod
    def create_user(self, firebase_uid, email=None, display_name=None, phone=None, pin="1234"):
        pass

    @abstractmethod
    def get_user_by_firebase_uid(self, firebase_uid):
        pass

    @abstractmethod
    def get_user_by_id(self, user_id):
        pass

    @abstractmethod
    def verify_pin(self, user_id, pin):
        pass

    @abstractmethod
    def get_balance(self, user_id):
        pass

    @abstractmethod
    def get_user_by_phone_or_email(self, identifier):
        pass

    @abstractmethod
    def get_user_with_locked(self, firebase_uid):
        pass

    @abstractmethod
    def update_kes_balance(self, user_uid, amount_delta):
        pass

    @abstractmethod
    def get_kes_balance(self, user_uid):
        pass

    # ── Transactions ──

    @abstractmethod
    def create_transaction(self, sender_uid, recipient_uid, amount, note=None, offline_id=None):
        pass

    @abstractmethod
    def get_transactions(self, user_id, limit=50):
        pass

    # ── Orders / Trades ──

    @abstractmethod
    def create_order(self, user_uid, order_type, price, amount):
        pass

    @abstractmethod
    def cancel_order(self, user_uid, order_id):
        pass

    @abstractmethod
    def get_orders(self, user_uid, status_filter=None):
        pass

    @abstractmethod
    def get_order_book(self, limit=15):
        pass

    @abstractmethod
    def execute_trade(self, buy_order_id, sell_order_id, buyer_uid, seller_uid, amount, price):
        pass

    @abstractmethod
    def get_trades(self, user_uid=None, limit=50):
        pass

    # ── M-PESA ──

    @abstractmethod
    def create_mpesa_transaction(self, user_uid, type_, phone, amount, checkout_id=None, conversation_id=None):
        pass

    @abstractmethod
    def get_mpesa_transactions(self, user_uid, limit=50):
        pass

    @abstractmethod
    def get_mpesa_transaction_by_checkout_id(self, checkout_id):
        pass

    @abstractmethod
    def get_mpesa_transaction_by_conversation_id(self, conversation_id):
        pass

    @abstractmethod
    def update_mpesa_transaction_status(self, identifier, result_code, result_desc):
        pass

    # ── Agents ──

    @abstractmethod
    def create_agent(self, firebase_uid, business_name, contact_phone=None, email=None, id_number=None, kra_pin=None, location=None):
        pass

    @abstractmethod
    def get_agent(self, firebase_uid):
        pass

    @abstractmethod
    def get_agent_by_id(self, agent_id):
        pass

    @abstractmethod
    def update_agent_status(self, firebase_uid, status):
        pass

    @abstractmethod
    def update_agent_float(self, agent_uid, amount_delta):
        pass

    @abstractmethod
    def get_all_agents(self, status=None):
        pass

    @abstractmethod
    def create_agent_transaction(self, agent_uid, type_, amount, user_uid=None, commission=0, reference=None):
        pass

    @abstractmethod
    def get_agent_transactions(self, agent_uid, limit=50):
        pass

    # ── Tariffs ──

    @abstractmethod
    def create_tariff(self, name, type_, percentage=None, flat_fee=None, min_amount=None, max_amount=None):
        pass

    @abstractmethod
    def get_active_tariffs(self):
        pass

    @abstractmethod
    def get_tariff_by_type(self, type_):
        pass

    @abstractmethod
    def update_tariff(self, tariff_id, **kwargs):
        pass

    # ── BradSec ──

    @abstractmethod
    def log_event(self, event_type, severity="low", uid=None, details=None, ip_address=None, user_agent=None):
        pass

    @abstractmethod
    def get_events(self, limit=50, offset=0, event_type=None, severity=None, uid=None):
        pass

    @abstractmethod
    def count_events(self, event_type=None, severity=None, uid=None):
        pass

    @abstractmethod
    def check_rate_limit(self, uid, action, max_count=10, window_seconds=60):
        pass

    @abstractmethod
    def get_rate_limit_remaining(self, uid, action, max_count=10, window_seconds=60):
        pass

    @abstractmethod
    def reset_rate_limit(self, uid, action):
        pass

    @abstractmethod
    def evaluate_transaction(self, sender_uid, recipient_uid, amount, tx_ref):
        pass

    @abstractmethod
    def get_flagged_transactions(self, status=None, limit=50, offset=0):
        pass

    @abstractmethod
    def resolve_flag(self, flag_id, status, reviewer_uid, note=None):
        pass

    @abstractmethod
    def get_flag_stats(self):
        pass

    @abstractmethod
    def get_security_summary(self):
        pass

    # ── Teardown ──

    @abstractmethod
    def close(self):
        pass
