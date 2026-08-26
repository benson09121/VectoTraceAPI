# Django 5.2 requires Python 3.10+, and this codebase uses 3.10+ syntax
# (`str | None`, `list[int]`). The previous python:3.8 base could never have
# built this project. The GDAL/PROJ packages were also unused — nothing here
# does geospatial work.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# libpq for psycopg2, build-essential for argon2-cffi, curl for healthchecks.
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Requirements first, so the dependency layer survives source-only changes.
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
