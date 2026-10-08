"""Cases cut from tests/test_themes.py when their themes were retired.

Methods of TestRenderDashboardWithThemes and TestThemeRegistration; paste back
into those classes to restore.
"""

    def test_today_theme_hides_week_view(self):
        """The today theme's week_view region should be invisible."""
        t = load_theme("today")
        assert t.layout.week_view.visible is False

    def test_today_theme_shows_today_view(self):
        """The today theme's today_view region should be visible and in draw_order."""
        t = load_theme("today")
        assert t.layout.today_view.visible is True
        assert "today_view" in t.layout.draw_order

    def test_today_theme_with_events_today(self):
        """today theme renders correctly when events fall on today."""
        today = date(2024, 3, 15)
        data = _make_data(today)
        # Add an event on today
        data.events.append(
            CalendarEvent(
                summary="Morning Meeting",
                start=datetime.combine(today, datetime.min.time().replace(hour=9)),
                end=datetime.combine(today, datetime.min.time().replace(hour=10)),
            )
        )
        t = load_theme("today")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)

    def test_today_theme_with_no_events(self):
        """today theme renders correctly with an empty event list."""
        data = _make_data()
        data.events = []
        t = load_theme("today")
        result = render_dashboard(data, self._cfg(), theme=t)
        assert isinstance(result, Image.Image)


    def test_timeline_in_available_themes(self):
        assert "timeline" in AVAILABLE_THEMES


    def test_load_timeline(self):
        theme = load_theme("timeline")
        assert theme.name == "timeline"


    def test_year_pulse_in_available_themes(self):
        assert "year_pulse" in AVAILABLE_THEMES


    def test_load_year_pulse(self):
        theme = load_theme("year_pulse")
        assert theme.name == "year_pulse"

