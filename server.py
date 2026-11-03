import errno
import json
import math
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
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


def build_route(stop_ids, accessible_only=False):
    sites = load_records("sites.json")
    sites_by_id = {site["id"]: site for site in sites}
    if not isinstance(stop_ids, list) or not 4 <= len(stop_ids) <= 5:
        raise ValueError("Select 4 or 5 landmarks for your walking route.")
    if any(not isinstance(site_id, str) or site_id not in sites_by_id for site_id in stop_ids):
        raise ValueError("Choose valid landmarks from the current site list.")
    if len(set(stop_ids)) != len(stop_ids):
        raise ValueError("A landmark can only appear once in the route.")

    route_sites = [sites_by_id[site_id] for site_id in stop_ids]
    if any(site["type"] == "submerged" for site in route_sites):
        raise ValueError("Protected submerged archaeology cannot be added as a walking stop.")
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


def get_walkable_route(stop_ids, accessible_only=False):
    build_route(stop_ids, accessible_only)
    sites_by_id = {site["id"]: site for site in load_records("sites.json")}
    route_sites = [sites_by_id[site_id] for site_id in stop_ids]
    payload = {
        "locations": [
            {"lat": site["lat"], "lon": site["lng"], "radius": 100}
            for site in route_sites
        ],
        "costing": "pedestrian",
        "costing_options": {"pedestrian": {"use_ferry": 0}},
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
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        raise RuntimeError(
            f"The pedestrian routing service returned HTTP {error.code}. Please try again."
        ) from error
    except (URLError, TimeoutError) as error:
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
    if not isinstance(legs, list) or len(legs) != len(route_sites) - 1:
        raise RuntimeError(
            "A walkable path could not be found between every selected landmark. "
            "Try a different stop or turn off the step-free filter."
        )
    trip_summary = trip.get("summary", {})
    if isinstance(trip_summary, dict) and trip_summary.get("has_ferry"):
        raise RuntimeError(
            "This route requires a ferry and is not a walking-only route. "
            "Choose stops connected by pedestrian paths."
        )

    route_legs = []
    for index, leg in enumerate(legs):
        if not isinstance(leg, dict):
            raise RuntimeError("The pedestrian router returned an incomplete route.")
        summary = leg.get("summary", {})
        if isinstance(summary, dict) and summary.get("has_ferry"):
            raise RuntimeError(
                "This route requires a ferry and is not a walking-only route. "
                "Choose stops connected by pedestrian paths."
            )
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
        instructions = [
            maneuver["instruction"]
            for maneuver in maneuvers
            if isinstance(maneuver, dict) and isinstance(maneuver.get("instruction"), str)
        ]
        route_legs.append(
            {
                "fromId": route_sites[index]["id"],
                "toId": route_sites[index + 1]["id"],
                "geometry": geometry,
                "distanceKm": distance_km,
                "durationMinutes": math.ceil(duration_seconds / 60),
                "instructions": instructions,
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
        "routingProvider": "OpenStreetMap pedestrian network via Valhalla",
    }


class VeniceRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self.send_json({"status": "ok"})
        if path == "/api/sites":
            return self.send_json(load_records("sites.json"))
        if path == "/api/fountains":
            return self.send_json(load_records("fountains.json"))
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
            if not isinstance(stop_ids, list) or not isinstance(accessible_only, bool):
                return self.send_json({"error": "Invalid route request."}, 400)
            return self.send_json(get_walkable_route(stop_ids, accessible_only))
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
