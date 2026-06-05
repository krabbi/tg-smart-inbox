FROM python:3.11-slim AS base

WORKDIR /app

# Install only production dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy migration files and entrypoint
COPY alembic/ alembic/
COPY alembic.ini alembic.ini
COPY entrypoint.sh entrypoint.sh
RUN chmod +x entrypoint.sh

# Copy source (overridden by volume mount in dev profile)
COPY bot/ bot/
COPY web/ web/
COPY scripts/ scripts/

ENTRYPOINT ["./entrypoint.sh"]
CMD ["python", "-m", "bot"]

# Dev stage: adds watchfiles on top of the production image
FROM base AS dev
RUN pip install --no-cache-dir watchfiles
