import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
import uvicorn

from app.config import load_settings
from app.services.live_stream import LiveStreamManager
from app.utils.security import get_security_manager, init_security_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Load environment variables
from dotenv import load_dotenv

load_dotenv()

settings = load_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    logger.info("Starting Hikvision Live Stream API...")
    init_security_manager(
        allowed_ips=settings.allowed_ips,
        max_body_size=settings.max_body_size,
        enforce_client_ip_rules=settings.enforce_client_ip_rules,
    )
    await live_stream_manager.verify_runtime()
    logger.info("Application started successfully")
    yield
    logger.info("Shutting down Hikvision Live Stream API...")
    await live_stream_manager.stop_all_streams(reason="application shutdown")


app = FastAPI(
    title="Hikvision Live Stream API",
    description="Browser-friendly live camera streaming for Hikvision RTSP feeds",
    version="1.1.0",
    lifespan=lifespan,
)

live_stream_manager = LiveStreamManager(
    camera_user=settings.camera_user,
    camera_password=settings.camera_password,
    ffmpeg_path=settings.ffmpeg_path,
    target_fps=settings.stream_target_fps,
    frame_width=settings.stream_width,
    quality=settings.stream_quality,
    read_timeout_seconds=settings.stream_read_timeout_seconds,
    startup_timeout_seconds=settings.stream_startup_timeout_seconds,
)


@app.get("/camera/live")
async def camera_live(
    request: Request,
    camera_ip: str = Query(..., description="Private Hikvision camera IP"),
    client_id: str = Query(settings.default_client_id, min_length=1, max_length=128),
):
    """MJPEG live stream endpoint backed by Hikvision RTSP."""
    security = get_security_manager()
    if not security:
        security = init_security_manager(
            allowed_ips=settings.allowed_ips,
            max_body_size=settings.max_body_size,
            enforce_client_ip_rules=settings.enforce_client_ip_rules,
        )

    await security.validate_request(request)
    security.validate_camera_ip(camera_ip)

    state = await live_stream_manager.start_or_switch_stream(client_id=client_id, camera_ip=camera_ip)
    return StreamingResponse(
        live_stream_manager.stream_generator(request=request, state=state),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/camera/active-streams")
async def camera_active_streams():
    streams = await live_stream_manager.list_streams()
    return {
        "status": "success",
        "count": len(streams),
        "active_streams": streams,
    }


@app.get("/camera/active-streams/{client_id}")
async def camera_stream_detail(client_id: str):
    stream = await live_stream_manager.get_stream(client_id)
    if not stream:
        raise HTTPException(status_code=404, detail=f"No active stream for client_id={client_id}")
    return {
        "status": "success",
        "stream": stream,
    }


@app.post("/camera/stop")
async def camera_stop(client_id: str = Query(..., min_length=1, max_length=128)):
    stopped = await live_stream_manager.stop_stream(client_id)
    if not stopped:
        raise HTTPException(status_code=404, detail=f"No active stream for client_id={client_id}")
    return {
        "status": "success",
        "message": f"Stream stopped for client_id={client_id}",
    }


@app.post("/camera/stop-all")
async def camera_stop_all():
    stopped_count = await live_stream_manager.stop_all_streams(reason="stop all api")
    return {
        "status": "success",
        "stopped_count": stopped_count,
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    streams = await live_stream_manager.list_streams()
    runtime = await live_stream_manager.runtime_status()
    return {
        "status": "healthy",
        "service": "hikvision-live-stream-api",
        "version": "1.1.0",
        "active_stream_count": len(streams),
        "runtime": runtime,
    }


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "message": "Hikvision Live Stream API",
        "docs": "/docs",
        "health": "/health",
        "live_endpoint": "/camera/live?client_id=<id>&camera_ip=<private-ip>",
    }


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
        log_level="info",
    )
