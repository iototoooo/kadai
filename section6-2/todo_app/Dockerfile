FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . ./todo_app

ENV PYTHONUNBUFFERED=1
EXPOSE 8080

# 非rootユーザーで実行する。
RUN useradd --create-home --uid 10001 appuser
USER appuser

CMD ["sh", "-c", "uvicorn todo_app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
