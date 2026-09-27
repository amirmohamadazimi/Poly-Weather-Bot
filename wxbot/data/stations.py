"""Resolution stations for Polymarket's daily temperature markets.

Each market names its resolution station in the description / resolutionSource
(e.g. a Weather Underground URL ending in the ICAO code). The bot reads the
code from the market itself and only trades markets whose station is listed
here, so a forecast is always taken at the exact point the market settles on.

Add a city by adding its station: ICAO code, coordinates, IANA timezone.
`rounding` describes how the official reading maps onto whole-degree buckets:
"round" for whole-degree reports (METAR / Weather Underground / NOAA).
Stations whose resolution rule is not yet understood are `enabled=False`:
they are shown on the dashboard but never traded.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Station:
    code: str
    name: str
    lat: float
    lon: float
    tz: str
    rounding: str = "round"
    enabled: bool = True
    note: str = ""


_STATIONS = [
    # North America
    Station("KLGA", "New York LaGuardia", 40.7769, -73.8740, "America/New_York"),
    Station("KORD", "Chicago O'Hare", 41.9742, -87.9073, "America/Chicago"),
    Station("KDAL", "Dallas Love Field", 32.8471, -96.8518, "America/Chicago"),
    Station("KMIA", "Miami Intl", 25.7959, -80.2870, "America/New_York"),
    Station("KATL", "Atlanta Hartsfield", 33.6407, -84.4277, "America/New_York"),
    Station("KSEA", "Seattle-Tacoma", 47.4502, -122.3088, "America/Los_Angeles"),
    Station("KLAX", "Los Angeles Intl", 33.9416, -118.4085, "America/Los_Angeles"),
    Station("KDEN", "Denver Intl", 39.8561, -104.6737, "America/Denver"),
    Station("KAUS", "Austin Bergstrom", 30.1945, -97.6699, "America/Chicago"),
    Station("KHOU", "Houston Hobby", 29.6454, -95.2789, "America/Chicago"),
    Station("KPHX", "Phoenix Sky Harbor", 33.4342, -112.0116, "America/Phoenix"),
    Station("KBOS", "Boston Logan", 42.3656, -71.0096, "America/New_York"),
    Station("KSFO", "San Francisco Intl", 37.6213, -122.3790, "America/Los_Angeles"),
    Station("CYYZ", "Toronto Pearson", 43.6777, -79.6248, "America/Toronto"),
    Station("MMMX", "Mexico City Intl", 19.4361, -99.0719, "America/Mexico_City"),
    # South America
    Station("SAEZ", "Buenos Aires Ezeiza", -34.8222, -58.5358, "America/Argentina/Buenos_Aires"),
    Station("SBGR", "Sao Paulo Guarulhos", -23.4356, -46.4731, "America/Sao_Paulo"),
    # Europe
    Station("EGLC", "London City Airport", 51.5048, 0.0495, "Europe/London"),
    Station("LFPG", "Paris Charles de Gaulle", 49.0097, 2.5479, "Europe/Paris"),
    Station("LEMD", "Madrid Barajas", 40.4983, -3.5676, "Europe/Madrid"),
    Station("EDDM", "Munich", 48.3538, 11.7861, "Europe/Berlin"),
    Station("LIMC", "Milan Malpensa", 45.6306, 8.7281, "Europe/Rome"),
    Station("EPWA", "Warsaw Chopin", 52.1657, 20.9671, "Europe/Warsaw"),
    Station("LTAC", "Ankara Esenboga", 40.1281, 32.9951, "Europe/Istanbul"),
    # Asia / Oceania
    Station("RKSI", "Seoul Incheon", 37.4602, 126.4407, "Asia/Seoul"),
    Station("RJTT", "Tokyo Haneda", 35.5494, 139.7798, "Asia/Tokyo"),
    Station("ZSPD", "Shanghai Pudong", 31.1443, 121.8083, "Asia/Shanghai"),
    Station("ZSJN", "Jinan Yaoqiang", 36.8572, 117.2159, "Asia/Shanghai"),
    Station("ZHCC", "Zhengzhou Xinzheng", 34.5197, 113.8409, "Asia/Shanghai"),
    Station("ZUUU", "Chengdu Shuangliu", 30.5785, 103.9471, "Asia/Shanghai"),
    Station("WSSS", "Singapore Changi", 1.3644, 103.9915, "Asia/Singapore"),
    Station("VILK", "Lucknow Amausi", 26.7606, 80.8893, "Asia/Kolkata"),
    Station("NZWN", "Wellington", -41.3272, 174.8053, "Pacific/Auckland"),
    Station("HKO", "Hong Kong Observatory", 22.3022, 114.1742, "Asia/Hong_Kong",
            rounding="unknown", enabled=False,
            note="Resolves on HKO absolute max to 0.1 degC; bucket edges not yet verified."),
]

STATIONS: dict[str, Station] = {s.code: s for s in _STATIONS}


def get_station(code: str | None) -> Station | None:
    return STATIONS.get((code or "").upper())
