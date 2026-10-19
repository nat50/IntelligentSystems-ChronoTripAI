FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

EXPOSE 8000
# First start: download the dataset, train and activate a model version (skipped when one exists)
CMD ["sh", "-c", "python -m app.bootstrap && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
