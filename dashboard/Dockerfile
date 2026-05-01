FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY app.py vocab.py ./
COPY templates/ templates/

# Data files will be mounted as a volume
VOLUME /app/data

# Location is configured via the /admin web UI on first run (or by
# setting LATITUDE / LONGITUDE / CITY / TIMEZONE env vars at runtime).
ENV PICTURES_DIR=/app/photos
ENV DATA_DIR=/app/data

EXPOSE 5000

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--timeout", "120", "app:app"]
