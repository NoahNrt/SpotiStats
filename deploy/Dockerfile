# Image für Collector und Importer (gleicher Code, anderer Startbefehl)
FROM docker.io/library/python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ /app/
CMD ["python", "-u", "collector.py", "loop"]
