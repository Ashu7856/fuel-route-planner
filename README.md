# Fuel Route Planner (Django 6.1 + DRF)

Given a start and finish inside the USA, returns the driving route, the cost-optimal
fuel stops (500-mile range), and total fuel spend at 10 MPG.

## Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py import_stations      # loads data/fuel-prices-for-be-assessment.csv
python manage.py runserver
python manage.py test                 # 8 tests
```

## API
`POST /api/route/`  (or `GET /api/route/?start=...&finish=...`)
```json
{ "start": "Los Angeles, CA", "finish": "New York, NY" }
```
`start`/`finish` accept `"City, ST"`, `"lat,lng"`, or a free-form US address.
Optional: `range_miles` (500), `mpg` (10), `corridor_miles` (10), `initial_fuel_miles` (full tank).

Response: `distance_miles`, `duration_hours`, `fuel_stops[]` (station, address, price, gallons, cost,
mile marker), `total_gallons_needed`, `total_fuel_cost`, a GeoJSON `map` (route line + start/finish/stops,
paste into geojson.io) and `map_url`, an interactive Leaflet map: `GET /api/route/map/?start=..&finish=..`.

Errors: `400` bad/non-US location, `422` no station within range on the route, `502` routing service down.

## Design (why it's fast)
| Concern | Approach |
|---|---|
| External calls | **One** OSRM call per route (`overview=full`, GeoJSON). Route is cached 24h, so changing MPG/range or repeating a trip makes **zero** calls. |
| Geocoding input | `lat,lng` parsed locally; `City, ST` resolved from an offline gazetteer (no call). Nominatim is only a fallback for free-form addresses. |
| Station coordinates | The CSV has none, so `import_stations` geocodes city/state offline once (6,626/6,626 US stations matched) and stores them in the DB. |
| Finding stations on route | Station array held in memory; one SciPy KD-tree over the route vertices snaps all ~6.6k stations in a few ms. Stations within `corridor_miles` get a mile marker. |
| Choosing stops | Greedy "gas-station problem" (provably optimal with continuous purchases): buy just enough to reach the next cheaper station within range, otherwise fill up and hop to the cheapest reachable one. Tested against a brute-force DP on random routes. |

Warm response ≈ 10 ms excluding the single OSRM round-trip.

## Assumptions
* Vehicle **starts with a full 500-mile tank** (not billed). `total_fuel_cost` is what's spent at the listed
  stops; pass `initial_fuel_miles` to start with less.
* Duplicate truckstop IDs are collapsed to the lowest listed price; the 620 Canadian rows are dropped.
* Stations are placed at their **city centre** (the CSV has no lat/lng), hence the 10-mile corridor.
* Contiguous USA only; vehicle must reach the destination with >= 0 fuel (no reserve).
