FROM python:3.12-slim

WORKDIR /app
COPY foundry ./foundry
COPY tests ./tests

RUN pip install --no-cache-dir pytest

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "pytest", "-v"]
