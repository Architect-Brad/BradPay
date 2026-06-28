#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-help}"
TERMUX_PYTHON="/data/data/com.termux/files/usr/bin/python3"

case "$MODE" in
  local)
    echo "Starting BradPay locally..."
    cd "$(dirname "$0")"
    if command -v "$TERMUX_PYTHON" &>/dev/null; then
      PYTHON="$TERMUX_PYTHON"
    else
      PYTHON="python3"
    fi
    cd backend && $PYTHON app.py
    ;;

  tunnel)
    echo "Starting BradPay with public tunnel..."
    cd "$(dirname "$0")"
    if command -v "$TERMUX_PYTHON" &>/dev/null; then
      PYTHON="$TERMUX_PYTHON"
    else
      PYTHON="python3"
    fi
    cd backend && $PYTHON app.py &
    APP_PID=$!
    sleep 2

    if command -v cloudflared &>/dev/null; then
      echo "Opening Cloudflare Tunnel..."
      cloudflared tunnel --url http://localhost:5000
    elif command -v ngrok &>/dev/null; then
      echo "Opening ngrok tunnel..."
      ngrok http 5000
    else
      echo "No tunnel tool found. Install one:"
      echo "  cloudflared: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
      echo "  ngrok:       https://ngrok.com/download"
      kill $APP_PID 2>/dev/null
      exit 1
    fi
    kill $APP_PID 2>/dev/null
    ;;

  docker)
    echo "Building Docker image..."
    cd "$(dirname "$0")"
    docker build -t bradpay:latest .
    echo "Running container..."
    docker run -p 5000:5000 -e SECRET_KEY=$(openssl rand -hex 32) bradpay:latest
    ;;

  railway)
    echo "Deploy to Railway:"
    echo "  1. Install Railway CLI: npm i -g @railway/cli"
    echo "  2. railway login"
    echo "  3. railway init"
    echo "  4. railway up"
    ;;

  render)
    echo "Deploy to Render:"
    echo "  1. Push to GitHub"
    echo "  2. Go to https://render.com -> New Web Service"
    echo "  3. Connect repo, use 'render.yaml' or manual config"
    echo "  4. Set SECRET_KEY in environment"
    ;;

  firebase)
    echo "Deploy frontend to Firebase Hosting:"
    echo "  1. npm install -g firebase-tools"
    echo "  2. firebase login"
    echo "  3. firebase init hosting (use 'frontend' as public dir)"
    echo "  4. firebase deploy --only hosting"
    ;;

  help|*)
    echo "BradPay Deployment Script"
    echo ""
    echo "Usage: ./deploy.sh <mode>"
    echo ""
    echo "Modes:"
    echo "  local     Start locally (default)"
    echo "  tunnel    Start + expose via Cloudflare Tunnel / ngrok"
    echo "  docker    Build & run Docker container"
    echo "  railway   Instructions for Railway deployment"
    echo "  render    Instructions for Render deployment"
    echo "  firebase  Instructions for Firebase Hosting"
    echo ""
    echo "Quick start:"
    echo "  ./deploy.sh local"
    echo "  ./deploy.sh tunnel"
    ;;
esac
