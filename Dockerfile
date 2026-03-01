# Stage 1: Build frontend
FROM node:22-alpine AS frontend-builder

WORKDIR /app/frontend

# Install dependencies first (cache layer)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

# Build frontend
COPY frontend/ ./
ARG VITE_BTCPAY_POS_URL
ENV VITE_BTCPAY_POS_URL=${VITE_BTCPAY_POS_URL}
RUN npm run build


# Stage 2: Python runtime
FROM python:3.14-slim AS runtime

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
ENV POETRY_HOME=/opt/poetry
ENV PATH="$POETRY_HOME/bin:$PATH"
RUN curl -sSL https://install.python-poetry.org | python3 - \
    && poetry config virtualenvs.create false

# Install Python dependencies
COPY backend/pyproject.toml backend/poetry.lock* ./
RUN poetry install --only main --no-interaction --no-ansi

# Copy backend code
COPY backend/ ./

# Copy built frontend
COPY --from=frontend-builder /app/frontend/dist ./static

# Make entrypoint executable
RUN chmod +x docker-entrypoint.sh

# Create non-root user
RUN useradd -m -u 1000 app && chown -R app:app /app
USER app

# Environment defaults
ENV DATABASE_URL=sqlite:///./data/secrets.db
ENV CORS_ORIGINS='["https://ieomd.com"]'
ENV LOG_FORMAT=json
ENV LOG_LEVEL=INFO

EXPOSE 8000

# Run migrations and start server
ENTRYPOINT ["./docker-entrypoint.sh"]
