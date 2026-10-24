# sift in a container: `docker compose up -d` keeps `sift watch` running 24/7 (home server, NAS, Raspberry Pi).
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1 SIFT_HOME=/data
WORKDIR /app
COPY pyproject.toml README.md ./
COPY steamsift ./steamsift
RUN pip install --no-cache-dir . && useradd --create-home sift && mkdir -p /data && chown sift /data
USER sift
VOLUME ["/data"]

ENTRYPOINT ["sift"]
CMD ["watch"]
