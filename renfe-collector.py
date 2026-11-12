import os, time, math, requests
from collections import namedtuple
from datetime import datetime
from itertools import combinations

import db

MAX_POSITION_SKEW_S = 30     # máx. diferencia entre las horas de posición de dos trenes
MAX_ROUTE_PAIR_M = 100_000   # en "mismo origen y destino", ignorar pares más lejos de esto

URL ="https://tiempo-real.largorecorrido.renfe.com/renfe-visor/flotaLD.json"
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
      - vehicles: lista de dicts con vehicle_id, mat, lat, lon, prev_stop_id,
        next_stop_id, next_arrival (str ISO), delay_min (int o None), origin,
        destination, position_time (epoch), product_code (int o None),
        accessible (bool o None) y raw (el registro original del feed)
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

        try:
            product_code = int(t.get("codProduct"))
        except (TypeError, ValueError):
            product_code = None

        vehicles.append({
            "vehicle_id": vehicle_id,
            "mat": t.get("mat"),
            "lat": lat,
            "lon": lon,
            "prev_stop_id": t.get("codEstAnt"),
            "next_stop_id": t.get("codEstSig"),
            "next_arrival": t.get("horaLlegadaSigEst"),
            "delay_min": delay,
            "origin": t.get("codOrigen"),
            "destination": t.get("codDestino"),
            "position_time": pos_time,
            "product_code": product_code,
            "accessible": t.get("accesible"),
            "raw": t,  # registro original completo, por si cambia el formato
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


def group_by(trains, key_fn):
    """Agrupa trenes por la clave que devuelva key_fn (se ignoran las claves con None)."""
    groups = {}
    for t in trains:
        key = key_fn(t)
        if None in key:
            continue
        groups.setdefault(key, []).append(t)
    return groups


Pair = namedtuple("Pair", "a b meters eta_gap_s skew_s")


def _units(train):
    """Unidades (matrículas) de un tren: 'a,b' -> {'a', 'b'}."""
    return set((train.get("mat") or "").split(",")) - {""}


def _eta_gap_s(a, b):
    """Segundos entre las llegadas previstas, solo si van a la misma estación."""
    if a["next_stop_id"] != b["next_stop_id"]:
        return None
    try:
        ta = datetime.fromisoformat(a["next_arrival"])
        tb = datetime.fromisoformat(b["next_arrival"])
    except (TypeError, ValueError):
        return None
    return abs((ta - tb).total_seconds())


def distances_within_groups(groups, max_skew_s=MAX_POSITION_SKEW_S, max_meters=None):
    """Pares de trenes de un mismo grupo con su distancia.

    Descarta:
      - pares acoplados (comparten alguna unidad en `mat`): son un solo tren físico;
      - pares cuyas posiciones se midieron con más de `max_skew_s` segundos de
        diferencia (a 250 km/h, 30 s son ~2 km de error);
      - pares a más de `max_meters` (si se indica).

    Devuelve (pares, descartados) con pares = [Pair(a, b, meters, eta_gap_s,
    skew_s)] ordenados por distancia, y a < b gracias a unique_trains.
    """
    pairs = []
    dropped = {"acoplados": 0, "desfase": 0, "lejos": 0}

    for members in groups.values():
        for a, b in combinations(members, 2):
            if _units(a) & _units(b):
                dropped["acoplados"] += 1
                continue

            skew = None
            if a["position_time"] and b["position_time"]:
                skew = abs(a["position_time"] - b["position_time"])
                if skew > max_skew_s:
                    dropped["desfase"] += 1
                    continue

            d = haversine(a["lat"], a["lon"], b["lat"], b["lon"])
            if max_meters is not None and d > max_meters:
                dropped["lejos"] += 1
                continue

            pairs.append(Pair(a["vehicle_id"], b["vehicle_id"], d, _eta_gap_s(a, b), skew))

    pairs.sort(key=lambda p: p.meters)
    return pairs, dropped


def distances_same_segment(trains, **kw):
    """Trenes entre la misma estación anterior y siguiente (mismo sentido)."""
    groups = group_by(trains, lambda t: (t["prev_stop_id"], t["next_stop_id"]))
    return distances_within_groups(groups, **kw)


def distances_same_route(trains, **kw):
    """Trenes con el mismo origen y el mismo destino."""
    groups = group_by(trains, lambda t: (t["origin"], t["destination"]))
    return distances_within_groups(groups, **kw)


def main():
    timestamp, vehicles = parse_vehicles(fetch_raw())
    trains = unique_trains(vehicles)

    with db.connect() as conn:
        saved = db.save_train_state(conn, trains)
    print(f"Guardados {saved} trenes en train_state")

    print(f"timestamp={timestamp} | trenes={len(trains)}")
    print(f"{'tren':<7}{'lat':>10}{'lon':>11}{'retraso':>9}  {'sig.est':<8}llegada")
    for t in trains:
        delay = "-" if t["delay_min"] is None else f"{t['delay_min']} min"
        print(f"{t['vehicle_id']:<7}{t['lat']:>10.5f}{t['lon']:>11.5f}{delay:>9}  "
              f"{t['next_stop_id'] or '-':<8}{t['next_arrival'] or '-'}")

    for title, (pairs, dropped) in (
        ("mismo tramo", distances_same_segment(trains)),
        ("mismo origen y destino", distances_same_route(trains, max_meters=MAX_ROUTE_PAIR_M)),
    ):
        print(f"\n[{title}] pares={len(pairs)} | descartados={dropped} | de más cerca a más lejos:")
        for p in pairs:
            eta = "-" if p.eta_gap_s is None else f"{p.eta_gap_s / 60:.0f} min"
            print(f"{p.a} - {p.b}: {p.meters:.0f} m | dif. llegada {eta} | desfase {p.skew_s}s")


if __name__ == "__main__":
    main()

