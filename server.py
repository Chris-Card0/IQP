import csv
import errno
import json
import math
import os
import time
from datetime import date
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
ROUTING_URL = os.environ.get(
    "VENICE_ROUTING_URL",
    "https://valhalla1.openstreetmap.de/route",
)


class VeniceHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = False


def load_records(filename):
    with (DATA_DIR / filename).open(encoding="utf-8") as data_file:
        return json.load(data_file)


def load_historical_locations(filename, dataset_name, id_prefix, additional_fields=None):
    required_fields = (
        "Location Name",
        "Island",
        "Sestiere / District",
        "Specific Location / Address",
        "Latitude",
        "Longitude",
        "Year Built / Founded",
        "Description & Significance",
        "Key Historical Context",
    ) + tuple((additional_fields or {}).values())
    locations = []
    with (DATA_DIR / filename).open(encoding="utf-8-sig", newline="") as data_file:
        reader = csv.DictReader(data_file)
        if reader.fieldnames is None or any(
            field not in reader.fieldnames for field in required_fields
        ):
            raise ValueError(
                f"The Venetian {dataset_name} dataset is missing required columns."
            )
        for index, row in enumerate(reader, start=1):
            try:
                latitude = float(row["Latitude"])
                longitude = float(row["Longitude"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"The Venetian {dataset_name} dataset has invalid coordinates on row {index}."
                ) from error
            if (
                not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise ValueError(
                    f"The Venetian {dataset_name} dataset has invalid coordinates on row {index}."
                )
            location = {
                "id": f"{id_prefix}-{index:03}",
                "name": row["Location Name"].strip(),
                "island": row["Island"].strip(),
                "district": row["Sestiere / District"].strip(),
                "address": row["Specific Location / Address"].strip(),
                "lat": latitude,
                "lng": longitude,
                "yearFounded": row["Year Built / Founded"].strip(),
                "description": row["Description & Significance"].strip(),
                "historicalContext": row["Key Historical Context"].strip(),
            }
            if additional_fields:
                location.update(
                    {
                        key: (row.get(column) or "").strip()
                        for key, column in additional_fields.items()
                    }
                )
            locations.append(location)
    return locations


def load_churches():
    return load_historical_locations(
        "venetian_churches.csv", "churches", "venetian-church"
    )


def load_confraternities():
    return load_historical_locations(
        "venetian_confraternities_guilds.csv",
        "confraternities and guilds",
        "venetian-confraternity",
    )


def load_doges():
    return load_historical_locations(
        "venetian_doges_dynasties.csv", "doges and dynasties", "venetian-doge"
    )


def load_inscriptions():
    required_fields = (
        "Location Name",
        "Island",
        "Sestiere / District",
        "Specific Location / Address",
        "Latitude",
        "Longitude",
        "Year Built / Founded",
        "Description & Significance",
        "Key Historical Context",
        "Artifact Category",
        "Type of Inscription",
        "Scale of Damage (1-5)",
        "Condition Notes",
        "Original Inscription Text",
        "English Translation",
        "Italian Translation",
        "Thematic Classification",
        "Survey ObjectID",
        "GlobalID",
        "Lapidi ID",
    )
    inscriptions = []
    with (DATA_DIR / "venetian_inscriptions.csv").open(
        encoding="utf-8-sig", newline=""
    ) as data_file:
        reader = csv.DictReader(data_file)
        if reader.fieldnames is None or any(
            field not in reader.fieldnames for field in required_fields
        ):
            raise ValueError(
                "The Venetian inscriptions dataset is missing required columns."
            )
        for index, row in enumerate(reader, start=1):
            try:
                latitude = float(row["Latitude"])
                longitude = float(row["Longitude"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"The Venetian inscriptions dataset has invalid coordinates on row {index}."
                ) from error
            if (
                not math.isfinite(latitude)
                or not math.isfinite(longitude)
                or not -90 <= latitude <= 90
                or not -180 <= longitude <= 180
            ):
                raise ValueError(
                    f"The Venetian inscriptions dataset has invalid coordinates on row {index}."
                )
            inscriptions.append(
                {
                    "id": f"venetian-inscription-{index:04}",
                    "name": row["Location Name"].strip(),
                    "island": row["Island"].strip(),
                    "district": row["Sestiere / District"].strip(),
                    "address": row["Specific Location / Address"].strip(),
                    "lat": latitude,
                    "lng": longitude,
                    "yearFounded": row["Year Built / Founded"].strip(),
                    "description": row["Description & Significance"].strip(),
                    "historicalContext": row["Key Historical Context"].strip(),
                    "artifactCategory": row["Artifact Category"].strip(),
                    "inscriptionType": row["Type of Inscription"].strip(),
                    "damageScale": row["Scale of Damage (1-5)"].strip(),
                    "conditionNotes": row["Condition Notes"].strip(),
                    "originalText": row["Original Inscription Text"].strip(),
                    "englishTranslation": row["English Translation"].strip(),
                    "italianTranslation": row["Italian Translation"].strip(),
                    "thematicClassification": row["Thematic Classification"].strip(),
                    "surveyObjectId": row["Survey ObjectID"].strip(),
                    "globalId": row["GlobalID"].strip(),
                    "lapidiId": row["Lapidi ID"].strip(),
                }
            )
    return inscriptions


def load_tassini_heritage():
    return load_historical_locations(
        "venetian_tassini_heritage.csv",
        "Tassini heritage",
        "tassini-heritage",
        {
            "tassiniWorkCited": "Tassini Work Cited",
            "tassiniCitation": "Tassini Page / Citation",
            "tassiniQuotation": "Exact Quotation from Tassini",
            "englishToponymicAnalysis": "English Translation & Toponymic Analysis",
            "sourceDocument": "Source Document",
        },
    )


def load_venice_history(month=None, day=None):
    if (month is None) != (day is None):
        raise ValueError("Provide both a month and day, or neither.")
    target_date = None
    if month is not None:
        try:
            target_date = date(2000, month, day)
        except (TypeError, ValueError) as error:
            raise ValueError("The history date must be a valid month and day.") from error

    required_fields = (
        "Month",
        "Day",
        "Date Display",
        "Year",
        "Event Headline",
        "Pop-Up Historical Text",
        "Category",
        "Historical Location",
        "Source Citation",
        "Source Document",
    )
    events = []
    with (DATA_DIR / "today_in_venice_history.csv").open(
        encoding="utf-8-sig", newline=""
    ) as data_file:
        reader = csv.DictReader(data_file)
        if reader.fieldnames is None or any(
            field not in reader.fieldnames for field in required_fields
        ):
            raise ValueError(
                "The today in Venice history dataset is missing required columns."
            )
        for index, row in enumerate(reader, start=1):
            try:
                row_month = int(row["Month"])
                row_day = int(row["Day"])
                year = int(row["Year"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"The today in Venice history dataset has an invalid date on row {index}."
                ) from error
            try:
                row_date = date(2000, row_month, row_day)
            except ValueError as error:
                raise ValueError(
                    f"The today in Venice history dataset has an invalid date on row {index}."
                ) from error
            if target_date and (
                row_date.month != target_date.month or row_date.day != target_date.day
            ):
                continue
            events.append(
                {
                    "id": f"venice-history-{index:04}",
                    "month": row_date.month,
                    "day": row_date.day,
                    "dateDisplay": row["Date Display"].strip(),
                    "year": year,
                    "headline": row["Event Headline"].strip(),
                    "text": row["Pop-Up Historical Text"].strip(),
                    "category": row["Category"].strip(),
                    "location": row["Historical Location"].strip(),
                    "citation": row["Source Citation"].strip(),
                    "sourceDocument": row["Source Document"].strip(),
                }
            )
    return events


def load_today_in_venice_history(month, day):
    return load_venice_history(month, day)[:3]


def load_venice_history_timeline():
    return load_venice_history()


def build_route(stop_ids, accessible_only=False, use_boats=True):
    sites = load_records("sites.json")
    sites_by_id = {site["id"]: site for site in sites}
    if not isinstance(use_boats, bool):
        raise ValueError("The boat preference must be true or false.")
    if not isinstance(stop_ids, list) or not 1 <= len(stop_ids) <= 5:
        raise ValueError("Select between 1 and 5 landmarks for your walking route.")
    if any(not isinstance(site_id, str) or site_id not in sites_by_id for site_id in stop_ids):
        raise ValueError("Choose valid landmarks from the current site list.")
    if len(set(stop_ids)) != len(stop_ids):
        raise ValueError("A landmark can only appear once in the route.")

    route_sites = [sites_by_id[site_id] for site_id in stop_ids]
    if any(site["type"] == "submerged" for site in route_sites):
        raise ValueError("Protected submerged archaeology cannot be added as a walking stop.")
    if not use_boats and any(site.get("requiresBoat", False) for site in route_sites):
        raise ValueError("This route includes a landmark that requires a boat. Turn on boat connections or choose another landmark.")
    if accessible_only and any(not site["accessibleStepFree"] for site in route_sites):
        raise ValueError("Every selected landmark must be marked step-free.")

    return stop_ids


def decode_polyline(encoded, precision=6):
    coordinates = []
    latitude = longitude = index = 0
    factor = 10**precision
    while index < len(encoded):
        deltas = []
        for _ in range(2):
            result = shift = 0
            while True:
                if index >= len(encoded):
                    raise ValueError("The pedestrian router returned invalid path geometry.")
                byte = ord(encoded[index]) - 63
                index += 1
                result |= (byte & 0x1F) << shift
                shift += 5
                if byte < 0x20:
                    break
            deltas.append(~(result >> 1) if result & 1 else result >> 1)
        latitude += deltas[0]
        longitude += deltas[1]
        coordinates.append([latitude / factor, longitude / factor])
    if len(coordinates) < 2:
        raise ValueError("The pedestrian router returned an incomplete path.")
    return coordinates


def get_walkable_route(stop_ids, accessible_only=False, start_location=None, use_boats=True):
    build_route(stop_ids, accessible_only, use_boats)
    if start_location is not None:
        if not isinstance(start_location, dict):
            raise ValueError("The route starting location is invalid.")
        try:
            latitude = float(start_location.get("lat"))
            longitude = float(start_location.get("lng"))
        except (OverflowError, TypeError, ValueError) as error:
            raise ValueError(
                "The route starting location has invalid coordinates."
            ) from error
        if (
            isinstance(start_location.get("lat"), bool)
            or isinstance(start_location.get("lng"), bool)
            or not math.isfinite(latitude)
            or not math.isfinite(longitude)
            or not -90 <= latitude <= 90
            or not -180 <= longitude <= 180
        ):
            raise ValueError("The route starting location has invalid coordinates.")
        start_location = {"lat": latitude, "lng": longitude}
    elif len(stop_ids) == 1:
        raise ValueError(
            "A single-stop route needs a starting location. Enable “Start from my current location”."
        )

    sites_by_id = {site["id"]: site for site in load_records("sites.json")}
    route_sites = [sites_by_id[site_id] for site_id in stop_ids]
    route_points = (
        [{"lat": start_location["lat"], "lng": start_location["lng"]}]
        if start_location is not None
        else []
    ) + route_sites
    payload = {
        "locations": [
            {"lat": point["lat"], "lon": point["lng"], "radius": 100}
            for point in route_points
        ],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"use_ferry": 1 if use_boats else 0}},
        "units": "kilometers",
        "shape_format": "polyline6",
        "directions_options": {"units": "kilometers"},
    }
    request = Request(
        ROUTING_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "User-Agent": "AncientVeniceWPI/1.0",
        },
        method="POST",
    )
    for attempt in range(2):
        try:
            with urlopen(request, timeout=20) as response:
                result = json.load(response)
            break
        except HTTPError as error:
            if attempt == 0 and (error.code == 429 or 500 <= error.code < 600):
                time.sleep(0.35)
                continue
            raise RuntimeError(
                f"The pedestrian routing service returned HTTP {error.code}. Please try again."
            ) from error
        except (URLError, TimeoutError) as error:
            if attempt == 0:
                time.sleep(0.35)
                continue
            raise RuntimeError(
                "Could not reach the pedestrian routing service. Check your internet connection and try again."
            ) from error
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise RuntimeError("The pedestrian routing service returned an invalid response.") from error

    if not isinstance(result, dict):
        raise RuntimeError("The pedestrian routing service returned an invalid response.")
    trip = result.get("trip", {})
    if not isinstance(trip, dict):
        raise RuntimeError("The pedestrian routing service returned an invalid response.")
    legs = trip.get("legs", [])
    if not isinstance(legs, list) or len(legs) != len(route_points) - 1:
        raise RuntimeError(
            "A walkable path could not be found from the starting location through every selected landmark. "
            "Try a different stop or turn off the step-free filter."
        )
    trip_summary = trip.get("summary", {})
    route_legs = []
    for index, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise RuntimeError("The pedestrian router returned an incomplete route.")
        summary = leg.get("summary", {})
        try:
            geometry = decode_polyline(leg["shape"])
            distance_km = float(summary["length"])
            duration_seconds = float(summary["time"])
        except (KeyError, TypeError, ValueError) as error:
            raise RuntimeError("The pedestrian router returned an incomplete route.") from error
        if not math.isfinite(distance_km) or distance_km < 0 or not math.isfinite(duration_seconds) or duration_seconds < 0:
            raise RuntimeError("The pedestrian router returned invalid route details.")
        maneuvers = leg.get("maneuvers", [])
        if not isinstance(maneuvers, list):
            raise RuntimeError("The pedestrian router returned invalid walking directions.")
        summary_has_ferry = isinstance(summary, dict) and summary.get("has_ferry")
        travel_types = [
            maneuver.get("travel_type")
            for maneuver in maneuvers
            if isinstance(maneuver, dict)
        ]
        has_only_foot_travel_types = bool(maneuvers) and len(travel_types) == len(maneuvers) and all(
            isinstance(travel_type, str) and travel_type.casefold() == "foot"
            for travel_type in travel_types
        )
        has_ferry_maneuver = any(
            isinstance(travel_type, str) and travel_type.casefold() == "ferry"
            for travel_type in travel_types
        )
        has_ferry = has_ferry_maneuver or (
            summary_has_ferry and not has_only_foot_travel_types
        )
        if has_ferry and not use_boats:
            raise RuntimeError("The selected route needs a boat connection. Turn on boat connections or choose another route.")
        instructions = [
            maneuver["instruction"]
            for maneuver in maneuvers
            if isinstance(maneuver, dict) and isinstance(maneuver.get("instruction"), str)
        ]
        from_site = route_points[index]
        to_site = route_points[index + 1]
        route_legs.append(
            {
                "fromId": from_site.get("id", "current-location"),
                "fromName": from_site.get("name", "Your location"),
                "toId": to_site["id"],
                "geometry": geometry,
                "distanceKm": distance_km,
                "durationMinutes": math.ceil(duration_seconds / 60),
                "instructions": instructions,
                "hasFerry": has_ferry,
            }
        )

    summary = trip_summary
    try:
        distance_km = float(summary["length"])
        duration_seconds = float(summary["time"])
    except (KeyError, TypeError, ValueError) as error:
        raise RuntimeError("The pedestrian router returned an incomplete route summary.") from error
    if not math.isfinite(distance_km) or distance_km < 0 or not math.isfinite(duration_seconds) or duration_seconds < 0:
        raise RuntimeError("The pedestrian router returned invalid route summary details.")
    return {
        "route": stop_ids,
        "legs": route_legs,
        "distanceKm": distance_km,
        "durationMinutes": math.ceil(duration_seconds / 60),
        "startedFromCurrentLocation": start_location is not None,
        "routingProvider": "OpenStreetMap pedestrian network via Valhalla",
    }


class VeniceRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed_url = urlparse(self.path)
        path = parsed_url.path
        if path == "/api/health":
            return self.send_json({"status": "ok"})
        if path == "/api/venice-history-timeline":
            return self.send_json(load_venice_history_timeline())
        if path == "/api/today-in-venice-history":
            dates = parse_qs(parsed_url.query).get("date", [])
            try:
                if len(dates) != 1:
                    raise ValueError
                month_text, day_text = dates[0].split("-", 1)
                target_date = date(2000, int(month_text), int(day_text))
            except (TypeError, ValueError):
                return self.send_json(
                    {"error": "Provide a valid date in MM-DD format."}, 400
                )
            return self.send_json(
                load_today_in_venice_history(target_date.month, target_date.day)
            )
        if path == "/api/sites":
            return self.send_json(load_records("sites.json"))
        if path == "/api/fountains":
            return self.send_json(load_records("fountains.json"))
        if path == "/api/churches":
            return self.send_json(load_churches())
        if path == "/api/confraternities":
            return self.send_json(load_confraternities())
        if path == "/api/doges":
            return self.send_json(load_doges())
        if path == "/api/inscriptions":
            return self.send_json(load_inscriptions())
        if path == "/api/tassini-heritage":
            return self.send_json(load_tassini_heritage())
        if path == "/api/geojson":
            sites = load_records("sites.json")
            return self.send_json(
                {
                    "type": "FeatureCollection",
                    "name": "WPI_Ancient_Venice",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {
                                key: site[key]
                                for key in (
                                    "id",
                                    "name",
                                    "sestiere",
                                    "category",
                                    "era",
                                    "dateConstructed",
                                )
                            },
                            "geometry": {
                                "type": "Point",
                                "coordinates": [site["lng"], site["lat"]],
                            },
                        }
                        for site in sites
                    ],
                }
            )
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path != "/api/routes":
            return self.send_json({"error": "Not found."}, 404)
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 16_384:
                return self.send_json({"error": "Request body must be under 16 KB."}, 400)
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                return self.send_json({"error": "Route request must be a JSON object."}, 400)
            stop_ids = request.get("stopIds")
            accessible_only = request.get("accessibleOnly", False)
            start_location = request.get("startLocation")
            use_boats = request.get("useBoats", True)
            if (
                not isinstance(stop_ids, list)
                or not isinstance(accessible_only, bool)
                or not isinstance(use_boats, bool)
                or ("startLocation" in request and not isinstance(start_location, dict))
            ):
                return self.send_json({"error": "Invalid route request."}, 400)
            return self.send_json(
                get_walkable_route(stop_ids, accessible_only, start_location, use_boats)
            )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json({"error": "Request body must contain valid JSON."}, 400)
        except ValueError as error:
            return self.send_json({"error": str(error)}, 400)
        except RuntimeError as error:
            return self.send_json({"error": str(error)}, 502)


if __name__ == "__main__":
    address = ("127.0.0.1", 8000)
    try:
        server = VeniceHTTPServer(address, VeniceRequestHandler)
    except OSError as error:
        if error.errno == errno.EADDRINUSE or getattr(error, "winerror", None) == 10048:
            raise SystemExit(
                f"Port {address[1]} is already in use. Stop the other Ancient Venice server "
                "with Ctrl+C, or use its existing browser tab."
            ) from error
        raise
    print(f"Ancient Venice is running at http://{address[0]}:{address[1]}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Ancient Venice.")
    finally:
        server.server_close()
