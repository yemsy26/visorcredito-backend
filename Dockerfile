# Imagen oficial de Playwright — ya incluye Chromium y todas las dependencias
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# No necesitamos instalar playwright browsers — ya vienen en la imagen base
COPY . .

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
