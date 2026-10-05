# CloudLabs API image — two stages.
#
#   runtime (default target) — production control plane, requirements.txt only.
#   test                     — api-test container: runtime deps + requirements-dev.txt (pytest, moto).
#
# The runtime stage is last so a plain `docker build` (e.g. the production compose stack) can never
# produce an image with dev dependencies.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
RUN useradd --uid 10010 --no-create-home api
COPY requirements.txt requirements-dev.txt ./

FROM base AS test
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY . .
RUN chmod +x entrypoint.sh
USER 10010
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["serve"]

FROM base AS runtime
RUN pip install --no-cache-dir -r requirements.txt \
 && ! python -c "import pytest" \
 && ! python -c "import moto"  # guard: the production image must not contain dev dependencies
COPY . .
RUN chmod +x entrypoint.sh
USER 10010
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["serve"]
