from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse

router = APIRouter(tags=["dashboard"])

DASHBOARD_HTML = Path(__file__).parent.parent / "dashboard" / "index.html"


@router.get("/dashboard")
async def dashboard():
    return FileResponse(DASHBOARD_HTML, media_type="text/html")
