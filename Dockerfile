FROM python:3.12-slim AS backend-test
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=$PIP_INDEX_URL PIP_TRUSTED_HOST=$PIP_TRUSTED_HOST
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt
COPY app.py auth.py store.py token_revocation.py ./
COPY catalog ./catalog
COPY tests ./tests
RUN python -m pytest -q tests

FROM node:20-bookworm AS ui
WORKDIR /src
ARG NPM_CONFIG_REGISTRY=https://registry.npmjs.org/
ENV NPM_CONFIG_REGISTRY=$NPM_CONFIG_REGISTRY
COPY frontend/package*.json ./
COPY frontend/vendor/ ./vendor/
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
ARG PIP_INDEX_URL=https://pypi.org/simple
ARG PIP_TRUSTED_HOST=
ENV PIP_INDEX_URL=$PIP_INDEX_URL \
    PIP_TRUSTED_HOST=$PIP_TRUSTED_HOST
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --from=backend-test /app/app.py /app/auth.py /app/store.py /app/token_revocation.py ./
COPY catalog ./catalog
COPY scripts ./scripts
COPY --from=ui /src/dist ./static
RUN useradd --uid 10001 --home-dir /home/atlas --create-home atlas \
    && mkdir -p /data \
    && chown atlas:atlas /data
USER 10001
ENV ATLAS_DB=/data/atlas.db \
    ATLAS_CATALOG=/app/catalog/sample.json
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
