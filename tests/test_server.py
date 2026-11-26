import csv
import io
import json
import threading
import unittest
from unittest.mock import patch
from urllib.error import URLError
from urllib.request import Request as URLRequest
from urllib.request import urlopen as request_urlopen

from server import (
    VeniceHTTPServer,
    VeniceRequestHandler,
    build_route,
    decode_polyline,
    get_walkable_route,
    load_churches,
    load_confraternities,
    load_doges,
    load_inscriptions,
    load_records,
    load_tassini_heritage,
    load_today_in_venice_history,
    load_venice_history_timeline,
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


def mocked_router_response(has_ferry=False, travel_type="foot", leg_count=3):
    shape = encode_polyline([(45.4352, 12.3352), (45.4353, 12.3353)])
    legs = [
        {
            "shape": shape,
            "summary": {"length": 0.5, "time": 600, "has_ferry": has_ferry},
            "maneuvers": [
                {
                    "instruction": "Continue along the pedestrian path.",
                    "travel_type": travel_type,
                }
            ],
        }
        for _ in range(leg_count)
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

    def test_no_boat_route_rejects_landmarks_on_boat_served_islands(self):
        for site_id in ("giudecca-stucky-mill", "redentore-giudecca", "murano-glass-furnaces"):
            with self.subTest(site_id=site_id), self.assertRaisesRegex(
                ValueError, "requires a boat"
            ):
                build_route([site_id], use_boats=False)

    def test_accessible_route_only_uses_step_free_stops(self):
        route = build_route(
            ["st-marks-basilica", "doges-palace", "ca-rezzonico", "peggy-guggenheim"],
            accessible_only=True,
        )
        sites_by_id = {site["id"]: site for site in load_records("sites.json")}

        self.assertTrue(all(sites_by_id[site_id]["accessibleStepFree"] for site_id in route))

    def test_route_rejects_empty_or_more_than_five_selected_stops(self):
        for selected in (
            [],
            [
                "st-marks-basilica",
                "doges-palace",
                "ca-rezzonico",
                "giudecca-stucky-mill",
                "peggy-guggenheim",
                "rialto-bridge",
            ],
        ):
            with self.subTest(selected=selected), self.assertRaisesRegex(
                ValueError, "between 1 and 5"
            ):
                build_route(selected)

    def test_route_accepts_one_selected_stop(self):
        self.assertEqual(build_route(["st-marks-basilica"]), ["st-marks-basilica"])

    def test_route_accepts_every_stop_count_from_one_through_five(self):
        selected = [
            "st-marks-basilica",
            "doges-palace",
            "ca-rezzonico",
            "giudecca-stucky-mill",
            "peggy-guggenheim",
        ]
        for count in range(1, 6):
            with self.subTest(count=count):
                self.assertEqual(build_route(selected[:count]), selected[:count])

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
        self.assertFalse(result["startedFromCurrentLocation"])
        self.assertEqual(result["distanceKm"], 1.5)
        self.assertEqual(result["durationMinutes"], 30)
        self.assertEqual(result["legs"][0]["instructions"], ["Continue along the pedestrian path."])
        self.assertEqual(result["legs"][0]["geometry"][0], [45.4352, 12.3352])
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(payload["costing"], "pedestrian")
        self.assertEqual(payload["costing_options"]["pedestrian"]["use_ferry"], 1)
        self.assertEqual(
            [(location["lat"], location["lon"]) for location in payload["locations"]],
            [(site["lat"], site["lng"]) for site in load_records("sites.json") if site["id"] in selected],
        )

    def test_routes_from_current_location_to_a_single_selected_stop(self):
        selected = ["st-marks-basilica"]
        start_location = {"lat": 45.4352, "lng": 12.3352}
        mock_urlopen = mock_router_response(mocked_router_response(leg_count=1))
        self.addCleanup(patch.stopall)

        result = get_walkable_route(selected, start_location=start_location)

        self.assertEqual(result["route"], selected)
        self.assertTrue(result["startedFromCurrentLocation"])
        self.assertEqual(len(result["legs"]), 1)
        self.assertEqual(result["legs"][0]["fromId"], "current-location")
        self.assertEqual(result["legs"][0]["fromName"], "Your location")
        self.assertEqual(result["legs"][0]["toId"], selected[0])
        request = mock_urlopen.call_args.args[0]
        payload = json.loads(request.data)
        self.assertEqual(
            (payload["locations"][0]["lat"], payload["locations"][0]["lon"]),
            (start_location["lat"], start_location["lng"]),
        )
        first_site = next(
            site for site in load_records("sites.json") if site["id"] == selected[0]
        )
        self.assertEqual(
            (payload["locations"][1]["lat"], payload["locations"][1]["lon"]),
            (first_site["lat"], first_site["lng"]),
        )

    def test_single_stop_route_requires_a_starting_location(self):
        with self.assertRaisesRegex(ValueError, "needs a starting location"):
            get_walkable_route(["st-marks-basilica"])

    def test_rejects_invalid_current_location_coordinates(self):
        for start_location in (
            {"lat": 91, "lng": 12},
            {"lat": 45, "lng": float("nan")},
            {"lat": 10**10000, "lng": 12},
            {"lat": True, "lng": 12},
            {"lat": 45},
        ):
            with self.subTest(start_location=start_location), self.assertRaisesRegex(
                ValueError, "starting location"
            ):
                get_walkable_route(
                    ["st-marks-basilica"], start_location=start_location
                )

    def test_route_api_accepts_a_current_location_start_for_one_stop(self):
        start_location = {"lat": 45.4352, "lng": 12.3352}
        mock_urlopen = mock_router_response(mocked_router_response(leg_count=1))
        self.addCleanup(patch.stopall)
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        request = URLRequest(
            f"http://127.0.0.1:{server.server_address[1]}/api/routes",
            data=json.dumps(
                {
                    "stopIds": ["st-marks-basilica"],
                    "accessibleOnly": False,
                    "useBoats": False,
                    "startLocation": start_location,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request_urlopen(request) as response:
            result = json.load(response)

        self.assertTrue(result["startedFromCurrentLocation"])
        self.assertEqual(len(result["legs"]), 1)
        self.assertEqual(json.loads(mock_urlopen.call_args.args[0].data)["locations"][0]["lat"], 45.4352)
        self.assertEqual(
            json.loads(mock_urlopen.call_args.args[0].data)["costing_options"]["pedestrian"]["use_ferry"],
            0,
        )

    def test_returns_ferry_legs_with_their_travel_time(self):
        selected = ["st-marks-basilica", "calle-dei-fuseri", "rialto-bridge", "ca-rezzonico"]
        mock_urlopen = mock_router_response(
            mocked_router_response(has_ferry=True, travel_type="ferry")
        )
        self.addCleanup(patch.stopall)

        result = get_walkable_route(selected)

        self.assertTrue(all(leg["hasFerry"] for leg in result["legs"]))
        self.assertTrue(all(leg["durationMinutes"] == 10 for leg in result["legs"]))
        payload = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(payload["costing_options"]["pedestrian"]["use_ferry"], 1)

    def test_no_boat_route_disables_ferries_and_rejects_ferry_legs(self):
        selected = ["st-marks-basilica", "calle-dei-fuseri"]
        mock_urlopen = mock_router_response(
            mocked_router_response(has_ferry=True, travel_type="ferry", leg_count=1)
        )
        self.addCleanup(patch.stopall)

        with self.assertRaisesRegex(RuntimeError, "needs a boat connection"):
            get_walkable_route(selected, use_boats=False)

        payload = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(payload["costing_options"]["pedestrian"]["use_ferry"], 0)

    def test_no_boat_route_can_use_walking_only_connections(self):
        selected = ["st-marks-basilica", "calle-dei-fuseri"]
        mock_urlopen = mock_router_response(
            mocked_router_response(leg_count=1)
        )
        self.addCleanup(patch.stopall)

        result = get_walkable_route(selected, use_boats=False)

        self.assertFalse(any(leg["hasFerry"] for leg in result["legs"]))
        payload = json.loads(mock_urlopen.call_args.args[0].data)
        self.assertEqual(payload["costing_options"]["pedestrian"]["use_ferry"], 0)

    def test_allows_walking_routes_with_a_false_ferry_summary(self):
        selected = ["st-marks-basilica", "calle-dei-fuseri", "rialto-bridge", "ca-rezzonico"]
        mock_router_response(mocked_router_response(has_ferry=True))
        self.addCleanup(patch.stopall)

        result = get_walkable_route(selected)

        self.assertEqual(len(result["legs"]), 3)
        self.assertFalse(any(leg["hasFerry"] for leg in result["legs"]))

    def test_reports_routing_service_connection_errors(self):
        mock_urlopen = patch("server.urlopen", side_effect=URLError("offline"))
        mock_urlopen.start()
        self.addCleanup(mock_urlopen.stop)

        with self.assertRaisesRegex(RuntimeError, "Could not reach the pedestrian routing service"):
            get_walkable_route(["st-marks-basilica", "calle-dei-fuseri", "rialto-bridge", "ca-rezzonico"])

    def test_retries_a_transient_routing_service_connection_error(self):
        selected = ["st-marks-basilica", "calle-dei-fuseri", "rialto-bridge", "ca-rezzonico"]
        mock_urlopen = mock_router_response(mocked_router_response())
        mock_urlopen.side_effect = [URLError("temporary outage"), mock_urlopen.return_value]
        self.addCleanup(patch.stopall)

        result = get_walkable_route(selected)

        self.assertEqual(len(result["legs"]), 3)
        self.assertEqual(mock_urlopen.call_count, 2)


class ServerStartupTests(unittest.TestCase):
    def test_second_server_cannot_reuse_an_active_server_port(self):
        first_server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(first_server.server_close)

        with self.assertRaises(OSError):
            VeniceHTTPServer(first_server.server_address, VeniceRequestHandler)


class ChurchDataTests(unittest.TestCase):
    def test_church_csv_is_normalized_with_valid_coordinates(self):
        churches = load_churches()

        self.assertGreater(len(churches), 0)
        self.assertEqual(churches[0]["name"], "Basilica di San Marco (St. Mark's Basilica)")
        self.assertAlmostEqual(churches[0]["lat"], 45.4345)
        self.assertAlmostEqual(churches[0]["lng"], 12.3397)
        self.assertTrue(all(church["id"] for church in churches))
        self.assertTrue(
            all(
                -90 <= church["lat"] <= 90 and -180 <= church["lng"] <= 180
                for church in churches
            )
        )

    def test_churches_api_returns_csv_records_as_json(self):
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        with request_urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/api/churches"
        ) as response:
            churches = json.load(response)

        self.assertEqual(len(churches), len(load_churches()))
        self.assertEqual(churches[0]["id"], "venetian-church-001")
        self.assertIn("historicalContext", churches[0])


class StaticAssetCacheTests(unittest.TestCase):
    def test_html_and_stylesheet_responses_disable_browser_caching(self):
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        base_url = f"http://127.0.0.1:{server.server_address[1]}"
        for path in ("/", "/styles.css?v=5"):
            with self.subTest(path=path), request_urlopen(f"{base_url}{path}") as response:
                self.assertEqual(response.headers.get("Cache-Control"), "no-store")


class HistoricalLocationDataTests(unittest.TestCase):
    def test_confraternities_csv_is_normalized_with_valid_coordinates(self):
        locations = load_confraternities()

        self.assertEqual(len(locations), 40)
        self.assertEqual(locations[0]["id"], "venetian-confraternity-001")
        self.assertIn("Carità", locations[0]["name"])
        self.assertIn("historicalContext", locations[0])
        self.assertTrue(
            all(
                -90 <= location["lat"] <= 90 and -180 <= location["lng"] <= 180
                for location in locations
            )
        )

    def test_doges_csv_is_normalized_with_valid_coordinates(self):
        locations = load_doges()

        self.assertEqual(len(locations), 64)
        self.assertEqual(locations[0]["id"], "venetian-doge-001")
        self.assertIn("Maggior Consiglio", locations[0]["name"])
        self.assertIn("historicalContext", locations[0])
        self.assertTrue(
            all(
                -90 <= location["lat"] <= 90 and -180 <= location["lng"] <= 180
                for location in locations
            )
        )

    def test_historical_location_apis_return_csv_records_as_json(self):
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        for endpoint, loader, record_id in (
            ("/api/confraternities", load_confraternities, "venetian-confraternity-001"),
            ("/api/doges", load_doges, "venetian-doge-001"),
        ):
            with self.subTest(endpoint=endpoint):
                with request_urlopen(
                    f"http://127.0.0.1:{server.server_address[1]}{endpoint}"
                ) as response:
                    locations = json.load(response)

                self.assertEqual(len(locations), len(loader()))
                self.assertEqual(locations[0]["id"], record_id)
                self.assertIn("description", locations[0])


class InscriptionDataTests(unittest.TestCase):
    def test_inscriptions_csv_preserves_multiline_text_and_metadata(self):
        inscriptions = load_inscriptions()

        self.assertGreater(len(inscriptions), 1000)
        self.assertEqual(inscriptions[0]["id"], "venetian-inscription-0001")
        self.assertEqual(inscriptions[0]["name"], "Lapide - Fermata Chiesa")
        self.assertIn("\n", inscriptions[0]["originalText"])
        self.assertTrue(inscriptions[0]["englishTranslation"])
        self.assertEqual(inscriptions[0]["artifactCategory"], "Inscription / Lapide")
        self.assertEqual(inscriptions[0]["globalId"], "19e8d049-6824-441b-98ac-c6f0d6e5ced0")
        self.assertTrue(
            all(
                -90 <= inscription["lat"] <= 90
                and -180 <= inscription["lng"] <= 180
                for inscription in inscriptions
            )
        )

    def test_inscriptions_api_returns_normalized_csv_records(self):
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        with request_urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/api/inscriptions"
        ) as response:
            inscriptions = json.load(response)

        self.assertEqual(len(inscriptions), len(load_inscriptions()))
        self.assertEqual(inscriptions[0]["id"], "venetian-inscription-0001")
        self.assertEqual(inscriptions[0]["originalText"], load_inscriptions()[0]["originalText"])
        self.assertIn("conditionNotes", inscriptions[0])
        self.assertIn("italianTranslation", inscriptions[0])


class TassiniHeritageDataTests(unittest.TestCase):
    def test_tassini_csv_preserves_citations_and_translation(self):
        locations = load_tassini_heritage()

        with open(
            "data/venetian_tassini_heritage.csv",
            encoding="utf-8-sig",
            newline="",
        ) as data_file:
            self.assertEqual(len(locations), sum(1 for _ in csv.DictReader(data_file)))
        first = locations[0]
        self.assertEqual(first["id"], "tassini-heritage-001")
        self.assertEqual(first["name"], "Ponte dei Baretteri (Sede dell'Accademia dei Granelleschi)")
        self.assertEqual(first["tassiniWorkCited"], "Curiosità Veneziane / Notizie Storiche")
        self.assertIn("Avendo Daniele Farsetti", first["tassiniQuotation"])
        self.assertIn("playful assembly", first["englishToponymicAnalysis"])
        self.assertEqual(first["sourceDocument"], "Encyclopedia_A_Part_01.txt")
        self.assertTrue(all(-90 <= item["lat"] <= 90 and -180 <= item["lng"] <= 180 for item in locations))

    def test_tassini_api_returns_normalized_csv_records(self):
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        with request_urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/api/tassini-heritage"
        ) as response:
            locations = json.load(response)

        self.assertEqual(len(locations), len(load_tassini_heritage()))
        self.assertEqual(locations[0]["tassiniCitation"], "Tassini; Distefano 10")


class TodayInVeniceHistoryTests(unittest.TestCase):
    def test_history_loader_returns_up_to_three_events_for_month_and_day(self):
        events = load_today_in_venice_history(11, 26)

        self.assertEqual(len(events), 3)
        self.assertEqual([event["year"] for event in events], [1095, 1567, 2006])
        self.assertTrue(all(event["text"].startswith("On this day in ") for event in events))
        self.assertTrue(all(event["citation"] and event["sourceDocument"] for event in events))

    def test_history_loader_rejects_invalid_month_and_day(self):
        with self.assertRaisesRegex(ValueError, "valid month and day"):
            load_today_in_venice_history(2, 30)

    def test_history_timeline_loader_returns_all_events_and_calendar_dates(self):
        events = load_venice_history_timeline()

        self.assertEqual(len(events), 1092)
        self.assertEqual((events[0]["month"], events[0]["day"]), (1, 1))
        self.assertEqual((events[-1]["month"], events[-1]["day"]), (12, 31))
        self.assertEqual(len({(event["month"], event["day"]) for event in events}), 366)

    def test_history_api_returns_events_for_requested_calendar_date(self):
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        with request_urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/api/today-in-venice-history?date=11-26"
        ) as response:
            events = json.load(response)

        self.assertEqual(len(events), 3)
        self.assertEqual(events[0]["year"], 1095)
        self.assertIn("citation", events[0])

    def test_history_timeline_api_returns_all_events(self):
        server = VeniceHTTPServer(("127.0.0.1", 0), VeniceRequestHandler)
        self.addCleanup(server.server_close)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        self.addCleanup(server_thread.join)
        self.addCleanup(server.shutdown)

        with request_urlopen(
            f"http://127.0.0.1:{server.server_address[1]}/api/venice-history-timeline"
        ) as response:
            events = json.load(response)

        self.assertEqual(len(events), 1092)
        self.assertEqual((events[-1]["month"], events[-1]["day"]), (12, 31))


if __name__ == "__main__":
    unittest.main()
