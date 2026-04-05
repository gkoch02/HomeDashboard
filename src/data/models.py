from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum
from typing import Optional


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
    location: Optional[str] = None
    calendar_name: Optional[str] = None
    event_id: Optional[str] = None  # Google Calendar event ID for incremental sync


@dataclass
class DayForecast:
    date: date
    high: float
    low: float
    icon: str
    description: str
    precip_chance: Optional[float] = None  # 0.0–1.0 probability of precipitation


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
    feels_like: Optional[float] = None
    wind_speed: Optional[float] = None  # speed in configured units (mph or m/s)
    wind_deg: Optional[float] = None  # wind direction in degrees (0=N, 90=E, etc.)
    pressure: Optional[float] = None  # atmospheric pressure in hPa
    uv_index: Optional[float] = None  # UV index (0-11+)
    sunrise: Optional[datetime] = None
    sunset: Optional[datetime] = None
    location_name: Optional[str] = None  # City name from OWM (e.g. "New York")


@dataclass
class Birthday:
    name: str
    date: date
    age: Optional[int] = None


@dataclass
class AirQualityData:
    aqi: int  # 0–500 EPA AQI computed from PM2.5
    category: str  # "Good" / "Moderate" / "Unhealthy for Sensitive Groups" / ...
    pm25: float  # PM2.5 60-minute average µg/m³ (used for AQI computation)
    pm10: Optional[float] = None  # PM10 µg/m³ (may be absent)
    sensor_id: Optional[int] = None  # PurpleAir sensor_index
    pm1: Optional[float] = None  # PM1.0 µg/m³ (may be absent)
    temperature: Optional[float] = None  # °F — PurpleAir ambient sensor reading
    humidity: Optional[float] = None  # % relative humidity — PurpleAir ambient
    pressure: Optional[float] = None  # hPa atmospheric pressure — PurpleAir ambient
    fallback_fields: set[str] = field(default_factory=set)  # Fields filled from OWM fallback


@dataclass
class HostData:
    hostname: Optional[str] = None
    uptime_seconds: Optional[float] = None  # seconds since boot, from /proc/uptime
    load_1m: Optional[float] = None  # 1-minute load average
    load_5m: Optional[float] = None  # 5-minute load average
    load_15m: Optional[float] = None  # 15-minute load average
    ram_used_mb: Optional[float] = None  # RAM in use (total - available), MB
    ram_total_mb: Optional[float] = None  # Total RAM, MB
    disk_used_gb: Optional[float] = None  # Root filesystem used, GB
    disk_total_gb: Optional[float] = None  # Root filesystem total, GB
    cpu_temp_c: Optional[float] = None  # CPU temperature °C, from thermal_zone0
    ip_address: Optional[str] = None  # Primary outbound IPv4 address


@dataclass
class DashboardData:
    events: list[CalendarEvent] = field(default_factory=list)
    weather: Optional[WeatherData] = None
    birthdays: list[Birthday] = field(default_factory=list)
    air_quality: Optional[AirQualityData] = None
    host_data: Optional[HostData] = None
    fetched_at: datetime = field(default_factory=datetime.now)
    is_stale: bool = False  # True when any component was filled from cache
    stale_sources: list[str] = field(default_factory=list)  # e.g. ["events", "weather"]
    source_staleness: dict[str, StalenessLevel] = field(default_factory=dict)
