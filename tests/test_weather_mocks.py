from __future__ import annotations

import shutil
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests
from fastapi import HTTPException

from backend import ghcn, main

TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


def _catalog_meta(earliest: int = 1900, latest: int = 2025) -> dict:
    return {
        "meta": {
            "earliestYear": earliest,
            "latestYear": latest,
            "stationCount": 1,
        },
        "stations": [],
    }


def _reset_case_dir(case_name: str) -> Path:
    case_dir = TEST_TMP_ROOT / case_name
    if case_dir.exists():
        shutil.rmtree(case_dir, ignore_errors=True)
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


class TestWeatherApiWithMocks(unittest.TestCase):
    def test_api_stations_success_with_mocked_station_search(self) -> None:
        # Mocked Stationsantwort fuer den API-Endpunkt.
        mocked_result = [
            {
                "id": "TEST0000001",
                "name": "Mock Station",
                "state": "BW",
                "latitude": 48.0,
                "longitude": 9.0,
                "distanceKm": 12.3,
                "tminFirst": 1990,
                "tminLast": 2025,
                "tmaxFirst": 1990,
                "tmaxLast": 2025,
            }
        ]

        with patch("backend.main._require_catalog", return_value=_catalog_meta()):
            with patch("backend.main.find_stations", return_value=mocked_result) as find_mock:
                result = main.api_stations(
                    lat=48.0,
                    lon=9.0,
                    radiusKm=50.0,
                    limit=5,
                    startYear=2000,
                    endYear=2001,
                )

        self.assertEqual(result, mocked_result)
        find_mock.assert_called_once_with(
            _catalog_meta(),
            lat=48.0,
            lon=9.0,
            radius_km=50.0,
            limit=5,
            start_year=2000,
            end_year=2001,
        )

    def test_api_stations_returns_empty_list_when_no_station_found(self) -> None:
        # Leere Antwort simuliert den Fall "keine passende Station".
        with patch("backend.main._require_catalog", return_value=_catalog_meta()):
            with patch("backend.main.find_stations", return_value=[]):
                result = main.api_stations(
                    lat=0.0,
                    lon=0.0,
                    radiusKm=5.0,
                    limit=5,
                    startYear=2000,
                    endYear=2001,
                )

        self.assertEqual(result, [])

    def test_api_station_annual_success_with_stubbed_weather_payload(self) -> None:
        # Wetterdatenberechnung wird als Stub kontrolliert zurueckgegeben.
        station_id = "TEST0000001"
        mocked_payload = {
            "annual": [{"year": 2020, "tmin": 5.1, "tmax": 14.2}],
            "seasons": {"spring": [], "summer": [], "autumn": [], "winter": []},
            "annualMonthsUsed": [{"year": 2020, "tminMonths": 12, "tmaxMonths": 12}],
            "seasonalMonthsUsed": {"spring": [], "summer": [], "autumn": [], "winter": []},
        }

        with patch("backend.main._require_catalog", return_value=_catalog_meta()):
            with patch.object(main, "station_ids", {station_id}):
                with patch.object(main, "stations_by_id", {station_id: {"latitude": 48.0}}):
                    with patch("backend.main._read_cache_epoch", return_value=7):
                        with patch(
                            "backend.main.compute_station_data_cached",
                            return_value=mocked_payload,
                        ) as compute_mock:
                            result = main.api_station_annual(station_id=station_id, startYear=2020, endYear=2020)

        self.assertEqual(result, mocked_payload)
        compute_mock.assert_called_once_with(7, station_id, 2020, 2020, 48.0)

    def test_api_station_annual_maps_network_error_to_http_503(self) -> None:
        # Netzwerkfehler aus externer Quelle wird als 503 sichtbar gemacht.
        station_id = "TEST0000001"

        with patch("backend.main._require_catalog", return_value=_catalog_meta()):
            with patch.object(main, "station_ids", {station_id}):
                with patch.object(main, "stations_by_id", {station_id: {"latitude": 48.0}}):
                    with patch("backend.main._read_cache_epoch", return_value=1):
                        with patch(
                            "backend.main.compute_station_data_cached",
                            side_effect=requests.RequestException("timeout"),
                        ):
                            with self.assertRaises(HTTPException) as err:
                                main.api_station_annual(station_id=station_id, startYear=2020, endYear=2020)

        self.assertEqual(err.exception.status_code, 503)
        self.assertIn("nicht erreichbar", err.exception.detail)


class TestWeatherDataLoadingAndParsing(unittest.TestCase):
    def test_ensure_dly_downloads_weather_data_via_mocked_requests(self) -> None:
        # Externer Download wird per Mock isoliert getestet.
        station_id = "TEST0000001"
        response = Mock()
        response.raise_for_status = Mock()
        response.iter_content = Mock(return_value=[b"abc", b"def"])

        case_dir = _reset_case_dir("ensure_dly_case")
        with patch("backend.ghcn.requests.get", return_value=response) as get_mock:
            out_path = ghcn.ensure_dly(station_id, str(case_dir))

        saved = Path(out_path).read_bytes()
        self.assertEqual(saved, b"abcdef")
        get_mock.assert_called_once_with(
            ghcn.STATION_DAILY_URL.format(station_id=station_id),
            stream=True,
            timeout=120,
        )

    def test_parse_small_dataset_matches_current_djf_and_annual_logic(self) -> None:
        # Aktuelle Logik im Code: DJF = Dez Vorjahr + Jan/Feb Jahr; annual braucht >=10 Monate.
        rows = [
            "TEST0000001,20221210,TMIN,20",
            "TEST0000001,20221210,TMAX,80",
            "TEST0000001,20230110,TMIN,30",
            "TEST0000001,20230110,TMAX,90",
            "TEST0000001,20230210,TMIN,40",
            "TEST0000001,20230210,TMAX,100",
            "TEST0000001,bad-date,TMIN,999",
            "TEST0000001,20230111,TMIN,invalid",
        ]

        case_dir = _reset_case_dir("parse_case")
        data_path = case_dir / "sample.csv"
        data_path.write_text("\n".join(rows) + "\n", encoding="utf-8")

        north = ghcn.parse_dly_annual_and_seasons(str(data_path), 2023, 2023, latitude=48.0)
        south = ghcn.parse_dly_annual_and_seasons(str(data_path), 2023, 2023, latitude=-33.0)

        self.assertEqual(north["seasons"]["winter"][0]["tmin"], 3.0)
        self.assertEqual(north["seasons"]["winter"][0]["tmax"], 9.0)
        self.assertEqual(south["seasons"]["summer"][0]["tmin"], 3.0)
        self.assertEqual(south["seasons"]["summer"][0]["tmax"], 9.0)
        self.assertIsNone(north["annual"][0]["tmin"])
        self.assertIsNone(north["annual"][0]["tmax"])


if __name__ == "__main__":
    unittest.main()
