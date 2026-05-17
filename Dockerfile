FROM python:3.11-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY api api
COPY vision vision
COPY events events
COPY analytics analytics
COPY telemetry telemetry
COPY configs configs
RUN pip install --no-cache-dir -e .

EXPOSE 8080
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8080"]
