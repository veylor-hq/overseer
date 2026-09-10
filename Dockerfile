FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONPATH=/app/master

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
RUN pip install --upgrade pip setuptools wheel && \
    pip install \
    "fastapi>=0.115.0" \
    "uvicorn[standard]>=0.30.0" \
    "beanie==2.0.1" \
    "motor>=3.6.0" \
    "pydantic>=2.8.0" \
    "pydantic-settings>=2.4.0" \
    "jinja2>=3.1.4" \
    "python-multipart>=0.0.9" \
    "httpx>=0.27.0" \
    "pyjwt[crypto]>=2.9.0" \
    "cryptography>=43.0.0" \
    "argon2-cffi>=23.1.0" \
    "ulid-py>=1.1.0"

COPY master/ /app/master/
WORKDIR /app/master

RUN useradd -m -u 1000 veylor && \
    chown -R veylor:veylor /app

USER veylor

EXPOSE 8080

CMD ["uvicorn", "overseer.main:app", "--host", "0.0.0.0", "--port", "8080"]
