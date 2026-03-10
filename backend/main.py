from __future__ import annotations

import os
import time
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Set

import requests
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, ORJSONResponse

from backend.ghcn import ensure_dly, find_stations, load_catalog, parse_dly_annual_and_seasons

BASE_DIR = Path(__file__).resolve().parent.parent
PUBLIC_DIR = BASE_DIR / "public"
DEFAULT_DATA_DIR = BASE_DIR / "data"
DATA_DIR = Path(os.getenv("DATA_DIR", str(DEFAULT_DATA_DIR))).resolve()
CACHE_EPOCH_FILE = DATA_DIR / ".annual_cache_epoch"

app = FastAPI(title="GHCN API", default_response_class=ORJSONResponse)
logger = logging.getLogger(__name__)

catalog: Dict[str, Any] | None = None
catalog_error: Exception | None = None
stations: List[Dict[str, Any]] = []
stations_by_id: Dict[str, Dict[str, Any]] = {}
station_ids: Set[str] = set()
_last_catalog_reload_attempt = 0.0


@lru_cache(maxsize=128)
def compute_station_data_cached(
    cache_epoch: int, station_id: str, start_year: int, end_year: int, latitude: float
) -> Dict[str, Any]:
    _ = cache_epoch
    dly_path = ensure_dly(station_id, str(DATA_DIR))
    return parse_dly_annual_and_seasons(dly_path, start_year, end_year, latitude)


def _read_cache_epoch() -> int:
    try:
        return int(CACHE_EPOCH_FILE.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, ValueError):
        return 0


def _write_cache_epoch(value: int) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = CACHE_EPOCH_FILE.with_suffix(".tmp")
    temp_path.write_text(str(value), encoding="utf-8")
    temp_path.replace(CACHE_EPOCH_FILE)


def _bump_cache_epoch() -> int:
    new_epoch = _read_cache_epoch() + 1
    _write_cache_epoch(new_epoch)
    return new_epoch


def _clear_dly_cache() -> int:
    removed_files = 0
    for cache_dir_name in ("dly", "by_station"):
        cache_dir = DATA_DIR / cache_dir_name
        if not cache_dir.exists():
            continue
        for file_path in cache_dir.glob("*"):
            if not file_path.is_file():
                continue
            try:
                file_path.unlink()
                removed_files += 1
            except OSError:
                continue
    return removed_files


def _load_catalog() -> None:
    global catalog, catalog_error, stations, stations_by_id, station_ids
    try:
        catalog = load_catalog(DATA_DIR)
        stations = list(catalog["stations"])
        stations_by_id = {str(station["id"]): station for station in stations}
        station_ids = {str(station["id"]) for station in stations}
        catalog_error = None
        compute_station_data_cached.cache_clear()
    except Exception as error:  # pragma: no cover
        catalog = None
        stations = []
        stations_by_id = {}
        station_ids = set()
        catalog_error = error
        logger.exception("Katalog konnte nicht geladen werden.")


@app.on_event("startup")
def _startup() -> None:
    _load_catalog()


def _require_catalog() -> Dict[str, Any]:
    global _last_catalog_reload_attempt
    if catalog is None:
        now = time.time()
        if now - _last_catalog_reload_attempt >= 30:
            _last_catalog_reload_attempt = now
            _load_catalog()

    if catalog is None:
        detail = str(catalog_error) if catalog_error else "Katalog nicht geladen."
        logger.error("Katalog nicht verfügbar: %s", detail)
        raise HTTPException(status_code=503, detail=detail)
    return catalog


def _validate_year_range(start_year: int, end_year: int, meta: Dict[str, Any]) -> None:
    latest_year = int(meta["latestYear"])
    earliest_year = int(meta["earliestYear"])
    if end_year > latest_year:
        raise HTTPException(status_code=400, detail=f"Endjahr darf nicht > {latest_year} sein.")
    if start_year < earliest_year:
        raise HTTPException(status_code=400, detail=f"Startjahr muss >= {earliest_year} sein.")
    if start_year > end_year:
        raise HTTPException(status_code=400, detail="Startjahr muss <= Endjahr sein.")


@app.get("/api/meta")
def api_meta() -> Dict[str, Any]:
    current_catalog = _require_catalog()
    return current_catalog["meta"]


@app.get("/api/stations")
def api_stations(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radiusKm: float = Query(50.0, ge=0, le=100),
    limit: int = Query(5, ge=1, le=10),
    startYear: int = Query(...),
    endYear: int = Query(...),
) -> List[Dict[str, Any]]:
    current_catalog = _require_catalog()
    meta = current_catalog["meta"]
    _validate_year_range(startYear, endYear, meta)

    return find_stations(
        current_catalog,
        lat=lat,
        lon=lon,
        radius_km=radiusKm,
        limit=limit,
        start_year=startYear,
        end_year=endYear,
    )


@app.get("/api/stations/{station_id}/annual")
def api_station_annual(
    station_id: str,
    startYear: int,
    endYear: int,
):
    current_catalog = _require_catalog()
    _validate_year_range(startYear, endYear, current_catalog["meta"])

    # Station existiert?
    if station_id not in station_ids:
        raise HTTPException(status_code=404, detail="Station nicht gefunden.")

    try:
        cache_epoch = _read_cache_epoch()
        station = stations_by_id[station_id]
        return compute_station_data_cached(cache_epoch, station_id, startYear, endYear, float(station["latitude"]))
    except requests.RequestException as error:
        logger.warning("NOAA-Datenquelle bei Stationsabruf nicht erreichbar: %s", error)
        raise HTTPException(status_code=503, detail=f"NOAA-Datenquelle aktuell nicht erreichbar: {error}")
    except Exception as error:
        logger.exception("Fehler beim Verarbeiten der Stationsdaten für %s.", station_id)
        raise HTTPException(status_code=500, detail=f"Fehler beim Laden/Parsen der Stations-Tagesdaten: {error}")


@app.post("/api/cache/clear")
def api_cache_clear() -> Dict[str, Any]:
    removed_dly_files = _clear_dly_cache()
    compute_station_data_cached.cache_clear()
    cache_epoch = _bump_cache_epoch()
    return {
        "cleared": True,
        "removedDlyFiles": removed_dly_files,
        "cacheEpoch": cache_epoch,
    }


@app.get("/", include_in_schema=False)
def serve_index() -> FileResponse:
    return FileResponse(PUBLIC_DIR / "index.html")


@app.get("/{asset_path:path}", include_in_schema=False)
def serve_assets(asset_path: str):
    if asset_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not found")

    requested = (PUBLIC_DIR / asset_path).resolve()
    public_root = PUBLIC_DIR.resolve()

    if str(requested).startswith(str(public_root)) and requested.is_file():
        return FileResponse(requested)

    return FileResponse(PUBLIC_DIR / "index.html")
