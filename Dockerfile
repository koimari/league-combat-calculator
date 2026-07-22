# Production image for the LoL calculator web app (see docs/deploy.md).
#
# Ships only the runtime: src/, static/, templates/, and the data/ cache.
# vendor/ (the wiki scraper) stays out — patch-day data updates run locally
# and arrive here as committed changes to data/.
FROM python:3.14-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY static/ static/
COPY templates/ templates/
COPY data/ data/

# PaaS hosts (Render, Fly) inject PORT; 8000 is for local `docker run`.
# Workers are processes, not threads — fight sims are CPU-bound Python.
# The generous timeout covers multi-second /api/optimize searches.
ENV PORT=8000
CMD gunicorn src.app:app --bind 0.0.0.0:$PORT --workers ${WEB_CONCURRENCY:-4} --timeout 120
