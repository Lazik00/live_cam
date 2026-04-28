# Hikvision Live Stream API

FastAPI backend for browser-friendly live viewing of Hikvision RTSP camera feeds.

## What this service does

- Streams RTSP camera feed to browser as MJPEG via `GET /camera/live`
- Tracks stream lifecycle per `client_id` and prevents FFmpeg process leaks
- Stops the previous stream automatically when the same `client_id` switches camera
- Exposes health and active stream inspection endpoints

## Senior-level improvements now included

- Centralized env parsing and validation in `app/config.py`
- FFmpeg runtime preflight on startup so misconfigured hosts fail fast
- Per-stream operational metadata: `status`, `frames_sent`, `bytes_sent`, `last_frame_at`, `last_error`, `ffmpeg_pid`
- Stream startup timeout detection when camera is reachable but frames never arrive
- Graceful full shutdown with `stop_all_streams()` to avoid orphan FFmpeg processes
- Extra operator endpoints for per-client inspection and mass stop
- Optional client IP enforcement with `ENFORCE_CLIENT_IP_RULES`

## Live streaming design

- One active stream per `client_id`
- FFmpeg process is spawned per live stream request
- `asyncio.Lock` protects shared `active_streams` state
- Disconnect detection (`request.is_disconnected()`) triggers cleanup
- SSRF mitigation: only valid private IPs or configured CIDRs are accepted for `camera_ip`

## RTSP format

The stream manager opens:

`rtsp://{CAMERA_USER}:{CAMERA_PASSWORD}@{camera_ip}:554/Streaming/Channels/101`

## API endpoints

- `GET /camera/live?client_id=user123&camera_ip=192.168.88.233`
  - Returns `multipart/x-mixed-replace; boundary=frame`
- `GET /camera/active-streams`
- `GET /camera/active-streams/{client_id}`
- `POST /camera/stop?client_id=user123`
- `POST /camera/stop-all`
- `GET /health`

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `CAMERA_USER` | `admin` | Camera username |
| `CAMERA_PASSWORD` | `1q2w3e4r5t` | Camera password |
| `ALLOWED_IPS` | `192.168.0.0/16,10.0.0.0/8,172.16.0.0/12` | Allowed private IP/CIDR list for camera targets |
| `MAX_BODY_SIZE` | `1048576` | Security limit retained for POST endpoints |
| `ENFORCE_CLIENT_IP_RULES` | `false` | If `true`, request source IP must also match `ALLOWED_IPS` |
| `DEFAULT_CLIENT_ID` | `anonymous` | Fallback client id for stream endpoint |
| `FFMPEG_PATH` | `ffmpeg` | FFmpeg binary path |
| `STREAM_RTSP_CHANNEL` | `101` | Hikvision RTSP channel path suffix |
| `STREAM_RECONNECT_ENABLED` | `false` | Enable FFmpeg reconnect flags only if your FFmpeg build supports them |
| `STREAM_TARGET_FPS` | `8` | Target FPS for MJPEG output |
| `STREAM_WIDTH` | `640` | Output frame width passed to FFmpeg scale filter |
| `STREAM_QUALITY` | `5` | MJPEG quality value passed to FFmpeg |
| `STREAM_READ_TIMEOUT_SECONDS` | `2.5` | Timeout for FFmpeg stdout read loop |
| `STREAM_STARTUP_TIMEOUT_SECONDS` | `25` | Fail stream if no frame arrives within this time |
| `HOST` | `0.0.0.0` | API host |
| `PORT` | `8335` | API port |

## Local run

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8335 --reload
```

## Docker run

```bash
docker compose up -d --build
docker compose logs -f
```

Stop:

```bash
docker compose down
```

## Docker + WireGuard

If the camera is reachable only through VPN, the default Docker startup path in this repo now uses the WireGuard sidecar stack.

1. Put your client config at `./wireguard/wg_confs/wg0.conf`.
2. Start the VPN stack:

```bash
docker compose up -d --build
```

3. Check logs:

```bash
docker compose logs -f wireguard hikvision-live-vpn
```

4. Stop the VPN stack:

```bash
docker compose down
```

Notes:

- In VPN mode, port `8335` is published on the `wireguard` container because `hikvision-live-vpn` shares its network namespace.
- The direct `hikvision-live` service is now behind the `direct` profile, so it will not start unless you explicitly ask for it.
- `./wireguard` is mounted into `/config`. Put client tunnel files under `./wireguard/wg_confs/`.
- If your provider-generated config includes `AllowedIPs = 0.0.0.0/0, ::/0` and the tunnel fails with IPv6 issues, keep only `0.0.0.0/0`.
- VPN streams can take longer to produce the first frame, so the default startup timeout is tuned higher than before.

## Direct mode

If you want the non-VPN container instead, start it explicitly:

```bash
docker compose --profile direct up -d --build hikvision-live
```

## Quick checks

```bash
curl http://localhost:8335/health
curl "http://localhost:8335/camera/active-streams"
curl "http://localhost:8335/camera/active-streams/user123"
curl -X POST "http://localhost:8335/camera/stop?client_id=user123"
curl -X POST "http://localhost:8335/camera/stop-all"
```

## Frontend HTML example

`live_example.html` already contains a simple player page for testing.

## Notes

- Live stream uses FFmpeg subprocess per client (`/camera/live`).
- If the camera is unreachable, FFmpeg exits and the stream is cleaned up.
- Health response now includes FFmpeg/runtime tuning info.
- Stream lifecycle logs include `stream started`, `camera switched`, `client disconnected`, `stream stopped`, and `stream cleanup complete`.
