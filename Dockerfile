FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV EDC_CHROME_BINARY=/usr/bin/chromium
ENV EDC_CHROMEDRIVER=/usr/bin/chromedriver

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends chromium chromium-driver \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir selenium

COPY edc_portal ./edc_portal
COPY web ./web
COPY config ./config
COPY README.md ./

EXPOSE 8001

CMD ["python", "-m", "edc_portal.cli", "serve", "--host", "0.0.0.0", "--port", "8001"]
