# BradPay — The Financial Engine of the Bradverse

Kenyan mobile wallet (KES) with M-PESA integration, P2P transfers, blockchain ledger, and a built-in exchange.

## Features

- **M-PESA Deposits & Withdrawals** — STK Push to top up, B2C to cash out
- **P2P Transfers** — Send KES to any BradPay user by email, phone, or UID
- **BradLedger** — SHA-256 proof-of-work blockchain recording all transactions
- **BradTrade** — Order book exchange for KES P2P trading with automatic matching
- **QR Payments** — Receive money by sharing your QR code
- **BradUSSD** — Feature phone access via Africa's Talking USSD (coming soon)

## Tech Stack

- **Frontend:** Vanilla JS PWA, Firebase Auth
- **Backend:** Flask (Python) REST API
- **Database:** Firestore (primary) / SQLite (fallback)
- **Payments:** Safaricom M-PESA Daraja API
- **Hosting:** Vercel (serverless)

## API

Full API documentation at [/developers.html](https://bradpay.vercel.app/developers.html)

## Deploy

```bash
vercel --prod
```

Set these environment variables on Vercel:

| Variable | Description |
|---|---|
| `FIREBASE_SERVICE_ACCOUNT` | Firebase Admin SDK JSON |
| `MPESA_CONSUMER_KEY` | Daraja API consumer key |
| `MPESA_CONSUMER_SECRET` | Daraja API consumer secret |
| `MPESA_PASSKEY` | M-PESA Paybill passkey |
| `MPESA_SHORTCODE` | M-PESA Paybill number |
| `MPESA_ENV` | `sandbox` or `production` |
