FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY core/requirements.txt /app/core/requirements.txt
RUN pip install --no-cache-dir -r /app/core/requirements.txt

COPY core /app/core
