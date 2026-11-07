"""Fetch JSON from the six Open-Meteo endpoints used by the legacy client."""

import requests

from ._http import get_json


class OpenMeteoClient:
    BASE_URL = "https://api.open-meteo.com/v1"

    def __init__(self, session: requests.Session | None = None):
        self.session = session if session is not None else requests.Session()

    def get_weather_forecast(self, latitude, longitude, **options):
        """Get live weather forecasts. Pass hourly, daily or current variables."""
        return self._get(f"{self.BASE_URL}/forecast", latitude=latitude, longitude=longitude, **options)

    def get_historical_weather(self, latitude, longitude, start_date, end_date, **options):
        """Get reanalysis weather for an inclusive YYYY-MM-DD date range."""
        return self._get(
            "https://archive-api.open-meteo.com/v1/archive",
            latitude=latitude,
            longitude=longitude,
            start_date=start_date,
            end_date=end_date,
            **options,
        )

    def get_air_quality(self, latitude, longitude, **options):
        """Get modeled pollutant or air quality index forecasts."""
        return self._get(
            "https://air-quality-api.open-meteo.com/v1/air-quality",
            latitude=latitude,
            longitude=longitude,
            **options,
        )

    def get_marine_forecast(self, latitude, longitude, **options):
        """Get waves or other marine variables at an offshore location."""
        return self._get(
            "https://marine-api.open-meteo.com/v1/marine",
            latitude=latitude,
            longitude=longitude,
            **options,
        )

    def get_geocoding(self, name: str, **options):
        """Search for places. Read matches from the JSON results list."""
        return self._get("https://geocoding-api.open-meteo.com/v1/search", name=name, **options)

    def get_elevation(self, latitude, longitude):
        """Get elevation in meters for a point or paired coordinate lists."""
        return self._get(f"{self.BASE_URL}/elevation", latitude=latitude, longitude=longitude)

    def _get(self, url: str, **params) -> dict | list:
        # Open-Meteo uses comma-separated values for variables and coordinate lists.
        query = {
            key: ",".join(map(str, value)) if isinstance(value, (list, tuple)) else value
            for key, value in params.items()
        }
        return get_json(self.session, url, query)
