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

The service will be available on `http://localhost:5500` unless you change the
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
4. Deploy the container. The application will expose port `5500` by default
   and provide the rendered E-ink-friendly image at `/eink-image`.

## Runtime configuration

Common environment variables:

| Variable | Description | Default |
| --- | --- | --- |
| `SOURCE_URL` | URL of the dashboard/snapshot image to proxy. | `http://192.168.1.199:10000/.../einkpanelcolor?viewport=800x480` |
| `HOST_PORT` | Host port published by Docker Compose. | `5500` |
| `PORT` | Container port exposed by Gunicorn. | `5500` |

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

### Per-request overrides

The proxy can be instructed to fetch a different upstream resource on a per-request basis.
This is useful when an external system (for example ESPHome automations or the Puppet Home
Assistant add-on) wants to trigger different renderings without redeploying the container or
changing its global environment variables.

#### Override parameters

- `source` – Optional absolute URL that replaces the configured `SOURCE_URL` for a single
  request. When providing a URL that already contains a query string you **must URL-encode** the
  value (for example by using `source=https%3A%2F%2Fha.local%2Frender%3Ftheme%3Ddark`) or place it
  last in the proxy URL so that additional `&` characters do not get treated as separate proxy
  parameters.
- `source_base` – Optional scheme + host (and optional base path) that replaces the upstream
  server while reusing the default path and query string from `SOURCE_URL`. Provide only the
  portion that should change (for example `https://ha.local:8123` or
  `https://ha.local:8123/puppet`).
- `source_path` – Optional path override that can be combined with `source_base`. When the value
  starts with `/` it is treated as an absolute path; otherwise it is appended to the base path.
- Any other query parameters (e.g. `dashboard`, `puppet`, `view`, `locale`) are appended to the
  upstream request. If the parameter already exists on the upstream URL, the values are merged so
  that both the default and override values are preserved.
- `dither` continues to control the local rendering behaviour and is never forwarded upstream.

#### Behaviour and caching

- Overrides are applied on every endpoint that fetches the upstream image (`/eink-image`,
  `/raw`, `/debug/masks`).
- The resulting upstream URL is cached according to `CACHE_TTL`. The cache key includes all
  override parameters, so different dashboards or Puppet configurations produce distinct cache
  entries.
- If an override results in an invalid URL, the request fails with a `400` error explaining which
  override was rejected.

#### Example requests

Fetch a specific Puppet dashboard from Home Assistant while forcing hybrid dithering:

```bash
curl "http://proxy.local:5500/eink-image?dashboard=family&puppet=night_mode"
```

Render the same Lovelace view through a different Home Assistant instance by overriding only the
base URL:

```bash
curl "http://proxy.local:5500/eink-image?source_base=https://ha.local:8123"
```

Request a different Puppet configuration exposed on a nested path:

```bash
curl "http://proxy.local:5500/eink-image?source_base=https://ha.local:8123/puppet&source_path=render/dashboard&config=evening"
```

Download the raw upstream image for diagnostics while targeting a custom snapshot. The upstream
URL already has query parameters, so `curl` URL-encodes it automatically:

```bash
curl -G -o raw.png "http://proxy.local:5500/raw" --data-urlencode "source=https://snapshots.local/camera.jpg?refresh=true" --data "ts=$(date +%s)"
```

#### Integrating with ESPHome

Within an ESPHome automation you can dynamically build the URL that the `http_request` action
should call. The snippet below switches between two Puppet configurations based on a binary
sensor, requesting the processed E-ink image when the display refreshes:

```yaml
script:
  - id: refresh_eink_display
    then:
      - http_request.get:
          url: !lambda |-
            if (id(night_mode).state) {
              return "http://proxy.local:5500/eink-image?dashboard=family&puppet=night_mode";
            } else {
              return "http://proxy.local:5500/eink-image?dashboard=family&puppet=day_mode";
            }
```

#### Troubleshooting tips

- Use `/debug/masks` with the same override parameters to verify that the correct dashboard is
  being fetched while inspecting the photo/UI segmentation.
- If Home Assistant endpoints require authentication, place the required tokens directly in the
  `source` parameter (for example `source=https://token@ha.local/...`) or configure a reverse
  proxy that injects credentials.
- When working with the Puppet add-on, inspect its logs to confirm which query parameters it
  expects. Anything you provide on the proxy URL is transparently forwarded to the upstream
  request. If you need to change only the Puppet base address, prefer `source_base`/`source_path`
  instead of embedding a full URL inside another URL.
