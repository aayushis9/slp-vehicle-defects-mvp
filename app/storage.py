import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

DB_NAME = "cache.db"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class VehicleKey:
    model_year: int
    make: str
    model: str

    def norm(self) -> "VehicleKey":
        return VehicleKey(
            model_year=int(self.model_year),
            make=(self.make or "").strip().upper(),
            model=(self.model or "").strip().upper(),
        )


def init_db(db_path: str = DB_NAME) -> None:
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS vehicle_cache (
              model_year INTEGER NOT NULL,
              make TEXT NOT NULL,
              model TEXT NOT NULL,
              fetched_at TEXT NOT NULL,
              recalls_json TEXT NOT NULL,
              complaints_json TEXT NOT NULL,
              PRIMARY KEY (model_year, make, model)
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS complaints_flat (
              odi_number TEXT PRIMARY KEY,
              model_year INTEGER,
              make TEXT,
              model TEXT,
              date_filed TEXT,
              state TEXT,
              crash INTEGER,
              fire INTEGER,
              injuries INTEGER,
              deaths INTEGER,
              components TEXT,
              summary TEXT,
              raw_json TEXT
            )
            """
        )
        con.commit()


def get_cached_vehicle(
    key: VehicleKey, ttl_hours: int = 24, db_path: str = DB_NAME
) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
    key = key.norm()
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(
            """
            SELECT fetched_at, recalls_json, complaints_json
            FROM vehicle_cache
            WHERE model_year=? AND make=? AND model=?
            """,
            (key.model_year, key.make, key.model),
        )
        row = cur.fetchone()
        if not row:
            return None

        fetched_at_iso, recalls_s, complaints_s = row
        try:
            fetched_at = datetime.fromisoformat(fetched_at_iso.replace("Z", "+00:00"))
        except Exception:
            return None

        age_hours = (datetime.now(timezone.utc) - fetched_at).total_seconds() / 3600.0
        if age_hours > ttl_hours:
            return None

        return (json.loads(recalls_s), json.loads(complaints_s))


def set_cached_vehicle(
    key: VehicleKey, recalls: Dict[str, Any], complaints: Dict[str, Any], db_path: str = DB_NAME
) -> None:
    key = key.norm()
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        cur.execute(
            """
            INSERT INTO vehicle_cache(model_year, make, model, fetched_at, recalls_json, complaints_json)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(model_year, make, model)
            DO UPDATE SET
              fetched_at=excluded.fetched_at,
              recalls_json=excluded.recalls_json,
              complaints_json=excluded.complaints_json
            """,
            (
                key.model_year,
                key.make,
                key.model,
                utc_now_iso(),
                json.dumps(recalls),
                json.dumps(complaints),
            ),
        )
        con.commit()


def upsert_flat_complaints(
    key: VehicleKey, complaints_json: Dict[str, Any], db_path: str = DB_NAME
) -> int:
    key = key.norm()
    items = (complaints_json or {}).get("results") or (complaints_json or {}).get("Results") or []
    if not isinstance(items, list):
        return 0

    count = 0
    with sqlite3.connect(db_path) as con:
        cur = con.cursor()
        for c in items:
            if not isinstance(c, dict):
                continue

            odi = str(c.get("odiNumber") or c.get("ODINumber") or c.get("odi_number") or "").strip()
            if not odi:
                continue

            date_filed = c.get("dateComplaintFiled") or c.get("dateFiled") or c.get("DateComplaintFiled") or None
            state = c.get("state") or c.get("State") or c.get("locationState") or None

            crash = int(bool(c.get("crash") or c.get("Crash") or False))
            fire = int(bool(c.get("fire") or c.get("Fire") or False))

            injuries = c.get("numberOfInjuries") or c.get("injuries") or 0
            deaths = c.get("numberOfDeaths") or c.get("deaths") or 0
            try:
                injuries = int(injuries)
            except Exception:
                injuries = 0
            try:
                deaths = int(deaths)
            except Exception:
                deaths = 0

            components_val = c.get("components") or c.get("Components") or []
            if isinstance(components_val, list):
                components_s = ", ".join([str(x).strip() for x in components_val if str(x).strip()])
            else:
                components_s = str(components_val or "").strip()

            summary = c.get("summary") or c.get("Summary") or c.get("description") or ""
            summary = str(summary or "")

            cur.execute(
                """
                INSERT INTO complaints_flat(
                  odi_number, model_year, make, model,
                  date_filed, state, crash, fire, injuries, deaths,
                  components, summary, raw_json
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(odi_number) DO UPDATE SET
                  model_year=excluded.model_year,
                  make=excluded.make,
                  model=excluded.model,
                  date_filed=excluded.date_filed,
                  state=excluded.state,
                  crash=excluded.crash,
                  fire=excluded.fire,
                  injuries=excluded.injuries,
                  deaths=excluded.deaths,
                  components=excluded.components,
                  summary=excluded.summary,
                  raw_json=excluded.raw_json
                """,
                (
                    odi,
                    key.model_year,
                    key.make,
                    key.model,
                    date_filed,
                    state,
                    crash,
                    fire,
                    injuries,
                    deaths,
                    components_s,
                    summary,
                    json.dumps(c),
                ),
            )
            count += 1

        con.commit()

    return count
