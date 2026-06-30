FROM python:3.11-slim

WORKDIR /app

# Copy requirements first to leverage Docker cache layers
COPY requirements.txt .

# Install dependencies globally in the container
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# COPY EVERYTHING inside the service folder (both main.py and schemas.py)
COPY . .

# Run uvicorn explicitly via python module path
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]