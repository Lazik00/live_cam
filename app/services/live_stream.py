import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi import Request

logger = logging.getLogger(__name__)


@dataclass
class StreamState:
    client_id: str
    camera_ip: str
    stop_event: asyncio.Event
    started_at: datetime
    ffmpeg_process: Optional[asyncio.subprocess.Process] = None
    frames_sent: int = 0
    bytes_sent: int = 0
    last_frame_at: Optional[datetime] = None
    last_error: Optional[str] = None
    reconnect_supported: bool = True
    status: str = "starting"
    ffmpeg_pid: Optional[int] = None
    startup_deadline_monotonic: float = field(default=0.0, repr=False)
    stderr_reader_task: Optional[asyncio.Task] = field(default=None, repr=False)
    stderr_tail: str = ""


class LiveStreamManager:
    """Manages per-client MJPEG streams with explicit FFmpeg lifecycle cleanup."""

    JPEG_SOI = b"\xff\xd8"
    JPEG_EOI = b"\xff\xd9"

    def __init__(
        self,
        camera_user: str,
        camera_password: str,
        ffmpeg_path: str = "ffmpeg",
        rtsp_channel: int = 101,
        reconnect_enabled: bool = False,
        target_fps: int = 8,
        frame_width: int = 640,
        quality: int = 5,
        read_timeout_seconds: float = 2.5,
        startup_timeout_seconds: float = 12.0,
    ):
        self.camera_user = camera_user
        self.camera_password = camera_password
        self.ffmpeg_path = ffmpeg_path
        self.rtsp_channel = rtsp_channel
        self.reconnect_enabled = reconnect_enabled
        self.target_fps = target_fps
        self.frame_width = frame_width
        self.quality = quality
        self.read_timeout_seconds = read_timeout_seconds
        self.startup_timeout_seconds = startup_timeout_seconds
        self.active_streams: Dict[str, StreamState] = {}
        self._lock = asyncio.Lock()

    async def verify_runtime(self) -> None:
        ffmpeg_resolved = shutil.which(self.ffmpeg_path)
        if not ffmpeg_resolved:
            raise RuntimeError(f"FFmpeg binary not found: {self.ffmpeg_path}")
        logger.info("ffmpeg runtime ready: path=%s resolved=%s", self.ffmpeg_path, ffmpeg_resolved)

    async def runtime_status(self) -> Dict[str, Any]:
        return {
            "ffmpeg_path": self.ffmpeg_path,
            "ffmpeg_available": shutil.which(self.ffmpeg_path) is not None,
            "rtsp_channel": self.rtsp_channel,
            "reconnect_enabled": self.reconnect_enabled,
            "target_fps": self.target_fps,
            "frame_width": self.frame_width,
            "quality": self.quality,
            "read_timeout_seconds": self.read_timeout_seconds,
            "startup_timeout_seconds": self.startup_timeout_seconds,
        }

    def _rtsp_url(self, camera_ip: str) -> str:
        return (
            f"rtsp://{self.camera_user}:{self.camera_password}@"
            f"{camera_ip}:554/Streaming/Channels/{self.rtsp_channel}"
        )

    def _serialize_state(self, state: StreamState) -> Dict[str, Any]:
        return {
            "client_id": state.client_id,
            "camera_ip": state.camera_ip,
            "status": state.status,
            "started_at": state.started_at.isoformat(),
            "frames_sent": state.frames_sent,
            "bytes_sent": state.bytes_sent,
            "last_frame_at": state.last_frame_at.isoformat() if state.last_frame_at else None,
            "last_error": state.last_error,
            "stderr_tail": state.stderr_tail or None,
            "ffmpeg_pid": state.ffmpeg_pid,
            "reconnect_supported": state.reconnect_supported,
        }

    async def _consume_stderr(self, state: StreamState, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return

        chunks: list[str] = []
        try:
            while True:
                line = await process.stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="ignore").strip()
                if not text:
                    continue
                chunks.append(text)
                if len(chunks) > 20:
                    chunks = chunks[-20:]
                state.stderr_tail = "\n".join(chunks)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("stderr consumer failed: client_id=%s error=%s", state.client_id, exc)

    async def get_stream(self, client_id: str) -> Optional[Dict[str, Any]]:
        async with self._lock:
            state = self.active_streams.get(client_id)
            return self._serialize_state(state) if state else None

    async def _terminate_process(self, state: StreamState, reason: str) -> None:
        process = state.ffmpeg_process
        stderr_task = state.stderr_reader_task
        if process is None:
            return

        if process.returncode is None:
            logger.info(
                "terminating ffmpeg: client_id=%s camera_ip=%s reason=%s",
                state.client_id,
                state.camera_ip,
                reason,
            )
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()

        if stderr_task:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass

        state.ffmpeg_process = None
        state.ffmpeg_pid = None
        state.stderr_reader_task = None

    async def start_or_switch_stream(self, client_id: str, camera_ip: str) -> StreamState:
        """Ensure one active stream per client; old stream gets stop signal and process termination."""
        old_state: Optional[StreamState] = None
        async with self._lock:
            old_state = self.active_streams.get(client_id)
            if old_state:
                old_state.stop_event.set()
                old_state.status = "stopping"

            state = StreamState(
                client_id=client_id,
                camera_ip=camera_ip,
                stop_event=asyncio.Event(),
                started_at=datetime.now(timezone.utc),
            )
            self.active_streams[client_id] = state

        if old_state:
            if old_state.camera_ip != camera_ip:
                logger.info(
                    "camera switched: client_id=%s old_ip=%s new_ip=%s",
                    client_id,
                    old_state.camera_ip,
                    camera_ip,
                )
                await self._terminate_process(old_state, reason="camera switched")
            else:
                logger.info("stream restarted: client_id=%s camera_ip=%s", client_id, camera_ip)
                await self._terminate_process(old_state, reason="stream restarted")

        logger.info("stream started: client_id=%s camera_ip=%s", client_id, camera_ip)
        return state

    async def stop_stream(self, client_id: str) -> bool:
        state: Optional[StreamState] = None
        async with self._lock:
            state = self.active_streams.pop(client_id, None)
            if not state:
                return False
            state.stop_event.set()
            state.status = "stopping"

        await self._terminate_process(state, reason="stop api")
        logger.info("stream stopped by api: client_id=%s camera_ip=%s", client_id, state.camera_ip)
        return True

    async def stop_all_streams(self, reason: str) -> int:
        async with self._lock:
            states = list(self.active_streams.values())
            self.active_streams.clear()

        for state in states:
            state.stop_event.set()
            state.status = "stopping"

        await asyncio.gather(*(self._terminate_process(state, reason=reason) for state in states), return_exceptions=True)
        if states:
            logger.info("all streams stopped: count=%s reason=%s", len(states), reason)
        return len(states)

    async def list_streams(self) -> Dict[str, Dict[str, Any]]:
        async with self._lock:
            return {
                client_id: self._serialize_state(state)
                for client_id, state in self.active_streams.items()
            }

    async def _cleanup_stream(self, state: StreamState) -> None:
        async with self._lock:
            current = self.active_streams.get(state.client_id)
            if current is state:
                self.active_streams.pop(state.client_id, None)

    def _ffmpeg_cmd(self, rtsp_url: str, use_reconnect: bool = True) -> list[str]:
        cmd = [
            self.ffmpeg_path,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-rtsp_transport",
            "tcp",
        ]
        if use_reconnect and self.reconnect_enabled:
            cmd.extend([
                "-reconnect",
                "1",
                "-reconnect_streamed",
                "1",
                "-reconnect_delay_max",
                "2",
            ])

        cmd.extend([
            "-i",
            rtsp_url,
            "-an",
            "-vf",
            f"fps={self.target_fps},scale={self.frame_width}:-1",
            "-f",
            "mjpeg",
            "-q:v",
            str(self.quality),
            "pipe:1",
        ])
        return cmd

    async def stream_generator(self, request: Request, state: StreamState) -> AsyncGenerator[bytes, None]:
        buffer = bytearray()
        rtsp_url = self._rtsp_url(state.camera_ip)
        process: Optional[asyncio.subprocess.Process] = None
        reconnect_supported = self.reconnect_enabled

        try:
            for attempt in range(2):
                state.status = "starting"
                state.last_error = None
                state.stderr_tail = ""
                state.startup_deadline_monotonic = asyncio.get_running_loop().time() + self.startup_timeout_seconds
                process = await asyncio.create_subprocess_exec(
                    *self._ffmpeg_cmd(rtsp_url, use_reconnect=reconnect_supported),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                state.ffmpeg_process = process
                state.ffmpeg_pid = process.pid
                state.reconnect_supported = reconnect_supported
                state.stderr_reader_task = asyncio.create_task(self._consume_stderr(state, process))
                logger.info(
                    "ffmpeg process started: client_id=%s camera_ip=%s reconnect=%s pid=%s",
                    state.client_id,
                    state.camera_ip,
                    reconnect_supported,
                    process.pid,
                )

                if process.stdout is None:
                    state.status = "error"
                    state.last_error = "ffmpeg stdout unavailable"
                    logger.error("ffmpeg stdout unavailable: client_id=%s camera_ip=%s", state.client_id, state.camera_ip)
                    return

                while True:
                    if state.stop_event.is_set():
                        state.status = "stopped"
                        logger.info("stream stopped: client_id=%s camera_ip=%s", state.client_id, state.camera_ip)
                        return

                    if await request.is_disconnected():
                        state.status = "client_disconnected"
                        logger.info("client disconnected: client_id=%s camera_ip=%s", state.client_id, state.camera_ip)
                        return

                    try:
                        chunk = await asyncio.wait_for(
                            process.stdout.read(4096),
                            timeout=self.read_timeout_seconds,
                        )
                    except asyncio.TimeoutError:
                        if process.returncode is not None:
                            break

                        startup_timed_out = (
                            state.frames_sent == 0
                            and asyncio.get_running_loop().time() > state.startup_deadline_monotonic
                        )
                        if startup_timed_out:
                            state.status = "startup_timeout"
                            state.last_error = state.stderr_tail or (
                                f"no frames received within {self.startup_timeout_seconds} seconds"
                            )
                            logger.warning(
                                "stream startup timeout: client_id=%s camera_ip=%s timeout=%s stderr=%s",
                                state.client_id,
                                state.camera_ip,
                                self.startup_timeout_seconds,
                                state.stderr_tail,
                            )
                            break
                        continue

                    if not chunk:
                        if process.returncode is not None:
                            break
                        await asyncio.sleep(0.02)
                        continue

                    buffer.extend(chunk)

                    while True:
                        start = buffer.find(self.JPEG_SOI)
                        if start == -1:
                            if len(buffer) > 1024 * 1024:
                                buffer.clear()
                            break

                        end = buffer.find(self.JPEG_EOI, start + 2)
                        if end == -1:
                            if start > 0:
                                del buffer[:start]
                            break

                        frame = bytes(buffer[start:end + 2])
                        del buffer[:end + 2]
                        state.frames_sent += 1
                        state.bytes_sent += len(frame)
                        state.last_frame_at = datetime.now(timezone.utc)
                        state.status = "streaming"
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"

                stderr_tail = state.stderr_tail
                if stderr_tail:
                    state.last_error = stderr_tail
                if state.status in {"starting", "streaming"}:
                    state.status = "ffmpeg_exited"

                logger.warning(
                    "ffmpeg stream ended: client_id=%s camera_ip=%s returncode=%s stderr=%s",
                    state.client_id,
                    state.camera_ip,
                    process.returncode,
                    stderr_tail,
                )

                if reconnect_supported and "Option reconnect not found" in stderr_tail and attempt == 0:
                    logger.warning(
                        "ffmpeg reconnect flags unsupported, retrying without reconnect: client_id=%s camera_ip=%s",
                        state.client_id,
                        state.camera_ip,
                    )
                    reconnect_supported = False
                    await self._terminate_process(state, reason="retry without reconnect")
                    continue

                break

        except asyncio.CancelledError:
            state.status = "cancelled"
            logger.info(
                "stream task cancelled (likely client/proxy disconnect): client_id=%s camera_ip=%s",
                state.client_id,
                state.camera_ip,
            )
            raise

        finally:
            await self._terminate_process(state, reason="stream cleanup")
            await self._cleanup_stream(state)
            logger.info(
                "stream cleanup complete: client_id=%s camera_ip=%s frames_sent=%s bytes_sent=%s status=%s",
                state.client_id,
                state.camera_ip,
                state.frames_sent,
                state.bytes_sent,
                state.status,
            )
