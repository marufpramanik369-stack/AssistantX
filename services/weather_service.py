"""
weather_service.py
===================
Current conditions and short-range forecast lookups via the
OpenWeatherMap API (https://openweathermap.org/api) — chosen for its
generous free tier and simple REST interface, requiring only an API
key (config/secrets.py's `openweather_api_key`) with no OAuth flow.

Handles both current weather and a short forecast, geocodes plain
city-name queries automatically (OpenWeatherMap's One Call API expects
lat/lon, so a geocoding lookup happens transparently first), and caches
responses briefly to avoid re-fetching on every rephrased voice query
within the same few minutes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config.constants import HTTP_USER_AGENT, REQUEST_TIMEOUT_SECONDS, WEATHER_UNITS
from config.secrets import secrets
from core.logger import get_logger

logger = get_logger(__name__)

_CACHE_TTL_MINUTES = 15
_GEOCODE_URL = "https://api.openweathermap.org/geo/1.0/direct"
_CURRENT_WEATHER_URL = "https://api.openweathermap.org/data/2.5/weather"
_FORECAST_URL = "https://api.openweathermap.org/data/2.5/forecast"

_UNIT_SYMBOLS = {"metric": "°C", "imperial": "°F", "standard": "K"}
_WIND_UNITS = {"metric": "m/s", "imperial": "mph", "standard": "m/s"}


class WeatherServiceError(RuntimeError):
    """Raised when a weather lookup fails (missing API key, network
    failure, or an unrecognized location)."""


@dataclass
class Coordinates:
    latitude: float
    longitude: float
    resolved_name: str


@dataclass
class CurrentWeather:
    location: str
    temperature: float
    feels_like: float
    condition: str
    description: str
    humidity: int
    wind_speed: float
    units: str

    @property
    def temperature_unit(self) -> str:
        return _UNIT_SYMBOLS.get(self.units, "")

    @property
    def wind_unit(self) -> str:
        return _WIND_UNITS.get(self.units, "")

    def to_speech(self) -> str:
        return (
            f"It's currently {round(self.temperature)}{self.temperature_unit} in {self.location}, "
            f"with {self.description}. It feels like {round(self.feels_like)}{self.temperature_unit}."
        )


@dataclass
class ForecastEntry:
    timestamp: datetime
    temperature: float
    condition: str
    description: str
    precipitation_probability: float


@dataclass
class Forecast:
    location: str
    units: str
    entries: list[ForecastEntry]

    def to_speech(self, max_entries: int = 3) -> str:
        if not self.entries:
            return f"I couldn't find forecast data for {self.location}."
        unit_symbol = _UNIT_SYMBOLS.get(self.units, "")
        parts = []
        for entry in self.entries[:max_entries]:
            time_label = entry.timestamp.strftime("%A %I %p").lstrip("0")
            parts.append(f"{time_label}: {round(entry.temperature)}{unit_symbol}, {entry.description}")
        return f"Here's the forecast for {self.location}: " + "; ".join(parts) + "."


def _get_requests():
    try:
        import requests

        return requests
    except ImportError as exc:
        raise WeatherServiceError(
            "Weather lookups require the 'requests' package. Run: pip install requests"
        ) from exc


def _require_api_key() -> str:
    if not secrets.openweather_api_key:
        raise WeatherServiceError(
            "Weather lookups require an OpenWeatherMap API key. "
            "Add OPENWEATHER_API_KEY to your .env file (free tier available at openweathermap.org)."
        )
    return secrets.openweather_api_key


def _cache_key(prefix: str, location: str, units: str) -> str:
    return f"weather:{prefix}:{location.strip().lower()}:{units}"


def _cache_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=_CACHE_TTL_MINUTES)).isoformat()


def _try_get_cached(cache_key: str):
    try:
        from database import db_manager

        return db_manager.get_cache(cache_key)
    except Exception as exc:  # noqa: BLE001 - cache is a pure optimization
        logger.debug("Weather cache unavailable (%s); proceeding without it.", exc)
        return None


def _try_set_cached(cache_key: str, value) -> None:
    try:
        from database import db_manager

        db_manager.set_cache(cache_key, value, expires_at=_cache_expiry())
    except Exception as exc:  # noqa: BLE001
        logger.debug("Could not write weather cache (%s); continuing without caching.", exc)


def geocode_location(location_name: str) -> Coordinates:
    """
    Resolve a plain-text place name (e.g. "Dhaka", "Paris, France") into
    latitude/longitude, required by OpenWeatherMap's weather endpoints.

    Raises:
        WeatherServiceError: if the location can't be resolved or the
            API key is missing/invalid.
    """
    api_key = _require_api_key()
    requests = _get_requests()

    try:
        response = requests.get(
            _GEOCODE_URL,
            params={"q": location_name, "limit": 1, "appid": api_key},
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherServiceError(f"Geocoding request failed: {exc}") from exc

    results = response.json()
    if not results:
        raise WeatherServiceError(f"Could not find a location matching '{location_name}'.")

    top = results[0]
    resolved_name = top.get("name", location_name)
    country = top.get("country")
    if country:
        resolved_name = f"{resolved_name}, {country}"

    return Coordinates(latitude=top["lat"], longitude=top["lon"], resolved_name=resolved_name)


def get_current_weather(location: str, units: str = WEATHER_UNITS) -> CurrentWeather:
    """
    Fetch current weather conditions for a location.

    Args:
        location: A plain place name, e.g. "Dhaka" or "New York, US".
        units: 'metric' (Celsius), 'imperial' (Fahrenheit), or 'standard' (Kelvin).

    Raises:
        WeatherServiceError: on missing API key, unresolved location,
            or a network/API failure.
    """
    cache_key = _cache_key("current", location, units)
    cached = _try_get_cached(cache_key)
    if cached is not None:
        return CurrentWeather(**cached)

    api_key = _require_api_key()
    requests = _get_requests()
    coords = geocode_location(location)

    try:
        response = requests.get(
            _CURRENT_WEATHER_URL,
            params={
                "lat": coords.latitude,
                "lon": coords.longitude,
                "appid": api_key,
                "units": units,
            },
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherServiceError(f"Current weather request failed: {exc}") from exc

    data = response.json()
    weather_info = (data.get("weather") or [{}])[0]
    main = data.get("main", {})
    wind = data.get("wind", {})

    result = CurrentWeather(
        location=coords.resolved_name,
        temperature=main.get("temp", 0.0),
        feels_like=main.get("feels_like", 0.0),
        condition=weather_info.get("main", "Unknown"),
        description=weather_info.get("description", "unknown conditions"),
        humidity=main.get("humidity", 0),
        wind_speed=wind.get("speed", 0.0),
        units=units,
    )

    _try_set_cached(cache_key, result.__dict__)
    logger.info("Fetched current weather for %s: %.1f%s", result.location, result.temperature, result.temperature_unit)
    return result


def get_forecast(location: str, units: str = WEATHER_UNITS, hours_ahead: int = 24) -> Forecast:
    """
    Fetch a short-range forecast (3-hour interval steps, via
    OpenWeatherMap's free /forecast endpoint) covering roughly the next
    `hours_ahead` hours.

    Raises:
        WeatherServiceError: on missing API key, unresolved location,
            or a network/API failure.
    """
    cache_key = _cache_key(f"forecast:{hours_ahead}", location, units)
    cached = _try_get_cached(cache_key)
    if cached is not None:
        entries = [
            ForecastEntry(
                timestamp=datetime.fromisoformat(e["timestamp"]),
                temperature=e["temperature"],
                condition=e["condition"],
                description=e["description"],
                precipitation_probability=e["precipitation_probability"],
            )
            for e in cached["entries"]
        ]
        return Forecast(location=cached["location"], units=cached["units"], entries=entries)

    api_key = _require_api_key()
    requests = _get_requests()
    coords = geocode_location(location)

    try:
        response = requests.get(
            _FORECAST_URL,
            params={
                "lat": coords.latitude,
                "lon": coords.longitude,
                "appid": api_key,
                "units": units,
            },
            headers={"User-Agent": HTTP_USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise WeatherServiceError(f"Forecast request failed: {exc}") from exc

    data = response.json()
    max_entries = max(1, hours_ahead // 3)  # API returns 3-hour steps

    entries: list[ForecastEntry] = []
    for item in data.get("list", [])[:max_entries]:
        weather_info = (item.get("weather") or [{}])[0]
        entries.append(
            ForecastEntry(
                timestamp=datetime.fromtimestamp(item["dt"], tz=timezone.utc),
                temperature=item.get("main", {}).get("temp", 0.0),
                condition=weather_info.get("main", "Unknown"),
                description=weather_info.get("description", "unknown conditions"),
                precipitation_probability=item.get("pop", 0.0) * 100,
            )
        )

    forecast = Forecast(location=coords.resolved_name, units=units, entries=entries)

    _try_set_cached(
        cache_key,
        {
            "location": forecast.location,
            "units": forecast.units,
            "entries": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "temperature": e.temperature,
                    "condition": e.condition,
                    "description": e.description,
                    "precipitation_probability": e.precipitation_probability,
                }
                for e in forecast.entries
            ],
        },
    )
    logger.info("Fetched %d-entry forecast for %s.", len(entries), forecast.location)
    return forecast


def is_available() -> bool:
    """Check whether weather lookups are usable (API key configured and
    the 'requests' package installed) — does not verify network reachability."""
    if not secrets.openweather_api_key:
        return False
    try:
        _get_requests()
        return True
    except WeatherServiceError:
        return False

