FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

# Copy migration files and entrypoint
COPY alembic/ alembic/
COPY alembic.ini alembic.ini
COPY entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh

# Copy source (overridden by volume mount in dev)
COPY bot/ bot/

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "-m", "bot"]
