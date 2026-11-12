-- Estado actual: una fila por tren, se sobrescribe en cada consulta.
CREATE TABLE IF NOT EXISTS train_state (
  vehicle_id    TEXT PRIMARY KEY,          -- codComercial
  mat           TEXT,                      -- matrícula(s), puede traer varias unidades separadas por coma
  prev_stop_id  TEXT,                      -- codEstAnt
  next_stop_id  TEXT,                      -- codEstSig
  next_arrival  TIMESTAMPTZ,               -- horaLlegadaSigEst (hora de Madrid en el feed)
  origin        TEXT,                      -- codOrigen
  destination   TEXT,                      -- codDestino
  product_code  INTEGER,                   -- codProduct
  accessible    BOOLEAN,                   -- accesible
  lat           DOUBLE PRECISION NOT NULL,
  lon           DOUBLE PRECISION NOT NULL,
  delay_min     INTEGER,                   -- ultRetraso (puede ser negativo)
  position_time TIMESTAMPTZ,               -- time: cuándo midió la posición el tren
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),  -- cuándo lo escribimos nosotros
  raw           JSONB                      -- registro original completo del feed
);
