FROM python:3.12-slim

WORKDIR /app

COPY notification_worker/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared/ /app/shared/
COPY notification_worker/ /app/notification_worker/

ENV PYTHONPATH=/app

CMD ["python", "-m", "notification_worker.main"]
