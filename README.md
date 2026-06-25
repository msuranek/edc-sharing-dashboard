# EDC Portal Analyzer

Small self-hosted tool for downloading, parsing and evaluating Czech EDC
sharing reports. It can log in to the EDC portal with Selenium, export monthly
CSV reports, convert them to JSON and show the results in a lightweight web UI.

The project is intentionally file-based. It does not require a database.

## Features

- Download EDC CSV exports through a headless Chromium browser
- Parse EDC reports with `Datum`, `Cas od`, `Cas do` and EAN `IN/OUT` columns
- Store data separately by project and sharing group
- Show monthly and daily views in a browser
- Compare current and recommended sharing ratios
- Edit readable names for metering points
- Trigger data download from the web UI with an admin token
- Export a static read-only version of the web app
- Run locally or in Docker

## Project Status

This is a personal/prototype project. It is built around the current EDC portal
flow and may need adjustments if the portal UI changes.

## Repository Layout

```text
edc_portal/        Python downloader, parser, analyzer and HTTP server
web/               Browser UI
config/            Runtime config files, for example OM display names
Dockerfile         Docker image with Python, Chromium and Chromedriver
docker-compose.yml Local/server Docker runtime
data/              Downloaded and processed data, ignored by git
downloads/         Browser downloads, Chrome profile and debug captures, ignored by git
dist/              Static exports, ignored by git
```

## Configuration

Create a local `.env` file from the example. Do not commit `.env`.

```bash
cp .env.example .env
```

Then fill in your own values:

```env
EDC_USERNAME=your-edc-login
EDC_PASSWORD=your-edc-password
EDC_PROJECT_CODE=my-project
EDC_GROUP=My sharing group
EDC_ADMIN_TOKEN=change-this-token

# Docker / compose runtime
EDC_BIND=127.0.0.1
EDC_PORT=8333
```

Important variables:

- `EDC_USERNAME` and `EDC_PASSWORD` are used for EDC portal login.
- `EDC_PROJECT_CODE` separates data under `data/<project-code>/`.
- `EDC_GROUP` is the default sharing group name from the EDC portal.
- `EDC_ADMIN_TOKEN` protects the web endpoint that triggers downloads.
- `EDC_BIND=127.0.0.1` is recommended on servers behind a reverse proxy.
- `EDC_PORT` is the host port exposed by Docker.

Runtime files are stored like this:

```text
data/<project-code>/<group-slug>/raw/
data/<project-code>/<group-slug>/processed/
downloads/<project-code>/<group-slug>/
config/om_names.json
```

## Run With Docker

Docker is the recommended way to run the app. The image contains Python,
Chromium and Chromedriver.

```bash
docker compose up -d --build
```

Open:

```text
http://127.0.0.1:8333/
```

Useful commands:

```bash
docker compose logs -f
docker compose restart
docker compose down
```

Run a separate instance with another env file:

```bash
COMPOSE_PROJECT_NAME=edc-example \
EDC_ENV_FILE=.env.example-local \
EDC_CONTAINER_NAME=edc-example \
EDC_PORT=8334 \
docker compose up -d --build
```

If each instance should have its own OM names, mount a separate config
directory:

```bash
mkdir -p config/example
printf '{}\n' > config/example/om_names.json

COMPOSE_PROJECT_NAME=edc-example \
EDC_ENV_FILE=.env.example-local \
EDC_CONTAINER_NAME=edc-example \
EDC_PORT=8334 \
EDC_CONFIG_DIR=./config/example \
docker compose up -d --build
```

## Server Deployment

On a public server, do not expose the project directory as a web root. Run the
Docker app on localhost and put Apache, Nginx or Caddy in front of it.

Recommended compose binding:

```env
EDC_BIND=127.0.0.1
EDC_PORT=8333
```

Example Nginx reverse proxy:

```nginx
server {
    listen 80;
    server_name example.com;

    location / {
        proxy_pass http://127.0.0.1:8333;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300;
    }
}
```

Example Apache reverse proxy:

```apache
<VirtualHost *:80>
    ServerName example.com

    ProxyPreserveHost On
    ProxyRequests Off

    ProxyPass / http://127.0.0.1:8333/
    ProxyPassReverse / http://127.0.0.1:8333/
</VirtualHost>
```

Enable Apache proxy modules if needed:

```bash
sudo a2enmod proxy proxy_http headers
sudo systemctl reload apache2
```

## Minimal Files To Copy To A Server

For a Docker deployment, copy only the source and runtime config:

```text
Dockerfile
docker-compose.yml
README.md
.env.example
edc_portal/
web/
config/
.env
```

Do not copy generated/local directories unless you intentionally want to migrate
existing data:

```text
.venv/
data/
downloads/
dist/
__pycache__/
```

Example with `rsync`:

```bash
rsync -av \
  --exclude '.venv/' \
  --exclude 'data/' \
  --exclude 'downloads/' \
  --exclude 'dist/' \
  --exclude '__pycache__/' \
  --exclude '*.pyc' \
  --exclude '.DS_Store' \
  ./ user@server:/var/docker/edc/
```

## Web UI

The web UI is served at `/`.

Main API endpoints:

```text
GET  /api/config
GET  /api/groups
GET  /api/months
GET  /api/data/latest
GET  /api/data/month
GET  /api/sync-status
POST /api/sync
GET  /api/om-names
POST /api/om-names
```

`POST /api/sync` requires the admin token from `EDC_ADMIN_TOKEN`.

## CLI Usage

Local Python usage is useful for development and manual parsing.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install selenium
```

Run the web server locally:

```bash
.venv/bin/python -m edc_portal.cli serve --host 127.0.0.1 --port 8123
```

Download one month from EDC:

```bash
.venv/bin/python -m edc_portal.cli download --month 6 --year 2026
```

Parse a CSV manually:

```bash
.venv/bin/python -m edc_portal.cli parse data/my-project/my-group/raw/edc-2026-06.csv
```

List and edit metering point names:

```bash
.venv/bin/python -m edc_portal.cli names
.venv/bin/python -m edc_portal.cli set-name 859000000000000000 "Main production"
.venv/bin/python -m edc_portal.cli remove-name 859000000000000000
```

Export a static read-only version:

```bash
.venv/bin/python -m edc_portal.cli export-static --output dist/example
```

Serve the static export with any static web server:

```bash
python3 -m http.server --directory dist/example 8080
```

Static export is read-only. Downloading new data and saving OM names require the
Python API server.

## Git Ignore

The repository should not contain credentials, downloaded data or generated
files. These paths are ignored:

```text
.env
.env.*
!.env.example
.venv/
data/
downloads/
dist/
config/om_names.json
__pycache__/
*.pyc
```

## Notes

- The downloader uses Selenium and Chromium, so portal UI changes can break the
  scraping flow.
- Some sharing groups or periods may legitimately return no EAN `IN/OUT`
  columns. In that case the app treats the selected group/period as having no
  available data.
- The recommendation currently works with energy volumes in kWh. Prices,
  tariffs and contractual constraints are outside the current scope.
