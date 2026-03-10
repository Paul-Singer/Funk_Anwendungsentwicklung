from __future__ import annotations

import math
import os
import shutil
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional

import requests

STATIONS_FILE = "ghcnd-stations.txt"
INVENTORY_FILE = "ghcnd-inventory.txt"
NOAA_BASE_URL = "https://noaa-ghcn-pds.s3.amazonaws.com"
STATIONS_URL = f"{NOAA_BASE_URL}/{STATIONS_FILE}"
INVENTORY_URL = f"{NOAA_BASE_URL}/{INVENTORY_FILE}"
STATION_DAILY_URL = f"{NOAA_BASE_URL}/csv/by_station/{{station_id}}.csv"


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
    station_dir = os.path.join(data_dir, "by_station")
    os.makedirs(station_dir, exist_ok=True)
    out_path = os.path.join(station_dir, f"{station_id}.csv")

    if os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return out_path

    url = STATION_DAILY_URL.format(station_id=station_id)
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


def _new_month_bucket() -> Dict[str, float | int]:
    return {"tmin_sum": 0.0, "tmin_n": 0, "tmax_sum": 0.0, "tmax_n": 0}


def _mean_or_none(values: List[float], min_count: int) -> float | None:
    if len(values) < min_count:
        return None
    return round(sum(values) / len(values), 1)


def _climate_groups_for_year(year: int) -> Dict[str, List[tuple[int, int]]]:
    return {
        "DJF": [(year - 1, 12), (year, 1), (year, 2)],
        "MAM": [(year, 3), (year, 4), (year, 5)],
        "JJA": [(year, 6), (year, 7), (year, 8)],
        "SON": [(year, 9), (year, 10), (year, 11)],
    }


def _season_group_mapping(latitude: float) -> Dict[str, str]:
    if latitude < 0:
        return {
            "summer": "DJF",
            "autumn": "MAM",
            "winter": "JJA",
            "spring": "SON",
        }
    return {
        "winter": "DJF",
        "spring": "MAM",
        "summer": "JJA",
        "autumn": "SON",
    }


def parse_dly_annual_and_seasons(dly_path: str, start_year: int, end_year: int, latitude: float):
    month_sums: Dict[tuple[int, int], Dict[str, float | int]] = {}

    with open(dly_path, "r", encoding="utf-8", errors="ignore") as file_handle:
        for line in file_handle:
            line = line.strip()
            if not line:
                continue

            parts = line.split(",")
            if len(parts) < 4:
                continue

            date_code = parts[1]
            if len(date_code) != 8 or not date_code.isdigit():
                continue

            year = int(date_code[0:4])
            month = int(date_code[4:6])
            if year < start_year - 1 or year > end_year:
                continue

            element = parts[2]
            if element not in {"TMIN", "TMAX"}:
                continue

            try:
                value = int(parts[3])
            except ValueError:
                continue
            if value == -9999:
                continue

            key = (year, month)
            if key not in month_sums:
                month_sums[key] = _new_month_bucket()
            bucket = month_sums[key]
            value_c = value / 10.0

            if element == "TMIN":
                bucket["tmin_sum"] += value_c
                bucket["tmin_n"] += 1
            else:
                bucket["tmax_sum"] += value_c
                bucket["tmax_n"] += 1

    month_means: Dict[tuple[int, int], Dict[str, float | None]] = {}
    for key, bucket in month_sums.items():
        tmin = None
        tmax = None
        if int(bucket["tmin_n"]) > 0:
            tmin = float(bucket["tmin_sum"]) / int(bucket["tmin_n"])
        if int(bucket["tmax_n"]) > 0:
            tmax = float(bucket["tmax_sum"]) / int(bucket["tmax_n"])
        month_means[key] = {"tmin": tmin, "tmax": tmax}

    annual_rows: List[Dict[str, float | int | None]] = []
    annual_months_used: List[Dict[str, int]] = []
    season_rows: Dict[str, List[Dict[str, float | int | None]]] = {
        "spring": [],
        "summer": [],
        "autumn": [],
        "winter": [],
    }
    season_months_used: Dict[str, List[Dict[str, int]]] = {
        "spring": [],
        "summer": [],
        "autumn": [],
        "winter": [],
    }

    for year in range(start_year, end_year + 1):
        annual_tmin_month_means: List[float] = []
        annual_tmax_month_means: List[float] = []
        for month in range(1, 13):
            means = month_means.get((year, month))
            if not means:
                continue
            if means["tmin"] is not None:
                annual_tmin_month_means.append(float(means["tmin"]))
            if means["tmax"] is not None:
                annual_tmax_month_means.append(float(means["tmax"]))

        annual_rows.append(
            {
                "year": year,
                "tmin": _mean_or_none(annual_tmin_month_means, 10),
                "tmax": _mean_or_none(annual_tmax_month_means, 10),
            }
        )
        annual_months_used.append(
            {
                "year": year,
                "tminMonths": len(annual_tmin_month_means),
                "tmaxMonths": len(annual_tmax_month_means),
            }
        )

        climate_groups = _climate_groups_for_year(year)
        season_to_group = _season_group_mapping(latitude)
        for season in ("spring", "summer", "autumn", "winter"):
            tmin_month_means: List[float] = []
            tmax_month_means: List[float] = []

            for month_key in climate_groups[season_to_group[season]]:
                means = month_means.get(month_key)
                if not means:
                    continue
                if means["tmin"] is not None:
                    tmin_month_means.append(float(means["tmin"]))
                if means["tmax"] is not None:
                    tmax_month_means.append(float(means["tmax"]))

            season_rows[season].append(
                {
                    "year": year,
                    "tmin": _mean_or_none(tmin_month_means, 2),
                    "tmax": _mean_or_none(tmax_month_means, 2),
                }
            )
            season_months_used[season].append(
                {
                    "year": year,
                    "tminMonths": len(tmin_month_means),
                    "tmaxMonths": len(tmax_month_means),
                }
            )

    return {
        "annual": annual_rows,
        "seasons": season_rows,
        "annualMonthsUsed": annual_months_used,
        "seasonalMonthsUsed": season_months_used,
    }


def parse_dly_annual(dly_path: str, start_year: int, end_year: int):
    return parse_dly_annual_and_seasons(dly_path, start_year, end_year, 0.0)["annual"]


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
                "name": line[41:71].strip() or station_id,
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


