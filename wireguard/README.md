# WireGuard Client Config

Place your client tunnel config in this folder structure:

```text
wireguard/
  wg_confs/
    wg0.conf
```

This repo uses the LinuxServer WireGuard container in client mode. The container reads client tunnel files from `/config/wg_confs/*.conf`, which maps to `./wireguard/wg_confs/*.conf` in this project.

Recommended startup command:

```bash
docker compose up -d --build
```
