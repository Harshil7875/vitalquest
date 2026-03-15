FROM python:3.12-slim

WORKDIR /app

COPY health_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared contracts and service code (build context is repo root)
COPY shared/ /app/shared/
COPY health_service/ /app/health_service/

ENV PYTHONPATH=/app

CMD ["uvicorn", "health_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
