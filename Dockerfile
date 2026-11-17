FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --create-home appuser \
    && mkdir -p /data && chown appuser:appuser /data
COPY --chown=appuser:appuser server.py .
COPY --chown=appuser:appuser public ./public
USER appuser
ENV PORT=8080 PAVZA_DATA_DIR=/data PAVZA_SITE_ENV=portfolio_demo PAVZA_ALLOW_SUBMISSIONS=0
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers"]
