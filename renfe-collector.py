import logging
import os, time, math, requests

URL = "https://gtfsrt.renfe.com/vehicle_positions_LD.json#"
ALERT_DISTANCE = 500
POLL_SECONDS = 15
TIMEOUT = 10

SAMPLE_FILE = "./sample-file"


def fetch_raw(): 
    try: 
        resp = requests.get(URL, timeout=TIMEOUT)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        print(e)
    except ValueError as e:
        print(e)
    return None


data = fetch_raw()
if data:
    print(data["header"])

def parse_vehicles(raw):
    """
    Normaliza el feed GTFS-RT de posiciones de vehículos.

    Devuelve (timestamp, vehicles):
      - timestamp: int (en segundos) o None si no viene
      - vehicles: lista de dicts con trip_id, vehicle_id, lat, lon, status, stop_id
    """
    if not raw or not raw.get("entity"):
        print("El archivo no se leyó correctamente")
        return None, []

    try:
        timestamp = int(raw.get("header", {}).get("timestamp"))
    except (TypeError, ValueError):
        timestamp = None

    vehicles = []
    discarded = 0

    for entity in raw["entity"]:
        v = entity.get("vehicle")
        if not v:
            continue  # entidad de otro tipo

        trip_id = v.get("trip", {}).get("tripId")
        pos = v.get("position", {})
        lat = pos.get("latitude")
        lon = pos.get("longitude")

        if trip_id is None or lat is None or lon is None:
            discarded += 1
            continue

        try:
            lat, lon = float(lat), float(lon)
        except (TypeError, ValueError):
            discarded += 1
            continue

        vehicles.append({
            "trip_id": trip_id,
            "vehicle_id": v.get("vehicle", {}).get("id"),
            "lat": lat,
            "lon": lon,
            "status": v.get("currentStatus"),
            "stop_id": v.get("stopId"),  # puede ser None
        })

    if discarded:
        print(f"Descartados {discarded} registros incompletos")

    return timestamp, vehicles
