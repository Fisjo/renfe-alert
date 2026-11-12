import logging
import os, time, math, requests

URL = "https://tiempo-real.largorecorrido.renfe.com/renfe-visor/flotaLD.json"
ALERT_DISTANCE = 500
POLL_SECONDS = 15
TIMEOUT = 10

SAMPLE_FILE = "./sample-file"

EARTH_RADIUS_M = 6371000



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


def parse_vehicles(raw):
    """
    Normaliza el feed flotaLD.json de Renfe (largo recorrido).

    Devuelve (timestamp, vehicles):
      - timestamp: int (epoch, segundos) de la posición más reciente, o None
      - vehicles: lista de dicts con vehicle_id, lat, lon, next_stop_id,
        next_arrival (str ISO), delay_min (int o None), origin, destination,
        position_time (epoch)
    """
    if not raw or not raw.get("trenes"):
        print("El archivo no se leyó correctamente")
        return None, []

    vehicles = []
    discarded = 0

    for t in raw["trenes"]:
        vehicle_id = t.get("codComercial")

        try:
            lat, lon = float(t["latitud"]), float(t["longitud"])
        except (KeyError, TypeError, ValueError):
            discarded += 1
            continue

        if vehicle_id is None:
            discarded += 1
            continue

        try:
            delay = int(t.get("ultRetraso"))
        except (TypeError, ValueError):
            delay = None

        try:
            pos_time = int(t.get("time"))
        except (TypeError, ValueError):
            pos_time = None

        vehicles.append({
            "vehicle_id": vehicle_id,
            "lat": lat,
            "lon": lon,
            "next_stop_id": t.get("codEstSig"),
            "next_arrival": t.get("horaLlegadaSigEst"),
            "delay_min": delay,
            "origin": t.get("codOrigen"),
            "destination": t.get("codDestino"),
            "position_time": pos_time,
        })

    if discarded:
        print(f"Descartados {discarded} registros incompletos")

    times = [v["position_time"] for v in vehicles if v["position_time"]]
    timestamp = max(times) if times else None

    return timestamp, vehicles

def haversine(lat1, lon1, lat2, lon2):
    """Distancia en metros entre dos puntos GPS."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


def unique_trains(vehicles):
    """Un registro por vehicle_id (los viajes duplicados comparten posición)."""
    by_id = {}
    for v in vehicles:
        if v["vehicle_id"] is not None:
            by_id.setdefault(v["vehicle_id"], v)  # me quedo con el primero
    return sorted(by_id.values(), key=lambda v: v["vehicle_id"])

