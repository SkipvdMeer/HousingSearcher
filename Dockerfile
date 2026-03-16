FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tini xvfb xauth \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md config.example.yaml .env.example ./
COPY src ./src
COPY docs ./docs
COPY docker/entrypoint.sh /usr/local/bin/docker-entrypoint.sh

RUN pip install --no-cache-dir . \
    && python -m playwright install --with-deps chromium
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/bin/tini", "--", "docker-entrypoint.sh"]
CMD ["run"]
