# CloudLabs AWS emulator (Moto server), pinned. Runs non-root with a read-only rootfs (tmpfs /tmp).
FROM python:3.12-slim
ARG MOTO_VERSION=5.2.3
RUN pip install --no-cache-dir "moto[server,s3]==${MOTO_VERSION}" \
 && useradd --uid 10001 --create-home --shell /usr/sbin/nologin moto
USER 10001
ENV TMPDIR=/tmp PYTHONDONTWRITEBYTECODE=1 MOTO_ALLOW_NONEXISTENT_REGION=false
EXPOSE 5000
HEALTHCHECK --interval=2s --timeout=2s --retries=30 CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:5000/moto-api/')" || exit 1
CMD ["moto_server", "-H", "0.0.0.0", "-p", "5000"]
LABEL cloudlabs.image=emulator cloudlabs.moto_version=${MOTO_VERSION}
