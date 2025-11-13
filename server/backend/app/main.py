from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .api import create_api_router
from .services.algorithm_manager import AlgorithmManager
from .services.camera_manager import build_default_camera_manager
from .services.recording import RecordingManager
from .services.system_info import get_device_status

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"
RECORD_BASE_DIR = BASE_DIR.parents[2] / "record"


def create_app() -> FastAPI:
    app = FastAPI(
        title="Smart Glasses Control Service",
        description="Control center service for managing smart glasses cameras.",
        version="0.1.0",
    )

    RECORD_BASE_DIR.mkdir(parents=True, exist_ok=True)
    camera_manager = build_default_camera_manager()
    recording_manager = RecordingManager(RECORD_BASE_DIR, camera_manager)
    algorithm_manager = AlgorithmManager(camera_manager)
    app.state.camera_manager = camera_manager
    app.state.recording_manager = recording_manager
    app.state.algorithm_manager = algorithm_manager

    if STATIC_DIR.exists():
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    app.include_router(create_api_router())

    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    @app.get("/healthz", name="healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    async def index(request: Request) -> HTMLResponse:
        camera_snapshot = app.state.camera_manager.status_snapshot()
        camera_cards = [
            {
                "camera_id": camera_id,
                "display_name": data["config"].display_name,
                "running": data["is_running"],
                "resolution": f'{data["config"].frame_width}×{data["config"].frame_height}',
                "fps": data["config"].fps,
            }
            for camera_id, data in camera_snapshot.items()
        ]

        recording_status = {
            "active": app.state.recording_manager.active,
            "record_dir": str(app.state.recording_manager.record_dir) if app.state.recording_manager.record_dir else None,
        }

        device_status = get_device_status()

        algorithms = [
            {
                "algorithm_id": state.algorithm_id,
                "display_name": state.display_name,
                "description": state.description,
                "running": state.running,
                "last_sample_at": state.last_sample_at,
                "last_frame_shapes": state.last_frame_shapes,
            }
            for state in app.state.algorithm_manager.list_algorithms()
        ]

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "page_title": "Smart Glasses Control Center",
                "cameras": camera_cards,
                "recording": recording_status,
                "device_status": device_status,
                "algorithms": algorithms,
            },
        )

    @app.post("/cameras/{camera_id}/start")
    async def dashboard_start_camera(camera_id: str, request: Request) -> RedirectResponse:
        if app.state.camera_manager.get_config(camera_id) is None:
            return RedirectResponse(request.url_for("index"), status_code=303)

        app.state.camera_manager.ensure_started(camera_id)
        return RedirectResponse(request.url_for("index"), status_code=303)

    @app.post("/cameras/{camera_id}/stop")
    async def dashboard_stop_camera(camera_id: str, request: Request) -> RedirectResponse:
        app.state.camera_manager.stop(camera_id)
        return RedirectResponse(request.url_for("index"), status_code=303)

    @app.post("/recording/start")
    async def dashboard_start_recording(request: Request) -> RedirectResponse:
        camera_manager = app.state.camera_manager
        recording_manager = app.state.recording_manager
        camera_ids = [cfg.camera_id for cfg in camera_manager.available_cameras()]
        for camera_id in camera_ids:
            camera_manager.ensure_started(camera_id)
        recording_manager.start(camera_ids)
        return RedirectResponse(request.url_for("index"), status_code=303)

    @app.post("/recording/stop")
    async def dashboard_stop_recording(request: Request) -> RedirectResponse:
        app.state.recording_manager.stop()
        return RedirectResponse(request.url_for("index"), status_code=303)

    @app.post("/algorithms/{algorithm_id}/start")
    async def dashboard_start_algorithm(algorithm_id: str, request: Request) -> RedirectResponse:
        try:
            app.state.algorithm_manager.start(algorithm_id)
        except KeyError:
            pass
        return RedirectResponse(request.url_for("index"), status_code=303)

    @app.post("/algorithms/{algorithm_id}/stop")
    async def dashboard_stop_algorithm(algorithm_id: str, request: Request) -> RedirectResponse:
        try:
            app.state.algorithm_manager.stop(algorithm_id)
        except KeyError:
            pass
        return RedirectResponse(request.url_for("index"), status_code=303)

    return app


app = create_app()

