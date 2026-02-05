FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y sqlite3 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir langchain langchain-community langgraph ollama arize-phoenix-otel openinference-instrumentation-langchain opentelemetry-sdk opentelemetry-exporter-otlp
COPY construction_game.py .
CMD ["python", "-u", "construction_game.py"]