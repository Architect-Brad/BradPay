FROM python:3.13-slim

WORKDIR /app

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY backend/ backend/
COPY frontend/ frontend/

EXPOSE 5000

CMD ["gunicorn", "backend.app:create_app", "--worker-class", "gevent", "--bind", "0.0.0.0:5000", "--workers", "2"]
