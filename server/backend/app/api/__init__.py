from fastapi import APIRouter

from . import algorithms, cameras, recording


def create_api_router() -> APIRouter:
    router = APIRouter(prefix="/api")
    router.include_router(cameras.router, prefix="/cameras", tags=["cameras"])
    router.include_router(recording.router, prefix="/recording", tags=["recording"])
    router.include_router(algorithms.router, prefix="/algorithms", tags=["algorithms"])
    return router

