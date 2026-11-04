FROM node:24.6.0-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PORT=8080
WORKDIR /app
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock
COPY backend/steward ./steward
COPY --from=frontend /app/frontend/dist ./frontend/dist
RUN useradd --create-home --uid 10001 steward
USER steward
ENV FRONTEND_DIST=/app/frontend/dist
CMD ["sh", "-c", "uvicorn steward.app:app --host 0.0.0.0 --port ${PORT}"]
