from __future__ import annotations

import math
import os
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import requests

STATIONS_FILE = "ghcnd-stations.txt"
INVENTORY_FILE = "ghcnd-inventory.txt"
NOAA_BASE_URL = "https://www.ncei.noaa.gov/pub/data/ghcn/daily"
STATIONS_URL = f"{NOAA_BASE_URL}/{STATIONS_FILE}"
INVENTORY_URL = f"{NOAA_BASE_URL}/{INVENTORY_FILE}"
_NAME_SEPARATORS_RE = re.compile(r"([\s,()/-]+)")
_GERMAN_TOKEN_REPLACEMENTS = {
    "Dusseldorf": "Düsseldorf",
    "Furth": "Fürth",
    "Gottingen": "Göttingen",
    "Koln": "Köln",
    "Lubeck": "Lübeck",
    "Munchen": "München",
    "Nurnberg": "Nürnberg",
    "Osnabruck": "Osnabrück",
    "Uberlingen": "Überlingen",
    "Wurzburg": "Würzburg",
}


def _parse_float(text: str) -> Optional[float]:
    try:
        return float(text.strip())
    except ValueError:
        return None


def _parse_int(text: str) -> Optional[int]:
    try:
        return int(text.strip())
    except ValueError:
        return None


def _title_case_station_name(name: str) -> str:
    tokens = _NAME_SEPARATORS_RE.split(name.strip())
    return "".join(token.capitalize() if token and not _NAME_SEPARATORS_RE.fullmatch(token) else token for token in tokens)


def _apply_german_umlaut_fixes(name: str) -> str:
    tokens = _NAME_SEPARATORS_RE.split(name)
    fixed: List[str] = []
    for token in tokens:
        if not token or _NAME_SEPARATORS_RE.fullmatch(token):
            fixed.append(token)
            continue
        fixed.append(_GERMAN_TOKEN_REPLACEMENTS.get(token, token))
    return "".join(fixed)


def _format_station_name(station_id: str, raw_name: str) -> str:
    cleaned = raw_name.strip()
    if not cleaned:
        return station_id

    name = _title_case_station_name(cleaned)
    if station_id.startswith("GM"):
        name = _apply_german_umlaut_fixes(name)
    return name


def _download_file(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_suffix(target.suffix + ".part")

    with urllib.request.urlopen(url, timeout=120) as response, temp_path.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)

    temp_path.replace(target)


def ensure_data_files(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)

    required = {
        STATIONS_FILE: STATIONS_URL,
        INVENTORY_FILE: INVENTORY_URL,
    }

    for file_name, url in required.items():
        file_path = data_dir / file_name
        if file_path.exists() and file_path.stat().st_size > 0:
            continue
        _download_file(url, file_path)


