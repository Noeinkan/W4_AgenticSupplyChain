# supplychain — the Supply-Chain Resilience Orchestrator, behind the owner login.
#
# Two stages: Node builds the dashboard bundle, then one Python container serves
# the FastAPI API and that bundle on the same origin (orchestrator.hosted.app).
# Custom Dockerfile: the pipeline has no Python type, so site.json says "node"
# and BUILD_COMMAND / START_COMMAND are ignored here.

FROM node:20-alpine AS web
WORKDIR /web
COPY repo/web/package.json repo/web/package-lock.json ./
RUN npm ci
COPY repo/web/ ./
RUN npm run build

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DASHBOARD_DIR=/app/web/dist

WORKDIR /app

# Dependencies before source, so editing a route does not reinstall numpy.
COPY repo/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY repo/src/ /app/src/
COPY --from=web /web/dist/ /app/web/dist/

RUN useradd --create-home --uid 10001 app
USER app

EXPOSE 8000
CMD ["uvicorn", "orchestrator.hosted.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
