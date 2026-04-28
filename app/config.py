from dataclasses import dataclass
import os
from typing import List, Optional


def _get_env_str(name: str, default: str) -> str:
    value = os.getenv(name, default).strip()
    return value or default


def _get_env_int(name: str, default: int, minimum: Optional[int] = None) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        value = default
    else:
        value = int(raw_value)

    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _get_env_float(name: str, default: float, minimum: Optional[float] = None) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        value = default
    else:
        value = float(raw_value)

    if minimum is not None and value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value


def _get_env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None or raw_value.strip() == "":
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _get_env_list(name: str) -> Optional[List[str]]:
    raw_value = os.getenv(name, "").strip()
    if not raw_value:
        return None
    values = [item.strip() for item in raw_value.split(",")]
    return [item for item in values if item]


@dataclass(frozen=True)
class Settings:
    camera_user: str
    camera_password: str
    allowed_ips: Optional[List[str]]
    max_body_size: int
    host: str
    port: int
    default_client_id: str
    enforce_client_ip_rules: bool
    ffmpeg_path: str
    stream_rtsp_channel: int
    stream_reconnect_enabled: bool
    stream_target_fps: int
    stream_width: int
    stream_quality: int
    stream_read_timeout_seconds: float
    stream_startup_timeout_seconds: float


def load_settings() -> Settings:
    return Settings(
        camera_user=_get_env_str("CAMERA_USER", "admin"),
        camera_password=_get_env_str("CAMERA_PASSWORD", "1q2w3e4r5t"),
        allowed_ips=_get_env_list("ALLOWED_IPS"),
        max_body_size=_get_env_int("MAX_BODY_SIZE", 1048576, minimum=1024),
        host=_get_env_str("HOST", "0.0.0.0"),
        port=_get_env_int("PORT", 8335, minimum=1),
        default_client_id=_get_env_str("DEFAULT_CLIENT_ID", "anonymous"),
        enforce_client_ip_rules=_get_env_bool("ENFORCE_CLIENT_IP_RULES", False),
        ffmpeg_path=_get_env_str("FFMPEG_PATH", "ffmpeg"),
        stream_rtsp_channel=_get_env_int("STREAM_RTSP_CHANNEL", 101, minimum=1),
        stream_reconnect_enabled=_get_env_bool("STREAM_RECONNECT_ENABLED", False),
        stream_target_fps=_get_env_int("STREAM_TARGET_FPS", 8, minimum=1),
        stream_width=_get_env_int("STREAM_WIDTH", 640, minimum=160),
        stream_quality=_get_env_int("STREAM_QUALITY", 5, minimum=1),
        stream_read_timeout_seconds=_get_env_float("STREAM_READ_TIMEOUT_SECONDS", 2.5, minimum=0.2),
        stream_startup_timeout_seconds=_get_env_float("STREAM_STARTUP_TIMEOUT_SECONDS", 25.0, minimum=1.0),
    )
