import io
import json
import unittest
from unittest.mock import patch
from urllib.error import URLError

from server import (
    VeniceHTTPServer,
    VeniceRequestHandler,
    build_route,
    decode_polyline,
    get_walkable_route,
    load_records,
)


def encode_polyline(points, precision=6):
    encoded = []
    previous_latitude = previous_longitude = 0
    factor = 10**precision
    for latitude, longitude in points:
        latitude = round(latitude * factor)
        longitude = round(longitude * factor)
        for delta in (latitude - previous_latitude, longitude - previous_longitude):
            value = ~(delta << 1) if delta < 0 else delta << 1
            while value >= 0x20:
                encoded.append(chr((0x20 | (value & 0x1F)) + 63))
                value >>= 5
            encoded.append(chr(value + 63))
        previous_latitude = latitude
        previous_longitude = longitude
    return "".join(encoded)


def mocked_router_response(has_ferry=False):
    shape = encode_polyline([(45.4352, 12.3352), (45.4353, 12.3353)])
    legs = [
        {
            "shape": shape,
            "summary": {"length": 0.5, "time": 600, "has_ferry": has_ferry},
            "maneuvers": [{"instruction": "Continue along the pedestrian path."}],
        }
        for _ in range(3)
    ]
    return {
        "trip": {
            "legs": legs,
            "summary": {"length": 1.5, "time": 1800, "has_ferry": has_ferry},
        }
    }


def mock_router_response(response):
    mock_urlopen = patch("server.urlopen").start()
    mock_urlopen.return_value.__enter__.return_value = io.BytesIO(
        json.dumps(response).encode("utf-8")
    )
    return mock_urlopen


class RouteTests(unittest.TestCase):
    def test_route_contains_only_the_selected_stops_in_selection_order(self):
        selected = [
            "st-marks-basilica",
            "rialto-bridge",
            "ca-rezzonico",
            "peggy-guggenheim",
        ]
        route = build_route(selected)
        sites_by_id = {site["id"]: site for site in load_records("sites.json")}

        self.assertEqual(route, selected)
        self.assertEqual(len(route), 4)
        self.assertTrue(all(sites_by_id[site_id]["type"] != "submerged" for site_id in route))

    def test_accessible_route_only_uses_step_free_stops(self):
        route = build_route(
            ["st-marks-basilica", "doges-palace", "ca-rezzonico", "peggy-guggenheim"],
            accessible_only=True,
        )
        sites_by_id = {site["id"]: site for site in load_records("sites.json")}

        self.assertTrue(all(sites_by_id[site_id]["accessibleStepFree"] for site_id in route))

    def test_route_requires_four_or_five_selected_stops(self):
        with self.assertRaisesRegex(ValueError, "Select 4 or 5"):
            build_route(["st-marks-basilica", "doges-palace", "ca-rezzonico"])

    def test_route_accepts_five_selected_stops(self):
        selected = [
            "st-marks-basilica",
            "doges-palace",
            "ca-rezzonico",
            "giudecca-stucky-mill",
            "peggy-guggenheim",
        ]
        self.assertEqual(build_route(selected), selected)

    def test_route_rejects_an_unknown_stop(self):
        with self.assertRaisesRegex(ValueError, "valid landmarks"):
            build_route(
                ["st-marks-basilica", "doges-palace", "ca-rezzonico", "not-a-landmark"]
            )

    def test_route_rejects_duplicate_stops(self):
        with self.assertRaisesRegex(ValueError, "only appear once"):
            build_route(
                ["st-marks-basilica", "doges-palace", "ca-rezzonico", "st-marks-basilica"]
            )

    def test_route_rejects_a_non_step_free_stop(self):
        with self.assertRaisesRegex(ValueError, "marked step-free"):
            build_route(
                ["st-marks-basilica", "doges-palace", "rialto-bridge", "peggy-guggenheim"],
                accessible_only=True,
            )

    def test_route_rejects_submerged_archaeology(self):
        with self.assertRaisesRegex(ValueError, "Protected submerged archaeology"):
            build_route(
                [
                    "st-marks-basilica",
                    "doges-palace",
                    "peggy-guggenheim",
                    "submerged-roman-road",
                ]
            )

    def test_decodes_polyline6_to_latitude_longitude_pairs(self):
        points = [(45.4352, 12.3352), (45.4353, 12.3353), (45.4354, 12.3355)]
        encoded = encode_polyline(points)

        decoded = decode_polyline(encoded)

        for actual, expected in zip(decoded, points):
            self.assertAlmostEqual(actual[0], expected[0], places=6)
            self.assertAlmostEqual(actual[1], expected[1], places=6)

    def test_decodes_known_polyline5_example(self):
        decoded = decode_polyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@", precision=5)

        self.assertEqual(decoded, [[38.5, -120.2], [40.7, -120.95], [43.252, -126.453]])

    def test_returns_routed_path_geometry_and_provider_totals(self):
        selected = ["st-marks-basilica", "calle-dei-fuseri", "rialto-bridge", "ca-rezzonico"]
        mock_urlopen = mock_router_response(mocked_router_response())
        self.addCleanup(patch.stopall)

        result = get_walkable_route(selected)

        self.assertEqual(result["route"], selected)
        self.assertEqual(len(result["legs"]), 3)
        self.assertEqual(result["distanceKm"], 1.5)
        self.assertEqual(result["durationMinutes"], 30)
        self.assertEqual(result["legs"][0]["instructions"], ["Continue along the pedestrian path."])
        self.assertEqual(result["legs"][0]["geometry"][0], [45.4352, 12.3352])
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["costing"], "pedestrian")
        self.assertEqual(payload["costing_options"]["pedestrian"]["use_ferry"], 0)
        self.assertEqual(
            [(location["lat"], location["lon"]) for location in payload["locations"]],
            [(site["lat"], site["lng"]) for site in load_records("sites.json") if site["id"] in selected],
        )

    def test_rejects_routes_that_require_ferries(self):
        selected = ["st-marks-basilica", "calle-dei-fuseri", "rialto-bridge", "ca-rezzonico"]
        mock_router_response(mocked_router_response(has_ferry=True))
        self.addCleanup(patch.stopall)

        with self.assertRaisesRegex(RuntimeError, "requires a ferry"):
            get_walkable_route(selected)

    def test_reports_routing_service_connection_errors(self):
        mock_urlopen = patch("server.urlopen", side_effect=URLError("offline"))
        mock_urlopen.start()
        self.addCleanup(mock_urlopen.stop)

        with self.assertRaisesRegex(RuntimeError, "Could not reach the pedestrian routing service"):
            get_walkable_route(["st-marks-basilica", "calle-dei-fuseri", "rialto-bridge", "ca-rezzonico"])


class ServerStartupTests(unittest.TestCase):
    def test_second_server_cannot_reuse_an_active_server_port(self):
        first_server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(first_server.server_close)

        with self.assertRaises(OSError):
            VeniceHTTPServer(first_server.server_address, VeniceRequestHandler)


if __name__ == "__main__":
    unittest.main()
