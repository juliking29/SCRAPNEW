FROM python:3.10-slim

# Instala Chrome y sus dependencias
RUN apt-get update && apt-get install -y \
    wget gnupg unzip curl \
    fonts-liberation libappindicator3-1 libasound2 libatk-bridge2.0-0 \
    libatk1.0-0 libcups2 libdbus-1-3 libgdk-pixbuf2.0-0 libnspr4 libnss3 \
    libxcomposite1 libxdamage1 libxrandr2 xdg-utils \
    chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

ENV GOOGLE_CHROME_BIN=/usr/bin/chromium
ENV CHROMEDRIVER_PATH=/usr/bin/chromedriver

# Instala dependencias de Python
WORKDIR /app
COPY . .
RUN pip install --upgrade pip && pip install -r requirements.txt

# Expone el puerto y arranca FastAPI
EXPOSE 8000
CMD ["uvicorn", "final:app", "--host", "0.0.0.0", "--port", "8000"]
