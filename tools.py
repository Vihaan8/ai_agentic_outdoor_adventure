import time
import requests
from datetime import datetime
from zoneinfo import ZoneInfo
from config import NPS_API_KEY

UA = "TrailAdventurePlanner/1.0 (educational project)"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

WMO_CODES = {
    0: "clear sky",
    1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "rime fog",
    51: "light drizzle", 53: "drizzle", 55: "heavy drizzle",
    56: "light freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain",
    66: "light freezing rain", 67: "freezing rain",
    71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains",
    80: "light showers", 81: "showers", 82: "heavy showers",
    85: "light snow showers", 86: "snow showers",
    95: "thunderstorm", 96: "thunderstorm with hail", 99: "severe thunderstorm",
}


def _fmt_local(iso: str) -> str:
    """Format an Open-Meteo 'YYYY-MM-DDTHH:MM' string as '6:34 AM'."""
    try:
        return datetime.fromisoformat(iso).strftime("%-I:%M %p")
    except ValueError:
        return iso


def geocode(place: str) -> dict:
    """Convert a place name to lat/lon via Nominatim."""
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place, "format": "json", "limit": 1},
        headers={"User-Agent": UA},
        timeout=15,
    )
    hits = r.json()
    if not hits:
        return {"error": f"Could not find location: {place}"}
    h = hits[0]
    return {
        "place": h["display_name"],
        "lat": float(h["lat"]),
        "lon": float(h["lon"]),
    }


def search_trails(location: str, radius_km: float = 15, limit: int = 15) -> dict:
    """Hit the Overpass API for hiking trails within radius_km of a place."""
    geo = geocode(location)
    if "error" in geo:
        return geo

    lat, lon = geo["lat"], geo["lon"]
    radius_m = int(radius_km * 1000)
    query = f"""
    [out:json][timeout:25];
    (
      relation["route"="hiking"]["name"](around:{radius_m},{lat},{lon});
      way["highway"="path"]["name"]["sac_scale"](around:{radius_m},{lat},{lon});
      way["highway"="footway"]["name"]["sac_scale"](around:{radius_m},{lat},{lon});
      way["highway"="path"]["name"]["foot"="designated"](around:{radius_m},{lat},{lon});
    );
    out tags center {limit * 3};
    """

    elements = None
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            r = requests.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": UA},
                timeout=20,
            )
            if r.status_code == 200 and r.text.lstrip().startswith("{"):
                elements = r.json().get("elements", [])
                break
            last_err = f"{endpoint} → {r.status_code}"
        except Exception as e:
            last_err = f"{endpoint} → {type(e).__name__}"
        time.sleep(0.5)

    if elements is None:
        return {"error": f"Overpass API unavailable: {last_err}", "location": geo["place"]}

    trails = []
    seen = set()
    for el in elements:
        tags = el.get("tags", {})
        name = tags.get("name")
        if not name or name in seen:
            continue
        seen.add(name)
        trails.append({
            "name": name,
            "type": tags.get("route", tags.get("highway", "trail")),
            "difficulty": tags.get("sac_scale") or tags.get("trail_visibility") or "unknown",
            "distance_km": tags.get("distance"),
            "surface": tags.get("surface", "unknown"),
            "ref": tags.get("ref"),
        })
        if len(trails) >= limit:
            break

    return {
        "location": geo["place"],
        "lat": lat,
        "lon": lon,
        "radius_km": radius_km,
        "count": len(trails),
        "trails": trails,
    }


def get_weather(location: str, days: int = 3) -> dict:
    """Get a daily forecast from Open-Meteo (free, no API key) in the location's local time."""
    geo = geocode(location)
    if "error" in geo:
        return geo

    days = max(1, min(days, 7))
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": geo["lat"],
            "longitude": geo["lon"],
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weathercode,windspeed_10m_max",
            "timezone": "auto",
            "temperature_unit": "fahrenheit",
            "windspeed_unit": "mph",
            "forecast_days": days,
        },
        timeout=15,
    )
    if r.status_code != 200:
        return {"error": f"Open-Meteo error {r.status_code}: {r.text[:200]}"}

    data = r.json()
    daily = data.get("daily", {})
    dates = daily.get("time", [])

    forecast = []
    for i, date in enumerate(dates):
        code = daily["weathercode"][i]
        forecast.append({
            "date": date,
            "high_f": round(daily["temperature_2m_max"][i]),
            "low_f": round(daily["temperature_2m_min"][i]),
            "rain_probability": daily["precipitation_probability_max"][i] or 0,
            "conditions": WMO_CODES.get(code, f"code {code}"),
            "wind_mph": round(daily["windspeed_10m_max"][i]),
        })

    return {
        "location": geo["place"],
        "timezone": data.get("timezone"),
        "forecast": forecast,
    }


