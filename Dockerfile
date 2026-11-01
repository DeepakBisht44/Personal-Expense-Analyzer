FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser
EXPOSE 5000
CMD ["sh", "-c", "flask --app app init-db && exec gunicorn --workers 3 --threads 4 --bind 0.0.0.0:5000 --access-logfile - app:app"]
