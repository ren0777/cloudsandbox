FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv
COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements.txt -r requirements-dev.txt
COPY . .
RUN useradd --uid 10010 --no-create-home api && chmod +x entrypoint.sh
USER 10010
EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
CMD ["serve"]
