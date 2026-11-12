from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
import psycopg

import db
import renfe_collector as rc


def _pairs_payload(pairs, dropped):
    return {
        "pairs": [
            {"a": p.a, "b": p.b, "meters": round(p.meters, 1),
             "eta_gap_s": p.eta_gap_s, "skew_s": p.skew_s}
            for p in pairs
        ],
        "dropped": dropped,
    }


def build_snapshot(trains):
    """Misma estructura que dashboard-data.js."""
    times = [t["position_time"] for t in trains if t["position_time"]]
    segment = rc.distances_same_segment(trains)
    route = rc.distances_same_route(trains, max_meters=rc.MAX_ROUTE_PAIR_M)
    return {
        "timestamp": max(times) if times else None,
        "alert_distance": rc.ALERT_DISTANCE,
        "max_route_pair_m": rc.MAX_ROUTE_PAIR_M,
        "trains": trains,
        "same_segment": _pairs_payload(*segment),
        "same_route": _pairs_payload(*route),
    }


def _load_trains():
    try:
        with db.connect() as conn:
            return db.load_train_state(conn)
    except psycopg.OperationalError:
        raise HTTPException(503, "Base de datos no disponible")


app = FastAPI(title="Renfe Alert API")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])


@app.get("/api/health")
def health():
    _load_trains()
    return {"ok": True}


@app.get("/api/trains")
def trains():
    """Foto actual: trenes y pares cercanos, listo para el panel."""
    return build_snapshot(_load_trains())


@app.get("/api/trains/{vehicle_id}")
def train(vehicle_id: str):
    for t in _load_trains():
        if t["vehicle_id"] == vehicle_id:
            return t
    raise HTTPException(404, "Tren no encontrado")


@app.get("/")
def index():
    return FileResponse("dashboard.html")