def ensure_dly(station_id: str, data_dir: str) -> str:
    dly_dir = os.path.join(data_dir, "dly")
    os.makedirs(dly_dir, exist_ok=True)
    out_path = os.path.join(dly_dir, f"{station_id}.dly")

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    url = f"https://www.ncei.noaa.gov/pub/data/ghcn/daily/all/{station_id}.dly"
    temp_path = f"{out_path}.part"
    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()

    try:
        with open(temp_path, "wb") as file_handle:
            for chunk in response.iter_content(chunk_size=1024 * 256):
                if chunk:
                    file_handle.write(chunk)
        os.replace(temp_path, out_path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return out_path


def _new_stats_bucket(start_year: int, end_year: int) -> Dict[int, Dict[str, float | int]]:
    return {
        year: {"tmin_sum": 0.0, "tmin_n": 0, "tmax_sum": 0.0, "tmax_n": 0}
        for year in range(start_year, end_year + 1)
    }


def _rows_from_bucket(bucket: Dict[int, Dict[str, float | int]], start_year: int, end_year: int) -> List[Dict[str, float | int | None]]:
    rows: List[Dict[str, float | int | None]] = []
    for year in range(start_year, end_year + 1):
        tmin = None
        tmax = None
        if bucket[year]["tmin_n"] > 0:
            tmin = round(bucket[year]["tmin_sum"] / bucket[year]["tmin_n"], 1)
        if bucket[year]["tmax_n"] > 0:
            tmax = round(bucket[year]["tmax_sum"] / bucket[year]["tmax_n"], 1)
        rows.append({"year": year, "tmin": tmin, "tmax": tmax})
    return rows


def season_of(month: int) -> str | None:
    if month in (3, 4, 5):
        return "spring"
    if month in (6, 7, 8):
        return "summer"
    if month in (9, 10, 11):
        return "autumn"
    if month in (12, 1, 2):
        return "winter"
    return None


def parse_dly_annual_and_seasons(dly_path: str, start_year: int, end_year: int):
    annual_sums = _new_stats_bucket(start_year, end_year)
    season_sums = {
        "spring": _new_stats_bucket(start_year, end_year),
        "summer": _new_stats_bucket(start_year, end_year),
        "autumn": _new_stats_bucket(start_year, end_year),
        "winter": _new_stats_bucket(start_year, end_year),
    }

    with open(dly_path, "r", encoding="utf-8", errors="ignore") as file_handle:
        for line in file_handle:
            if not line.strip():
                continue

            try:
                year = int(line[11:15])
                month = int(line[15:17])
            except (ValueError, IndexError):
                continue

            if year < start_year - 1 or year > end_year:
                continue

            element = line[17:21]
            if element not in ("TMIN", "TMAX"):
                continue

            season = season_of(month)
            if not season:
                continue

            season_year = year
            if season == "winter" and month == 12:
                season_year = year + 1

            in_annual_range = start_year <= year <= end_year
            in_season_range = start_year <= season_year <= end_year
            if not in_annual_range and not in_season_range:
                continue

            annual_row = annual_sums[year] if in_annual_range else None
            season_row = season_sums[season][season_year] if in_season_range else None

            base = 21
            is_tmin = element == "TMIN"
            for i in range(31):
                off = base + i * 8
                value_str = line[off : off + 5]
                if len(value_str) < 5:
                    continue

                try:
                    value = int(value_str)
                except ValueError:
                    continue

                if value == -9999:
                    continue

                value_c = value / 10.0
                if is_tmin:
                    if annual_row is not None:
                        annual_row["tmin_sum"] += value_c
                        annual_row["tmin_n"] += 1
                    if season_row is not None:
                        season_row["tmin_sum"] += value_c
                        season_row["tmin_n"] += 1
                else:
                    if annual_row is not None:
                        annual_row["tmax_sum"] += value_c
                        annual_row["tmax_n"] += 1
                    if season_row is not None:
                        season_row["tmax_sum"] += value_c
                        season_row["tmax_n"] += 1

    return {
        "annual": _rows_from_bucket(annual_sums, start_year, end_year),
        "seasons": {
            "spring": _rows_from_bucket(season_sums["spring"], start_year, end_year),
            "summer": _rows_from_bucket(season_sums["summer"], start_year, end_year),
            "autumn": _rows_from_bucket(season_sums["autumn"], start_year, end_year),
            "winter": _rows_from_bucket(season_sums["winter"], start_year, end_year),
        },
    }


def parse_dly_annual(dly_path: str, start_year: int, end_year: int):
    return parse_dly_annual_and_seasons(dly_path, start_year, end_year)["annual"]


def _merge_range(current_first: Optional[int], current_last: Optional[int], new_first: int, new_last: int) -> tuple[int, int]:
    first = new_first if current_first is None else min(current_first, new_first)
    last = new_last if current_last is None else max(current_last, new_last)
    return first, last


def load_catalog(data_dir: Path) -> Dict[str, object]:
    ensure_data_files(data_dir)

    stations_path = data_dir / STATIONS_FILE
    inventory_path = data_dir / INVENTORY_FILE

    stations_by_id: Dict[str, Dict[str, object]] = {}

    with stations_path.open("r", encoding="utf-8", errors="ignore") as file_handle:
        for raw_line in file_handle:
            line = raw_line.rstrip("\n")
            if len(line) < 71:
                continue

            station_id = line[0:11].strip()
            if not station_id:
                continue

            latitude = _parse_float(line[12:20])
            longitude = _parse_float(line[21:30])
            if latitude is None or longitude is None:
                continue

            stations_by_id[station_id] = {
                "id": station_id,
                "name": _format_station_name(station_id, line[41:71]),
                "state": line[38:40].strip() or None,
                "latitude": latitude,
                "longitude": longitude,
                "tminFirst": None,
                "tminLast": None,
                "tmaxFirst": None,
                "tmaxLast": None,
            }

    with inventory_path.open("r", encoding="utf-8", errors="ignore") as file_handle:
        for raw_line in file_handle:
            line = raw_line.rstrip("\n")
            if len(line) < 45:
                continue

            station_id = line[0:11].strip()
            element = line[31:35].strip()
            first_year = _parse_int(line[36:40])
            last_year = _parse_int(line[41:45])

            if station_id not in stations_by_id:
                continue
            if element not in {"TMIN", "TMAX"}:
                continue
            if first_year is None or last_year is None:
                continue

            station = stations_by_id[station_id]

            if element == "TMIN":
                station["tminFirst"], station["tminLast"] = _merge_range(
                    station["tminFirst"], station["tminLast"], first_year, last_year
                )
            else:
                station["tmaxFirst"], station["tmaxLast"] = _merge_range(
                    station["tmaxFirst"], station["tmaxLast"], first_year, last_year
                )

    stations: List[Dict[str, object]] = []
    earliest_year: Optional[int] = None
    latest_year: Optional[int] = None

    for station in stations_by_id.values():
        if station["tminFirst"] is None or station["tminLast"] is None:
            continue
        if station["tmaxFirst"] is None or station["tmaxLast"] is None:
            continue

        stations.append(station)

        start = min(int(station["tminFirst"]), int(station["tmaxFirst"]))
        end = max(int(station["tminLast"]), int(station["tmaxLast"]))

        if earliest_year is None or start < earliest_year:
            earliest_year = start
        if latest_year is None or end > latest_year:
            latest_year = end

    if earliest_year is None:
        earliest_year = 1800
    if latest_year is None:
        latest_year = 2025
    else:
        latest_year = min(latest_year, 2025)

    return {
        "stations": stations,
        "meta": {
            "earliestYear": earliest_year,
            "latestYear": latest_year,
            "stationCount": len(stations),
        },
    }


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)

    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(d_lon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return r * c


def find_stations(
    catalog: Dict[str, object],
    *,
    lat: float,
    lon: float,
    radius_km: float,
    limit: int,
    start_year: int,
    end_year: int,
) -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    delta_lat = radius_km / 111.0
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-9:
        delta_lon = 180.0
    else:
        delta_lon = min(180.0, radius_km / (111.0 * abs(cos_lat)))

    lat_min = lat - delta_lat
    lat_max = lat + delta_lat
    lon_min = lon - delta_lon
    lon_max = lon + delta_lon

    def lon_in_range(station_lon: float) -> bool:
        if lon_min >= -180 and lon_max <= 180:
            return lon_min <= station_lon <= lon_max
        if lon_min < -180:
            return station_lon >= (lon_min + 360) or station_lon <= lon_max
        if lon_max > 180:
            return station_lon >= lon_min or station_lon <= (lon_max - 360)
        return False

    for station in catalog["stations"]:
        station_lat = float(station["latitude"])
        station_lon = float(station["longitude"])
        if station_lat < lat_min or station_lat > lat_max:
            continue
        if not lon_in_range(station_lon):
            continue

        tmin_first = int(station["tminFirst"])
        tmin_last = int(station["tminLast"])
        tmax_first = int(station["tmaxFirst"])
        tmax_last = int(station["tmaxLast"])

        # Inventory range covers full query interval; gaps are allowed.
        if not (tmin_first <= start_year and tmin_last >= end_year):
            continue
        if not (tmax_first <= start_year and tmax_last >= end_year):
            continue

        distance_km = _haversine_km(lat, lon, station_lat, station_lon)
        if distance_km > radius_km:
            continue

        out.append(
            {
                "id": station["id"],
                "name": station["name"],
                "state": station["state"],
                "latitude": station["latitude"],
                "longitude": station["longitude"],
                "distanceKm": distance_km,
                "tminFirst": tmin_first,
                "tminLast": tmin_last,
                "tmaxFirst": tmax_first,
                "tmaxLast": tmax_last,
            }
        )

    out.sort(key=lambda row: float(row["distanceKm"]))
    return out[:limit]


