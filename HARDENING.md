# Security & Correctness Hardening — Changelog

This addresses every issue raised in review, plus tests proving each fix.

## 1. Race condition on transfers and orders (critical)
`create_transaction` and `create_order` checked the sender's balance, then
updated it as two separate statements, with no lock in between. Two
concurrent requests could both pass the check before either committed,
letting an account go negative.

**Fix:** SQLite now uses `BEGIN IMMEDIATE` plus a conditional
`UPDATE ... WHERE balance >= ?`, so the check and the debit happen as one
atomic step; Firestore now uses a real `@firestore.transactional` function
so the read is re-validated inside the transaction and Firestore retries on
conflict. See `tests/test_transactions.py::test_concurrent_transfers_cannot_overdraw`.

## 2. Tariffs/fees were never applied (functional bug)
The `tariffs` table existed and admins could create fee tiers, but nothing
in the codebase ever read it — `create_transaction` hardcoded `fee = 0`.

**Fix:** added `calculate_fee(type, amount)` (basis-points percentage +
flat fee) to both backends, wired into `create_transaction`. Fees are
credited to a system `__fees__` account so the books stay balanced. See
`tests/test_transactions.py::test_transfer_fee_is_applied`.

## 3. Ledger lost data on serverless cold starts (critical)
The "blockchain" persisted to a JSON file at `/tmp/bradledger.json` by
default, plus an optional Vercel Blob backup that silently no-ops if
`BLOB_READ_WRITE_TOKEN` isn't set (it isn't, by default). On Vercel, `/tmp`
and the process itself reset between invocations, so the ledger could
silently revert to genesis.

**Fix:** the ledger chain now persists through the same data backend as
everything else (`ledger_state` table in SQL / a `system/ledger` doc in
Firestore), so it survives cold starts wherever the app already has a
durable DATABASE_URL/Firestore project configured. The local file is now
just a best-effort dev cache, not the source of truth. See
`tests/test_ledger.py::test_ledger_persists_across_cold_start`.

**Still true:** if you deploy with the default `sqlite:///bradpay.db`, the
SQLite file itself is just as ephemeral on serverless as the old JSON file
was. Use Postgres or Firestore in production — this doesn't fix SQLite's
inherent unsuitability for serverless, it just stops the ledger from being
a special case with its own separate failure mode.

## 4. Insecure default PIN
Registration silently defaulted to PIN `1234` if the client didn't send
one, and there was no check against common/guessable PINs.

**Fix:** PIN is now required and validated (`validators.py`): must be
numeric, ≥4 digits, and not in a short list of commonly-guessed PINs
(`1234`, `0000`, `1111`, etc). Missing or weak PINs return `400` instead of
silently succeeding. Applied identically to both backends.

## 5. CORS wildcard
`CORS(app, resources={r"/api/*": {"origins": "*"}})` allowed any website to
call the API from a logged-in user's browser.

**Fix:** origins now come from `ALLOWED_ORIGINS` (comma-separated env var).
Defaults to `localhost` only if unset, for local dev convenience.

## 6. Placeholder secrets could ship to production
`SECRET_KEY` defaulted to the literal string `change-this-in-production...`
with nothing stopping that from reaching a live deployment.

**Fix:** `app.py` now refuses to start in production
(`FLASK_ENV=production`) if `SECRET_KEY` is missing or is one of the known
placeholder values. Local `.env` now has a real generated key;
`.env.production` is clearly marked as a template with instructions.
`.env`/`.env.production` were already gitignored — added `.env.example` as
the thing that should actually be committed.

## 7. Admin key comparison was not constant-time
`auth.split(" ", 1)[1] != api_key` leaks timing information about how many
characters matched, in principle usable for a timing attack.

**Fix:** switched to `hmac.compare_digest`.

## Verification
All 93 backend tests pass, including 5 new tests added specifically for
these fixes (`test_transfer_fee_is_applied`,
`test_concurrent_transfers_cannot_overdraw`,
`test_ledger_persists_across_cold_start`, plus PIN-rejection tests in
`test_auth.py`). Run with:

```
cd backend
pip install -r requirements.txt
python -m pytest tests/ -q
```

## Bugfix batch (2026-07) — money, authz, USSD, Daraja

Also fixed in a later pass (see `tests/test_bugfixes.py`):

1. **B2C `type=` TypeError** after debiting the user → `type_="withdrawal"`.
2. **M-PESA units** — API uses cents; Daraja gets whole KES (`cents_to_kes` /
   `kes_to_cents`); STK password/timestamp desync fixed.
3. **Dual balances** — deposits/admin/M-PESA now move main `balance`
   (`update_kes_balance` / `get_kes_balance` unified).
4. **Callback idempotency** — `claim_mpesa_callback` only finalizes pending
   txs once (no double credit/refund); B2C timeout refunds once.
5. **Agent authz** — `/agents/verify` and `/agents/all` require admin key.
6. **USSD cumulative text** — uses last `*` segment (Africa's Talking).
7. **Agent money moves** — atomic float topup/transfer/cash-in/out;
   commission conserved from cash-in amount (not minted).
8. **Self-transfer blocked**; **offline_id** idempotent; ledger gets UIDs.
9. **Buy orders lock funds**; no self-match; trade fees to `__fees__`.
10. **Safaricom IP** — `X-Forwarded-For` / `X-Real-IP` for proxied callbacks;
    TEST_MODE bypass for local tests.
11. **Fraud balance_drain** checks `balance` (not `kes_balance`).

## Not fixed (out of scope / lower priority — flagging for visibility)
- `storage/backend.py`, `storage/sqlite_backend.py`, and
  `storage/postgres_backend.py` define a storage abstraction, including
  Postgres support, that nothing in the app actually imports — `data.py`
  only ever chooses between `models.py` (SQLite) and `firestore_db.py`
  based on whether `FIREBASE_SERVICE_ACCOUNT` is set. `DATABASE_URL` is
  read into `Config` but never consulted to pick a backend. In other
  words: despite `render.yaml`/`railway.json` implying Postgres deployment,
  the app currently always runs on local SQLite unless you configure
  Firestore. If you want Postgres in production, that abstraction needs to
  actually be wired into `data.py` — it isn't safe to rely on today.
- USSD sessions remain in-process memory (broken across multi-instance
  serverless without Redis or similar).
