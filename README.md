# eink-proxy

A tiny Flask application that proxies an existing dashboard or snapshot feed and remaps
it into the seven-colour palette supported by Waveshare-style E-ink panels. The container
is designed to run as a sidecar to Home Assistant or any other service that can provide a
static PNG/JPEG snapshot.

## Features

- Hybrid dithering pipeline tuned for dashboards that mix crisp UI regions with photos.
- Additional endpoints such as `/raw` and `/debug/masks` for troubleshooting.
- Runtime tunables through environment variables (`PHOTO_MODE`, `SKY_GRAD_THR`, etc.).
- Health-checked Docker image built on Python 3.12-slim with Gunicorn.

## Building the image

```bash
docker build -t eink-proxy .
```

## Using docker-compose

```bash
docker compose up -d --build
```

The service will be available on `http://localhost:5000` unless you change the
`HOST_PORT`/`PORT` environment variables.

## Running on Unraid

1. Copy `unraid/docker-template.xml` to your Unraid server at
   `/boot/config/plugins/dockerMan/templates-user/`.
2. Edit the template to point the `<Repository>`, `<Support>`, `<Project>` and
   `<TemplateURL>` fields at your published image or fork. The default values
   assume you have pushed an image to GitHub Container Registry under
   `ghcr.io/your-user/eink-proxy:latest`.
3. In the Unraid web UI, go to **Docker → Add Container**, choose the custom
   template you copied, and adjust the `SOURCE_URL` environment variable to the
   dashboard snapshot you want to proxy. Update any of the advanced tunables if
   required.
4. Deploy the container. The application will expose port `5000` by default
   and provide the rendered E-ink-friendly image at `/eink-image`.

## Runtime configuration

Common environment variables:

| Variable | Description | Default |
| --- | --- | --- |
| `SOURCE_URL` | URL of the dashboard/snapshot image to proxy. | `http://192.168.1.199:10000/.../einkpanelcolor?viewport=800x480` |
| `HOST_PORT` | Host port published by Docker Compose. | `5000` |
| `PORT` | Container port exposed by Gunicorn. | `5000` |

The sample compose file points at ``http://192.168.1.199:10000/lovelace-main/einkpanelcolor?viewport=800x480``; update this to match your dashboard.
If you change `PORT`, update `HOST_PORT` (or adjust your port mapping) so the exposed
port on the host matches the container process.

Additional environment variables:

| Variable | Description | Default |
| --- | --- | --- |
| `PHOTO_MODE` | Photo processing mode (`hybrid`, `fs`, `stucki`, `ordered`). | `hybrid` |
| `SKY_GRAD_THR` | Gradient threshold that controls where photo smoothing applies. | `14` |
| `SMOOTH_STRENGTH` | Strength of edge-aware smoothing in flat areas. | `1` |
| `CACHE_TTL` | Seconds to cache the most recent rendered PNG. | `5` |
| `SOURCE_TIMEOUT` | Seconds to wait for the source request. | `10.0` |
| `SOURCE_RETRIES` | Number of retries when contacting the source. | `2` |

See the top of `eink_proxy.py` for the full list of tunables.

## Endpoints

- `/eink-image?dither=regional` – Recommended for mixed dashboards (default behaviour).
- `/eink-image?dither=false` – Force no dithering for crisp UI dashboards.
- `/eink-image?dither=true` – Force full dithering (best for photographs).
- `/health` – Readiness/liveness information.
- `/raw` – Returns the upstream image without processing.
- `/debug/masks` – Visualises the mask used to decide between UI and photo processing paths.
