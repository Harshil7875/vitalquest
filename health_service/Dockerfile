FROM python:3.12-slim

WORKDIR /app

# Install dependencies first for better layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared contracts and service code
COPY ../shared /app/shared
COPY . /app/health_service

ENV PYTHONPATH=/app

CMD ["uvicorn", "health_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
