FROM python:3.11

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/workspace

WORKDIR /workspace

COPY requirements-prod.txt .
RUN pip install --no-cache-dir -r requirements-prod.txt

# Copy all app code into workspace/app/
COPY . ./app/

# Cloud Run injects PORT; default to 8080
ENV PORT=8080
EXPOSE 8080

# Run as non-root
RUN useradd -m appuser
USER appuser

# Local run with Google credentials:
#   docker run -p 8080:8080 \
#     --env-file .env \
#     -v /path/to/key.json:/secrets/key.json \
#     -e GOOGLE_APPLICATION_CREDENTIALS=/secrets/key.json \
#     beacon-api
#
# On Cloud Run: attach a service account with BigQuery/Firestore roles —
# GOOGLE_APPLICATION_CREDENTIALS is not needed.

CMD exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1
