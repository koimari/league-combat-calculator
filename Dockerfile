# Production image for the LoL calculator web app (see docs/deploy.md).
#
# Ships only the runtime: src/, static/, templates/, and the data/ cache.
# vendor/ (the wiki scraper) stays out — patch-day data updates run locally
# and arrive here as committed changes to data/.
FROM python:3.15.0rc1-slim@sha256:d66aca68fc851b8e5b1bc350f7154fe408cf0e85e70c37d18a385591d9bf2743

WORKDIR /app

COPY requirements-runtime.txt .
RUN apt-get update \
    && apt-get upgrade --yes \
    && apt-get install --no-install-recommends --yes libpq5 \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir --require-hashes -r requirements-runtime.txt \
    && pip uninstall --yes pip \
    && addgroup --system app \
    && adduser --system --ingroup app app

COPY --chown=app:app src/ src/
COPY --chown=app:app static/ static/
COPY --chown=app:app templates/ templates/
COPY --chown=app:app data/ data/

# PaaS hosts (Render, Fly) inject PORT; 8000 is for local `docker run`.
# Workers are processes, not threads — fight sims are CPU-bound Python.
# Request bounds keep every valid calculation below this finite deadline.
ENV PORT=8000 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ['PORT'] + '/healthz', timeout=2)"]
CMD ["sh", "-c", "exec gunicorn src.app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-2} --timeout 30 --access-logfile - --error-logfile -"]
