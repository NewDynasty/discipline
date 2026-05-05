FROM python:3.11-slim

WORKDIR /app

# Install deps
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY backend/main.py .
COPY backend/deps.py .
COPY backend/graph.py .
COPY backend/knowledge_lite.py .
COPY backend/routers/ ./routers/
COPY portal/ /portal/

# Create data dir
RUN mkdir -p /app/data

# Env defaults
ENV EARLY_RISE_DB=/app/data/earlyrise.db
ENV EARLY_RISE_STATIC=/portal
ENV OBSIDIAN_VAULT=/vault
ENV PORT=8899

EXPOSE 8899

CMD ["python", "main.py"]
