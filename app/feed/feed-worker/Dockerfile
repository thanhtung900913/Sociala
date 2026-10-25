FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN useradd --uid 10001 --create-home worker
COPY app ./app
COPY main.py config.py ./
COPY sql ./sql
USER worker
CMD ["python", "main.py"]
