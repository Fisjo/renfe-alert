import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import psycopg
from psycopg.types.json import Jsonb

# Desde tu Mac el puerto es el 5434 (ver docker-compose.yml).
DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://renfe:renfe@localhost:5434/renfe"
)
MADRID = ZoneInfo("Europe/Madrid")


def connect():
    return psycopg.connect(DATABASE_URL)


def _epoch_to_dt(value):
    """Segundos desde 1970 -> datetime en UTC (o None)."""
    return datetime.fromtimestamp(value, tz=timezone.utc) if value else None


def _madrid_to_dt(value):
    """'2026-11-12T18:27:20' (hora de Madrid, sin zona) -> datetime con zona (o None)."""
    try:
        return datetime.fromisoformat(value).replace(tzinfo=MADRID)
    except (TypeError, ValueError):
        return None


UPSERT_SQL = """
INSERT INTO train_state (
    vehicle_id, mat, prev_stop_id, next_stop_id, next_arrival, origin, destination,
    product_code, accessible, lat, lon, delay_min, position_time, raw
) VALUES (
    %(vehicle_id)s, %(mat)s, %(prev_stop_id)s, %(next_stop_id)s, %(next_arrival)s,
    %(origin)s, %(destination)s, %(product_code)s, %(accessible)s, %(lat)s, %(lon)s,
    %(delay_min)s, %(position_time)s, %(raw)s
)
ON CONFLICT (vehicle_id) DO UPDATE SET
    mat           = EXCLUDED.mat,
    prev_stop_id  = EXCLUDED.prev_stop_id,
    next_stop_id  = EXCLUDED.next_stop_id,
    next_arrival  = EXCLUDED.next_arrival,
    origin        = EXCLUDED.origin,
    destination   = EXCLUDED.destination,
    product_code  = EXCLUDED.product_code,
    accessible    = EXCLUDED.accessible,
    lat           = EXCLUDED.lat,
    lon           = EXCLUDED.lon,
    delay_min     = EXCLUDED.delay_min,
    position_time = EXCLUDED.position_time,
    raw           = EXCLUDED.raw,
    updated_at    = now()
"""


def save_train_state(conn, trains):
    """Inserta o actualiza una fila por tren. `trains` debe venir de unique_trains
    (sin vehicle_id repetidos). Todo en una sola transacción."""
    rows = [
        {
            **t,
            "next_arrival": _madrid_to_dt(t["next_arrival"]),
            "position_time": _epoch_to_dt(t["position_time"]),
            "raw": Jsonb(t["raw"]),
        }
        for t in trains
    ]
    with conn.transaction(), conn.cursor() as cur:
        cur.executemany(UPSERT_SQL, rows)
    return len(rows)
