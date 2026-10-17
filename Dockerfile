# Hound: one container with FalkorDB (official server build) + the API + the web UI.
# Works on Hugging Face Spaces (port 7860, uid 1000) and Render (uses $PORT).

FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# Official FalkorDB 6 server image: Debian trixie, redis-server + self-contained falkordb.so
FROM falkordb/falkordb-server:latest AS falkordb

FROM python:3.11-slim-trixie
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app/backend/src HOME=/home/user
RUN useradd -m -u 1000 user
COPY --from=falkordb /usr/local/bin/redis-server /usr/local/bin/redis-server
COPY --from=falkordb /usr/local/bin/redis-cli /usr/local/bin/redis-cli
COPY --from=falkordb /var/lib/falkordb/bin/falkordb.so /opt/falkordb/falkordb.so
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend/ backend/
COPY --from=web /web/dist frontend/dist
COPY start.sh start.sh
RUN chmod 755 /app/start.sh /opt/falkordb/falkordb.so && chown -R user:user /app
USER user
EXPOSE 7860
CMD ["/app/start.sh"]
