FROM python:3.11-slim

WORKDIR /app

# Install deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app
COPY backend/main.py .
COPY frontend/ ./frontend/

# Create data dir
RUN mkdir -p /app/data

ENV EARLY_RISE_DB=/app/data/earlyrise.db
ENV EARLY_RISE_STATIC=./frontend
ENV PORT=8899

EXPOSE 8899

CMD ["python", "main.py"]
