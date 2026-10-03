FROM node:20-bookworm AS ui
WORKDIR /src
ARG NPM_CONFIG_REGISTRY=http://npm-cache.registry.svc.cluster.local:4873/
ENV NPM_CONFIG_REGISTRY=$NPM_CONFIG_REGISTRY
COPY frontend/package*.json ./
COPY frontend/vendor/ ./vendor/
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ARG PIP_INDEX_URL=http://pip-cache.registry.svc.cluster.local/simple/
ARG PIP_TRUSTED_HOST=pip-cache.registry.svc.cluster.local
ENV PIP_INDEX_URL=$PIP_INDEX_URL \
    PIP_TRUSTED_HOST=$PIP_TRUSTED_HOST
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py auth.py store.py ./
COPY catalog ./catalog
COPY scripts ./scripts
COPY --from=ui /src/dist ./static
RUN useradd --uid 10001 --home-dir /home/atlas --create-home atlas \
    && mkdir -p /data \
    && chown atlas:atlas /data
USER 10001
ENV ATLAS_DB=/data/atlas.db \
    ATLAS_CATALOG=/app/catalog/system.json \
    ATLAS_JWKS_URL=http://shizuha-id.shizuha.svc.cluster.local:8001/.well-known/jwks.json
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
