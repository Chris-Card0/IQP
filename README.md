# Ancient Venice Interactive Tour

Interactive historical and archaeological guide for the WPI Venice Project Center. Choose 4–5 landmarks for a walking route, select artifact interests for nearby discoveries, browse research records, and export the site dataset as GeoJSON.

The WPI Research catalog includes past IQP Venetian church records loaded directly from `data/venetian_churches.csv`. Select **Venetian Churches** under Route Builder walking preferences to see church proximity alerts in **Near Me (GPS)**; adjust the preferred-find radius there. Use the **All churches** map toggle to show or hide every church point.

## Run locally

Requires Python 3.9 or newer; there are no Python packages to install.

1. Open a terminal in this folder.
2. Run `python server.py` (on Windows, `py server.py` also works).
3. Visit `http://127.0.0.1:8000`.

If the server reports that port 8000 is already in use, stop the other server with **Ctrl+C** in its terminal or use the browser tab that is already open.
