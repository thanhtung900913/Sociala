# Dockerfile
FROM python:3.10-slim

RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    libpq-dev \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set the timezone to Vietnam
ENV TZ=Asia/Ho_Chi_Minh
RUN ln -sf /usr/share/zoneinfo/Asia/Ho_Chi_Minh /etc/localtime \
    && echo "Asia/Ho_Chi_Minh" > /etc/timezone

# Create a working directory
WORKDIR /app

# Copy requirement file
COPY requirements.txt /app/

# Install Python dependencies without cache
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire project into the container
COPY . /app

# Expose the port (Gunicorn will listen on 5000)
EXPOSE 5000

# Use Gunicorn to run our Flask app in production
# The string "app.main:create_app()" refers to the 'create_app' function in app/main.py
CMD ["gunicorn", \
     "-w", "2", \
     "-k", "gevent", \
     "--worker-connections", "500", \
     "-b", "0.0.0.0:5000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--max-requests", "1000", \
     "--max-requests-jitter", "50", \
     "--log-level", "info", \
     "main:create_app()"]

# CMD ["sleep", "infinity"]