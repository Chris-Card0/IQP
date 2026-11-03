# Ancient Venice Interactive Tour

Interactive historical and archaeological guide for the WPI Venice Project Center. Choose 4–5 landmarks for a walking route, select artifact interests for nearby discoveries, browse research records, and export the site dataset as GeoJSON.

## Run locally

Requires Python 3.9 or newer; there are no Python packages to install.

1. Open a terminal in this folder.
2. Run `python server.py` (on Windows, `py server.py` also works).
3. Visit `http://127.0.0.1:8000`.

If the server reports that port 8000 is already in use, stop the other server with **Ctrl+C** in its terminal or use the browser tab that is already open.

FIX THIS A LOW LOWK just put in our proposal should thing be private?

The Python server provides landmark and fountain data, finds pedestrian routes between selected stops, and serves GeoJSON downloads. Walking paths follow the OpenStreetMap pedestrian network through Valhalla; the app draws the returned path geometry and displays the route distance, estimated walking time, and turn instructions. Ferry-required routes are rejected rather than shown as walking-only. This is network routing, not machine learning: mapped pedestrian paths are a better fit for dependable directions than generated routes.

The default router is a public Valhalla demonstration service. It requires an internet connection and may be rate-limited or temporarily unavailable. For a different Valhalla instance, set `VENICE_ROUTING_URL` to its `/route` endpoint before starting the server. Routing errors are shown in the app rather than replaced with straight-line segments. Step-free landmark selection checks the project’s landmark accessibility data; it does not guarantee every section of the pedestrian network is wheelchair-accessible.

Artifact preferences only filter nearby walking discoveries; they never add stops to the route. The page, CSS, and research data live in separate files. The map and UI libraries load from public CDNs, so an internet connection is required.

On the **Near Me** tab, choose **Start live location** and allow the browser permission to update preferred finds as you walk; choose **Stop live location** when done. You can also drag the map pin or use the simulated walk. The street map uses OpenStreetMap tiles and the satellite layer uses Esri imagery; attribution is shown on the map.

The unfinished lagoon timeline illustration has been removed. The historical-map tab now explains that real historical layers are waiting for the project database; the map remains on the present-day basemap.

Run the backend tests with `python -m unittest discover -s tests`.

Site coordinates and historical information are supplied research data and should be verified before field use.