def get_daylight(location: str, date: str = None) -> dict:
    """Get sunrise, sunset, and day length in the location's local time via Open-Meteo."""
    geo = geocode(location)
    if "error" in geo:
        return geo

    params = {
        "latitude": geo["lat"],
        "longitude": geo["lon"],
        "daily": "sunrise,sunset,daylight_duration",
        "timezone": "auto",
    }
    if date:
        params["start_date"] = date
        params["end_date"] = date
    else:
        params["forecast_days"] = 1

    r = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=15)
    if r.status_code != 200:
        return {"error": f"Open-Meteo error {r.status_code}: {r.text[:200]}"}

    data = r.json()
    daily = data.get("daily", {})
    if not daily.get("time"):
        return {"error": "No daylight data returned"}

    sunrise_iso = daily["sunrise"][0]
    sunset_iso = daily["sunset"][0]
    day_sec = int(daily["daylight_duration"][0])
    hours = day_sec // 3600
    minutes = (day_sec % 3600) // 60

    tz_name = data.get("timezone")
    try:
        tz_abbr = datetime.fromisoformat(sunrise_iso).replace(
            tzinfo=ZoneInfo(tz_name)
        ).strftime("%Z")
    except Exception:
        tz_abbr = data.get("timezone_abbreviation", "")

    return {
        "location": geo["place"],
        "timezone": tz_name,
        "date": daily["time"][0],
        "sunrise": f"{_fmt_local(sunrise_iso)} {tz_abbr}".strip(),
        "sunset": f"{_fmt_local(sunset_iso)} {tz_abbr}".strip(),
        "day_length": f"{hours}h {minutes}m",
    }


def get_park_info(park_query: str) -> dict:
    """Get NPS park details, alerts, and campgrounds for a search query."""
    if not NPS_API_KEY:
        return {"error": "NPS_API_KEY not set"}

    r = requests.get(
        "https://developer.nps.gov/api/v1/parks",
        params={"q": park_query, "limit": 3, "api_key": NPS_API_KEY},
        timeout=15,
    )
    if r.status_code != 200:
        return {"error": f"NPS error {r.status_code}: {r.text[:200]}"}

    parks = r.json().get("data", [])
    if not parks:
        return {"error": f"No parks found for: {park_query}"}

    results = []
    for p in parks:
        code = p["parkCode"]
        alerts_r = requests.get(
            "https://developer.nps.gov/api/v1/alerts",
            params={"parkCode": code, "api_key": NPS_API_KEY},
            timeout=15,
        )
        alerts = [
            {"title": a["title"], "category": a.get("category", ""), "description": a["description"][:300]}
            for a in alerts_r.json().get("data", [])[:5]
        ]

        camp_r = requests.get(
            "https://developer.nps.gov/api/v1/campgrounds",
            params={"parkCode": code, "limit": 5, "api_key": NPS_API_KEY},
            timeout=15,
        )
        campgrounds = [
            {
                "name": c["name"],
                "description": c["description"][:200],
                "reservation_url": c.get("reservationUrl", ""),
            }
            for c in camp_r.json().get("data", [])
        ]

        results.append({
            "name": p["fullName"],
            "code": code,
            "states": p.get("states", ""),
            "description": p["description"][:400],
            "designation": p.get("designation", ""),
            "url": p.get("url", ""),
            "alerts": alerts,
            "campgrounds": campgrounds,
        })

    return {"query": park_query, "parks": results}


TOOL_FUNCTIONS = {
    "search_trails": search_trails,
    "get_weather": get_weather,
    "get_daylight": get_daylight,
    "get_park_info": get_park_info,
}
