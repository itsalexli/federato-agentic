"""Optional external enrichment.

The schema tells us a location is in Houston and tagged `flood`. It does not
tell us how hard the weather has actually hit that coordinate. Open-Meteo's
archive is free, keyless, and answers exactly that, so the agent pulls a
five-year severe-weather history for each account's largest location and lets
it move the score.

This is strictly a bonus lane. Every failure path here is a shrug: the run
continues, the submission keeps its base score, and the trace says the
enrichment was unavailable rather than pretending it was clean.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from ..config import CACHE_DIR, ENRICHMENT_ENABLED

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Thresholds for "a day that would have generated claims activity".
HEAVY_RAIN_MM = 50.0
HIGH_GUST_KMH = 90.0

# Points added to / removed from the base score. Deliberately small: external
# weather is a tiebreaker between comparable risks, not a reason to overturn
# the carrier's own appetite table.
MAX_ADJUSTMENT = 5.0


@dataclass
class WeatherRisk:
    latitude: float
    longitude: float
    years: int
    heavy_rain_days: int
    high_wind_days: int
    max_gust_kmh: float | None
    adjustment: float
    summary: str
    source: str = "Open-Meteo ERA5 archive"

    def as_dict(self) -> dict:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "years": self.years,
            "heavy_rain_days": self.heavy_rain_days,
            "high_wind_days": self.high_wind_days,
            "max_gust_kmh": self.max_gust_kmh,
            "adjustment": round(self.adjustment, 1),
            "summary": self.summary,
            "source": self.source,
        }


class WeatherEnricher:
    """Cached, fail-soft client for the Open-Meteo archive."""

    def __init__(self, enabled: bool = ENRICHMENT_ENABLED, years: int = 5):
        self.enabled = enabled
        self.years = years
        self.unavailable_reason: str | None = None
        self._memo: dict[tuple[float, float], WeatherRisk | None] = {}
        self._cache_file = CACHE_DIR / "weather.json"
        self._disk: dict[str, dict] = {}
        if self.enabled:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            if self._cache_file.exists():
                try:
                    self._disk = json.loads(self._cache_file.read_text())
                except Exception:
                    self._disk = {}

    def _persist(self) -> None:
        try:
            self._cache_file.write_text(json.dumps(self._disk))
        except OSError:
            pass

    def for_location(self, lat: float | None, lon: float | None) -> WeatherRisk | None:
        if not self.enabled or lat is None or lon is None:
            return None
        # Round to ~1km: neighbouring buildings share a climate history, and
        # this keeps the cache small across a 158-row queue.
        key = (round(float(lat), 2), round(float(lon), 2))
        if key in self._memo:
            return self._memo[key]

        cache_key = f"{key[0]},{key[1]},{self.years}"
        if cache_key in self._disk:
            risk = WeatherRisk(**self._disk[cache_key])
            self._memo[key] = risk
            return risk

        end = date.today() - timedelta(days=7)   # archive lags real time
        start = end - timedelta(days=365 * self.years)
        params = {
            "latitude": key[0],
            "longitude": key[1],
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "daily": "precipitation_sum,wind_gusts_10m_max",
            "timezone": "UTC",
        }
        daily = None
        for attempt in range(3):
            try:
                resp = httpx.get(ARCHIVE_URL, params=params, timeout=20.0)
                # The archive is free and rate-limited; a short backoff clears
                # it far more often than not.
                if resp.status_code == 429 and attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                resp.raise_for_status()
                daily = resp.json().get("daily", {})
                break
            except Exception as exc:
                if attempt == 2:
                    self.unavailable_reason = f"{type(exc).__name__}: {exc}"
                    self._memo[key] = None
                    return None
                time.sleep(1.0 * (attempt + 1))
        if daily is None:
            self._memo[key] = None
            return None

        rain = [v for v in (daily.get("precipitation_sum") or []) if v is not None]
        gust = [v for v in (daily.get("wind_gusts_10m_max") or []) if v is not None]
        if not rain and not gust:
            self._memo[key] = None
            return None

        heavy = sum(1 for v in rain if v >= HEAVY_RAIN_MM)
        windy = sum(1 for v in gust if v >= HIGH_GUST_KMH)
        risk = WeatherRisk(
            latitude=key[0], longitude=key[1], years=self.years,
            heavy_rain_days=heavy, high_wind_days=windy,
            max_gust_kmh=round(max(gust), 1) if gust else None,
            adjustment=_adjust(heavy, windy),
            summary=_summarize(heavy, windy, self.years),
        )
        self._memo[key] = risk
        self._disk[cache_key] = risk.as_dict()
        self._persist()
        return risk


def _adjust(heavy_rain_days: int, high_wind_days: int) -> float:
    """Map observed severe-weather frequency onto a small score adjustment.

    A benign site earns back a little; a repeatedly battered one gives some up.
    Bounded at +/-MAX_ADJUSTMENT so it can reorder near-ties and nothing more.
    """
    events = heavy_rain_days + high_wind_days
    if events == 0:
        return MAX_ADJUSTMENT * 0.6
    if events <= 3:
        return MAX_ADJUSTMENT * 0.2
    if events <= 10:
        return 0.0
    if events <= 25:
        return -MAX_ADJUSTMENT * 0.5
    return -MAX_ADJUSTMENT


def _summarize(heavy: int, windy: int, years: int) -> str:
    if heavy == 0 and windy == 0:
        return f"No days over {HEAVY_RAIN_MM:.0f}mm rain or {HIGH_GUST_KMH:.0f}km/h gusts in {years} years."
    parts = []
    if heavy:
        parts.append(f"{heavy} day{'s' if heavy != 1 else ''} over {HEAVY_RAIN_MM:.0f}mm rain")
    if windy:
        parts.append(f"{windy} day{'s' if windy != 1 else ''} with gusts over {HIGH_GUST_KMH:.0f}km/h")
    return f"{' and '.join(parts)} in the last {years} years at the primary location."
