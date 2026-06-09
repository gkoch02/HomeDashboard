from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class StalenessLevel(Enum):
    """Age-based staleness level for cached data relative to its TTL."""

    FRESH = "fresh"  # within TTL
    AGING = "aging"  # 1-2x TTL
    STALE = "stale"  # 2-4x TTL
    EXPIRED = "expired"  # >4x TTL — data should not be used


@dataclass
class CalendarEvent:
    summary: str
    start: datetime
    end: datetime
    is_all_day: bool = False
    location: str | None = None
    calendar_name: str | None = None
    event_id: str | None = None  # Google Calendar event ID for incremental sync


@dataclass
class DayForecast:
    date: date
    high: float
    low: float
    icon: str
    description: str
    precip_chance: float | None = None  # 0.0–1.0 probability of precipitation


@dataclass
class WeatherAlert:
    event: str  # Short alert name, e.g. "Flood Watch"


@dataclass
class WeatherData:
    current_temp: float
    current_icon: str
    current_description: str
    high: float
    low: float
    humidity: int
    forecast: list[DayForecast] = field(default_factory=list)
    alerts: list[WeatherAlert] = field(default_factory=list)
    feels_like: float | None = None
    wind_speed: float | None = None  # speed in configured units (mph or m/s)
    wind_deg: float | None = None  # wind direction in degrees (0=N, 90=E, etc.)
    pressure: float | None = None  # atmospheric pressure in hPa
    uv_index: float | None = None  # UV index (0-11+)
    sunrise: datetime | None = None
    sunset: datetime | None = None
    location_name: str | None = None  # City name from OWM (e.g. "New York")
    units: str | None = None  # OWM unit system: "imperial", "metric", or "standard"


@dataclass
class Birthday:
    name: str
    date: date
    age: int | None = None


@dataclass
class AirQualityData:
    aqi: int  # 0–500 EPA AQI computed from PM2.5
    category: str  # "Good" / "Moderate" / "Unhealthy for Sensitive Groups" / ...
    pm25: float  # PM2.5 60-minute average µg/m³ (used for AQI computation)
    pm10: float | None = None  # PM10 µg/m³ (may be absent)
    sensor_id: int | None = None  # PurpleAir sensor_index
    pm1: float | None = None  # PM1.0 µg/m³ (may be absent)
    temperature: float | None = None  # °F — PurpleAir ambient sensor reading
    humidity: float | None = None  # % relative humidity — PurpleAir ambient
    pressure: float | None = None  # hPa atmospheric pressure — PurpleAir ambient
    fallback_fields: set[str] = field(default_factory=set)  # Fields filled from OWM fallback


@dataclass
class HostData:
    hostname: str | None = None
    uptime_seconds: float | None = None  # seconds since boot, from /proc/uptime
    load_1m: float | None = None  # 1-minute load average
    load_5m: float | None = None  # 5-minute load average
    load_15m: float | None = None  # 15-minute load average
    ram_used_mb: float | None = None  # RAM in use (total - available), MB
    ram_total_mb: float | None = None  # Total RAM, MB
    disk_used_gb: float | None = None  # Root filesystem used, GB
    disk_total_gb: float | None = None  # Root filesystem total, GB
    cpu_temp_c: float | None = None  # CPU temperature °C, from thermal_zone0
    ip_address: str | None = None  # Primary outbound IPv4 address


@dataclass
class DashboardData:
    events: list[CalendarEvent] = field(default_factory=list)
    weather: WeatherData | None = None
    birthdays: list[Birthday] = field(default_factory=list)
    air_quality: AirQualityData | None = None
    host_data: HostData | None = None
    fetched_at: datetime = field(default_factory=datetime.now)
    is_stale: bool = False  # True when any component was filled from cache
    stale_sources: list[str] = field(default_factory=list)  # e.g. ["events", "weather"]
    source_staleness: dict[str, StalenessLevel] = field(default_factory=dict)
