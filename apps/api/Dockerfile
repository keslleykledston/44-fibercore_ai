FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY apps/api/pyproject.toml apps/api/requirements.lock /app/
COPY apps/api/app /app/app
RUN pip install --no-cache-dir --require-hashes -r /app/requirements.lock && pip install --no-cache-dir --no-deps . && useradd --uid 10001 --create-home app
COPY apps/api/alembic.ini /app/alembic.ini
COPY apps/api/alembic /app/alembic
COPY configs /app/configs
USER 10001
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
