"""Realistic dummy data for development previews and testing.

Used by ``main.py --dummy`` to render a dashboard without API credentials.
"""

from datetime import datetime, timedelta, timezone, tzinfo

from src.data.models import (
    AirQualityData, Birthday, CalendarEvent, DashboardData, DayForecast,
    HostData, StalenessLevel, WeatherData,
)


def generate_dummy_data(tz: tzinfo | None = None, now: datetime | None = None) -> DashboardData:
    """Create realistic dummy data for development/testing.

    *now* overrides the current datetime (useful for dry-run with --date).
    When omitted, ``datetime.now(tz)`` is used.
    """
    if now is None:
        now = datetime.now(tz) if tz is not None else datetime.now()
    today = now.date()

    # Find Monday of this week — matches the week_view rendering which is also Monday-based
    week_start = today - timedelta(days=today.weekday())

    def _at(day_offset: int, hour: int, minute: int = 0) -> datetime:
        return datetime.combine(
            week_start + timedelta(days=day_offset),
            datetime.min.time().replace(hour=hour, minute=minute),
        )

    events = [
        # Monday (col 0) — Normal weekday (2 events, threshold ≤4)
        CalendarEvent(
            summary="Team Standup",
            start=_at(0, 9), end=_at(0, 9, 30),
            location="Zoom",
        ),
        CalendarEvent(
            summary="1:1 with Alex",
            start=_at(0, 14), end=_at(0, 14, 30),
            location="Conference Room B",
        ),
        # Tuesday (col 1) — Compact weekday (6 events, threshold 5–7)
        CalendarEvent(
            summary="Morning Standup",
            start=_at(1, 9), end=_at(1, 9, 15),
        ),
        CalendarEvent(
            summary="Dentist Appointment",
            start=_at(1, 10), end=_at(1, 11),
            location="123 Main St, Suite 4",
        ),
        CalendarEvent(
            summary="Sprint Review",
            start=_at(1, 11), end=_at(1, 12),
        ),
        CalendarEvent(
            summary="Lunch with Team",
            start=_at(1, 12), end=_at(1, 13),
            location="Tartine Manufactory",
        ),
        CalendarEvent(
            summary="Design Sync",
            start=_at(1, 15, 30), end=_at(1, 16),
        ),
        CalendarEvent(
            summary="Code Review",
            start=_at(1, 16, 30), end=_at(1, 17, 30),
        ),
        # Wednesday–Friday: multi-day conference (spanning bar)
        CalendarEvent(
            summary="Tech Conference",
            start=datetime.combine(week_start + timedelta(days=2), datetime.min.time()),
            end=datetime.combine(week_start + timedelta(days=5), datetime.min.time()),
            is_all_day=True,
        ),
        CalendarEvent(
            summary="Yoga",
            start=_at(2, 17, 30), end=_at(2, 18, 30),
            location="Studio 12",
        ),
        # Thursday (col 3) — Dense weekday (8 events, threshold ≥8)
        CalendarEvent(
            summary="Morning Standup",
            start=_at(3, 9), end=_at(3, 9, 15),
        ),
        CalendarEvent(
            summary="Project Planning",
            start=_at(3, 10), end=_at(3, 11, 30),
        ),
        CalendarEvent(
            summary="Architecture Review",
            start=_at(3, 11, 30), end=_at(3, 12, 30),
            location="Conf Room A",
        ),
        CalendarEvent(
            summary="HR Check-in",
            start=_at(3, 13), end=_at(3, 13, 30),
        ),
        CalendarEvent(
            summary="Stakeholder Briefing",
            start=_at(3, 13, 30), end=_at(3, 14, 30),
            location="Board Room",
        ),
        CalendarEvent(
            summary="Coffee with Sam",
            start=_at(3, 15), end=_at(3, 15, 45),
            location="Blue Bottle, Market St",
        ),
        CalendarEvent(
            summary="Bug Triage",
            start=_at(3, 15, 45), end=_at(3, 16, 15),
        ),
        CalendarEvent(
            summary="Sprint Retro",
            start=_at(3, 16, 30), end=_at(3, 17, 30),
        ),
        # Friday (col 4)
        CalendarEvent(
            summary="Demo Day",
            start=_at(4, 14), end=_at(4, 15),
            location="Main Auditorium",
        ),
        # Friday (col 4) — extra events
        CalendarEvent(
            summary="Weekly Wrap-up",
            start=_at(4, 9), end=_at(4, 9, 30),
        ),
        CalendarEvent(
            summary="Lunch & Learn",
            start=_at(4, 12), end=_at(4, 13),
            location="Rooftop Lounge",
        ),
        # Saturday (col 5) — Normal weekend
        CalendarEvent(
            summary="Farmers Market",
            start=_at(5, 9), end=_at(5, 11),
        ),
        CalendarEvent(
            summary="Bike Ride",
            start=_at(5, 12), end=_at(5, 14),
            location="Golden Gate Park",
        ),
        CalendarEvent(
            summary="Dinner Party",
            start=_at(5, 19), end=_at(5, 22),
            location="Chris & Dana's",
        ),
        # Sunday (col 6)
        CalendarEvent(
            summary="Weekend",
            start=datetime.combine(week_start + timedelta(days=6), datetime.min.time()),
            end=datetime.combine(week_start + timedelta(days=7), datetime.min.time()),
            is_all_day=True,
        ),
        CalendarEvent(
            summary="Morning Run",
            start=_at(6, 7, 30), end=_at(6, 8, 15),
            location="Embarcadero",
        ),
        CalendarEvent(
            summary="Brunch",
            start=_at(6, 10), end=_at(6, 12),
            location="The Griddle Cafe",
        ),
    ]

    dummy_tz = tz if tz is not None else timezone.utc
    weather = WeatherData(
        current_temp=42.0,
        current_icon="02d",
        current_description="partly cloudy",
        high=48.0,
        low=35.0,
        humidity=65,
        forecast=[
            DayForecast(
                date=today + timedelta(days=1), high=45.0, low=33.0,
                icon="10d", description="rain", precip_chance=0.80,
            ),
            DayForecast(
                date=today + timedelta(days=2), high=50.0, low=38.0,
                icon="01d", description="clear", precip_chance=0.05,
            ),
            DayForecast(
                date=today + timedelta(days=3), high=47.0, low=36.0,
                icon="04d", description="cloudy", precip_chance=0.30,
            ),
            DayForecast(
                date=today + timedelta(days=4), high=52.0, low=40.0,
                icon="02d", description="partly cloudy",
            ),
            DayForecast(
                date=today + timedelta(days=5), high=55.0, low=42.0,
                icon="09d", description="drizzle", precip_chance=0.60,
            ),
        ],
        alerts=[],
        feels_like=38.0,
        wind_speed=12.0,
        wind_deg=315.0,
        pressure=1013.0,
        uv_index=5.0,
        sunrise=datetime.combine(
            today, datetime.min.time().replace(hour=6, minute=24)
        ).replace(tzinfo=dummy_tz),
        sunset=datetime.combine(
            today, datetime.min.time().replace(hour=19, minute=51)
        ).replace(tzinfo=dummy_tz),
    )

    birthdays = [
        Birthday(name="Mom", date=today + timedelta(days=3)),
        Birthday(name="Jake", date=today + timedelta(days=7), age=30),
        Birthday(name="Alice", date=today + timedelta(days=12), age=25),
        Birthday(name="Bob", date=today + timedelta(days=18)),
    ]

    air_quality = AirQualityData(
        aqi=42,
        category="Good",
        pm25=9.8,
        pm10=14.2,
        sensor_id=99999,
        pm1=6.1,
        temperature=68.4,
        humidity=52.0,
        pressure=1014.3,
    )

    host_data = HostData(
        hostname="raspberrypi",
        uptime_seconds=3 * 86400 + 14 * 3600 + 22 * 60 + 15,  # 3d 14h 22m 15s
        load_1m=0.42,
        load_5m=0.38,
        load_15m=0.31,
        ram_used_mb=892.0,
        ram_total_mb=4096.0,
        disk_used_gb=12.4,
        disk_total_gb=31.3,
        cpu_temp_c=52.1,
        ip_address="192.168.1.105",
    )

    return DashboardData(
        events=events, weather=weather, birthdays=birthdays,
        air_quality=air_quality,
        host_data=host_data,
        fetched_at=now, is_stale=False,
        source_staleness={
            "weather": StalenessLevel.FRESH,
            "events": StalenessLevel.FRESH,
            "air_quality": StalenessLevel.FRESH,
        },
    )
