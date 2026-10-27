FROM mcr.microsoft.com/playwright/python:v1.64.1-jammy

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "10000"]
