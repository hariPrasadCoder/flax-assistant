FROM python:3.11-slim

WORKDIR /app

# Install dependencies first (cached layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy app source
COPY . .

EXPOSE 8747

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8747"]
