# CloudLabs Runner Agent image — two stages (same pattern as services/api).
#
#   runtime (default target) — production runner: requirements.txt and app/ only.
#   test                     — runner tests: runtime deps + requirements-dev.txt, plus tests/.
#                              docker build --target test -t cloudlabs/runner-test:dev services/runner
#
# The runtime stage is last so a plain `docker build` (dev compose, runner-host compose) can never produce
# an image with dev dependencies. The runner holds the Docker socket, so it ships nothing it doesn't need.
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt requirements-dev.txt ./

FROM base AS test
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY app ./app
COPY tests ./tests
COPY pytest.ini ./
EXPOSE 7070
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7070", "--ws", "websockets-sansio", "--no-access-log"]

FROM base AS runtime
RUN pip install --no-cache-dir -r requirements.txt \
 && ! python -c "import pytest" \
 && ! python -c "import httpx2"  # guard: the production image must not contain dev dependencies
COPY app ./app
EXPOSE 7070
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7070", "--ws", "websockets-sansio", "--no-access-log"]
