# Renfe Alert

Sistema de seguimiento en tiempo real de los trenes de **largo recorrido de Renfe**. Consulta
el feed público de posiciones cada 15 segundos, guarda el estado en PostgreSQL, detecta qué
trenes circulan **peligrosamente cerca unos de otros** y lo muestra en un panel web con mapa,
tabla de parejas y estadísticas de retrasos.

> Estado: la monitorización y el panel funcionan. El envío de avisos (Telegram, email…) aún
> no está implementado; ver [Mejoras futuras](#mejoras-futuras).

---

## Qué hace

1. **Recoge** las posiciones GPS de toda la flota de largo recorrido (~100 trenes).
2. **Guarda** el estado actual de cada tren en PostgreSQL (una fila por tren).
3. **Calcula** las parejas de trenes cercanas con la fórmula de Haversine y descarta las que
   serían falsos positivos (ver [Cómo se detectan las parejas](#cómo-se-detectan-las-parejas)).
4. **Sirve** el resultado por una API REST (FastAPI).
5. **Muestra** un panel con mapa de España, KPIs, ficha por tren, tabla ordenable de parejas
   e histograma de retrasos, que se refresca solo cada 15 s.

## Arquitectura

```
 Renfe (flotaLD.json)
        │  HTTP GET cada 15 s
        ▼
 renfe_collector.py ──► db.py ──► PostgreSQL (train_state)
   (parseo + cálculo)                    │
                                         ▼
                              api.py (FastAPI) ──► dashboard.html (navegador)
                              /api/trains              fetch cada 15 s
```

| Archivo | Responsabilidad |
|---|---|
| `renfe_collector.py` | Descarga y normaliza el feed (`fetch_raw`, `parse_vehicles`), deduplica trenes y calcula distancias entre parejas. Con `--loop` es el proceso de recogida continua. |
| `db.py` | Capa de acceso a PostgreSQL: conexión, *upsert* del estado (`save_train_state`) y lectura (`load_train_state`) con conversión de zonas horarias. |
| `api.py` | API FastAPI: construye la foto actual (`build_snapshot`) y sirve el panel. |
| `dashboard.html` | Panel de una sola página (HTML + CSS + JS sin dependencias, solo Google Fonts). |
| `dashboard-data.js` | Foto estática de datos; el panel la usa si la API no responde. |
| `db/schema.sql` | Esquema de la tabla `train_state`; Docker lo aplica al crear la base de datos. |
| `docker-compose.yml` | Levanta PostgreSQL 17 con el esquema ya cargado. |

## Requisitos

- Python 3.9 o superior (usa `zoneinfo`)
- Docker (para PostgreSQL)

## Puesta en marcha

```bash
# 1. Dependencias
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. Configuración
cp .env.example .env            # cambia la contraseña si quieres
export DATABASE_URL=postgresql://renfe:cambiame@localhost:5434/renfe

# 3. Base de datos
docker compose up -d

# 4. Recogida de datos (terminal 1)
python renfe_collector.py --loop

# 5. API + panel (terminal 2)
uvicorn api:app
```

Abre <http://localhost:8000>. La documentación interactiva de la API está en
<http://localhost:8000/docs>.

> **Nota:** el código no lee `.env` por sí mismo; solo Docker Compose lo usa. Por eso hay que
> exportar `DATABASE_URL` en cada terminal. Si no se define, `db.py` usa
> `postgresql://renfe:cambiame@localhost:5434/renfe`, que coincide con `.env.example`.

### Modo de una sola consulta

`python renfe_collector.py` (sin `--loop`) hace una única descarga, la guarda en la base de
datos e imprime en consola la tabla de trenes y los pares más cercanos. Es útil para
depurar sin dejar un proceso en marcha.

## Configuración

| Variable / constante | Dónde | Valor por defecto | Significado |
|---|---|---|---|
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `.env` | `renfe` / `cambiame` / `renfe` | Credenciales del contenedor |
| `POSTGRES_PORT` | `.env` | `5434` | Puerto expuesto en tu máquina |
| `DATABASE_URL` | entorno | ver arriba | Cadena de conexión que usan collector y API |
| `ALERT_DISTANCE` | `renfe_collector.py` | `500` m | Por debajo de esta distancia una pareja se marca como alerta |
| `POLL_SECONDS` | `renfe_collector.py` | `15` | Intervalo de consulta al feed |
| `MAX_POSITION_SKEW_S` | `renfe_collector.py` | `30` s | Desfase máximo entre las posiciones de dos trenes |
| `MAX_ROUTE_PAIR_M` | `renfe_collector.py` | `100 000` m | Distancia máxima en el modo «mismo origen y destino» |

## Fuente de datos

El feed es público y no requiere autenticación:

```
https://tiempo-real.largorecorrido.renfe.com/renfe-visor/flotaLD.json
```

Cada elemento de `trenes` aporta, entre otros: `codComercial` (identificador del tren),
`mat` (matrícula; varias unidades acopladas van separadas por comas), `latitud`/`longitud`,
`codEstAnt`/`codEstSig` (estaciones anterior y siguiente), `horaLlegadaSigEst`, `ultRetraso`,
`codOrigen`/`codDestino` y `time` (instante en que se midió la posición).

Peculiaridades que el código tiene en cuenta:

- `horaLlegadaSigEst` viene en **hora de Madrid sin zona**; `db.py` la convierte a
  `TIMESTAMPTZ`. En cambio `time` es epoch UTC.
- El feed da **códigos de estación**, no nombres, por lo que el panel muestra códigos.
- Un mismo `codComercial` puede aparecer repetido; `unique_trains` se queda con un registro
  por tren.
- Registros sin coordenadas o sin identificador se descartan (y se informa por consola).
- `ultRetraso` puede ser negativo (tren adelantado); el panel cuenta los adelantos como
  retraso 0 en la media.

## Cómo se detectan las parejas

Dos trenes pueden estar cerca sin que haya riesgo (viajan acoplados, o las posiciones se
midieron en momentos distintos). Para evitar falsos positivos, `distances_within_groups`
descarta:

| Motivo | Regla | Por qué |
|---|---|---|
| **Acoplados** | comparten alguna unidad en `mat` | Son un único tren físico con dos números comerciales |
| **Desfase** | las posiciones se midieron con más de 30 s de diferencia | A 250 km/h, 30 s son ~2 km de error |
| **Lejos** | distancia superior a `max_meters` (si se indica) | Solo en el modo «misma ruta» |

Las parejas se buscan en dos modos, que el panel muestra en pestañas:

- **Mismo tramo** (`distances_same_segment`): trenes con la misma estación anterior *y*
  siguiente, es decir, en el mismo tramo y sentido. Es el caso con riesgo real de alcance.
- **Mismo origen y destino** (`distances_same_route`): trenes del mismo corredor, hasta 100 km.
  Sirve para ver trenes que se siguen de cerca.

Cada pareja incluye la distancia en metros, la diferencia entre sus horas previstas de
llegada (si van a la misma estación) y el desfase de medición. La distancia se calcula con la
fórmula de Haversine sobre una Tierra esférica de 6 371 km; el error frente a un modelo
elipsoidal es despreciable a estas distancias.

## API

| Método y ruta | Descripción |
|---|---|
| `GET /` | Panel web |
| `GET /dashboard-data.js` | Foto estática de respaldo para el panel |
| `GET /api/health` | `{"ok": true}` si la base de datos responde; `503` si no |
| `GET /api/trains` | Foto actual: trenes y parejas cercanas |
| `GET /api/trains/{vehicle_id}` | Un tren concreto; `404` si no existe |

Respuesta de `/api/trains`:

```jsonc
{
  "timestamp": 1794506571,          // posición más reciente (epoch)
  "alert_distance": 500,
  "max_route_pair_m": 100000,
  "trains": [ { "vehicle_id": "00192", "mat": "730024", "lat": 39.89, "lon": -5.55,
                "prev_stop_id": "35206", "next_stop_id": "...", "next_arrival": "2026-11-12T18:27:20",
                "delay_min": 3, "origin": "...", "destination": "...", "position_time": 1794506560 } ],
  "same_segment": { "pairs": [ { "a": "...", "b": "...", "meters": 412.3, "eta_gap_s": 60, "skew_s": 4 } ],
                    "dropped": { "acoplados": 0, "desfase": 2, "lejos": 0 } },
  "same_route":   { "pairs": [ /* igual */ ], "dropped": { /* igual */ } }
}
```

La API solo devuelve trenes actualizados en los últimos 5 minutos (`max_age_s` en
`load_train_state`); los que dejan de aparecer en el feed desaparecen de la respuesta, aunque
su fila siga en la tabla.

## Base de datos

Una sola tabla, `train_state`, con **una fila por tren** que se sobrescribe en cada consulta
(`INSERT … ON CONFLICT DO UPDATE`, todo en una transacción). Además de las columnas
normalizadas guarda el registro original completo en `raw` (JSONB), por si Renfe cambia el
formato o se quieren campos que hoy no se usan (`product_code`, `accessible`). `updated_at`
marca cuándo escribió el collector, y es lo que permite descartar trenes obsoletos.

## El panel

- **Mapa** de España con todos los trenes coloreados por retraso (verde < 5 min, ámbar
  5–14, rojo ≥ 15), zoom con rueda o pellizco, arrastre y líneas entre parejas; las parejas
  por debajo de 500 m se resaltan con un anillo.
- **KPIs**: trenes en circulación, retraso medio, trenes con 15 min o más y número de parejas
  en alerta.
- **Tabla de parejas** ordenable por distancia, diferencia de llegada o desfase; al pulsar una
  fila el mapa hace zoom sobre los dos trenes.
- **Ficha de tren** con estaciones anterior/siguiente, ruta, posición y sus parejas.
- **Histograma de retrasos** que filtra el mapa al pulsar una columna.
- Filtros por número de tren, «solo trenes con pareja» y distancia máxima.
- **Resiliencia**: se refresca cada 15 s; si la API no responde al cargar usa
  `dashboard-data.js`, y si se cae después, conserva los últimos datos y avisa de que no hay
  conexión.

## Limitaciones conocidas

- **Solo estado actual**: no hay histórico, así que no se pueden analizar tendencias ni
  reconstruir incidentes pasados.
- **Sin avisos**: la alerta se ve en el panel pero no se notifica a nadie.
- **Distancia en línea recta**: no tiene en cuenta la geometría de la vía, ni vías paralelas
  o cercanías entre estaciones, por lo que una pareja «cercana» no implica riesgo real.
- **Dependencia del feed**: es un servicio público no documentado; puede cambiar o limitar
  peticiones sin previo aviso.
- **Sin autenticación** en la API y CORS abierto (`*`); pensado para uso local o de demostración.
- **Sin tests automáticos** por ahora.
- No se muestran nombres de estación, solo códigos.
- `requirements.txt` fija `urllib3<2`, una restricción que conviene revisar antes de desplegar.

## Mejoras futuras

1. **Notificaciones** (Telegram/email) cuando una pareja baje del umbral, con control de
   duplicados para no repetir el aviso.
2. **Histórico** de posiciones (tabla de series temporales) para análisis de retrasos y
   de aproximaciones pasadas.
3. **Nombres de estación** a partir del catálogo de Renfe.
4. **Tests** con `pytest` de `haversine`, `parse_vehicles` y `distances_within_groups`.
5. **Dockerizar** collector y API para arrancar todo con `docker compose up`.
6. Restringir CORS y añadir autenticación si se despliega públicamente.
