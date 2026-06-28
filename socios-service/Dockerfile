FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# REST + gRPC
EXPOSE 8001 9001

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "infrastructure/adapters/inbound/api.py"]
