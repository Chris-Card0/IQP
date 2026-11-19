# Ancient Venice Interactive Tour

Interactive historical and archaeological guide for the WPI Venice Project Center. Choose 1–5 landmarks for a walking route, optionally start at your current location, select artifact interests for nearby discoveries, browse research records, and export the site dataset as GeoJSON. A one-stop route requires the current-location start option.

The WPI Research catalog includes historic records from `data/venetian_churches.csv`, `data/venetian_confraternities_guilds.csv`, `data/venetian_doges_dynasties.csv`, and inscription records from `data/venetian_inscriptions.csv`. The server parses the inscription CSV (including quoted multiline text) and exposes normalized records at `GET /api/inscriptions`. Select **Venetian Churches**, **Confraternities & Guilds**, **Doges & Dynasties**, or **Inscriptions & Street Altars** under Route Builder walking preferences to see nearby locations in **Near Me (GPS)**. Click a nearby location to view its facts and inscription text in the right-hand panel, where it can also be narrated with text-to-speech. Use the corresponding map toggles to show all points in each collection.

## Run locally

Requires Python 3.9 or newer; there are no Python packages to install.

1. Open a terminal in this folder.
2. Run `python server.py` (on Windows, `py server.py` also works).
3. Visit `http://127.0.0.1:8000`.

If the server reports that port 8000 is already in use, stop the other server with **Ctrl+C** in its terminal or use the browser tab that is already open.
