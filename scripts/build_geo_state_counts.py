import os
import sqlite3
import csv
import pandas as pd

# Path to the extracted complaints flat file (tab-delimited)
INPUT_TXT = os.path.join("data", "FLAT_CMPL.txt")

# Output SQLite for app geo queries
OUT_DB = os.path.join("data", "geo_state_counts.sqlite")

CHUNK_SIZE = 250_000

# ODI complaints file (CMPL.txt / FLAT_CMPL.txt) has 49 fields (per ODI import instructions)
# We'll name them so we can reliably reference columns even if the file has no header row.
ALL_COLS_49 = [
    "CMPLID", "ODINO", "MFR_NAME", "MAKETXT", "MODELTXT", "YEARTXT", "CRASH",
    "FAILDATE", "FIRE", "INJURED", "DEATHS", "COMPDESC", "CITY", "STATE", "VIN",
    "DATEA", "LDATE", "MILES", "OCCURENCES", "CDESCR", "CMPL_TYPE", "POLICE_RPT_YN",
    "PURCH_DT", "ORIG_OWNER_YN", "ANTI_BRAKES_YN", "CRUISE_CONT_YN", "NUM_CYLS",
    "DRIVE_TRAIN", "FUEL_SYS", "FUEL_TYPE", "TRANS_TYPE", "VEH_SPEED", "DOT",
    "TIRE_SIZE", "LOC_OF_TIRE", "TIRE_FAIL_TYPE", "ORIG_EQUIP_YN", "MANUF_DT",
    "SEAT_TYPE", "RESTRAINT_TYPE", "DEALER_NAME", "DEALER_TEL", "DEALER_CITY",
    "DEALER_STATE", "DEALER_ZIP", "PROD_TYPE", "REPAIRED_YN", "MEDICAL_ATTN",
    "VEHICLES_TOWED_YN"
]

# We only need these 4 columns
WANTED = ["MAKETXT", "MODELTXT", "YEARTXT", "STATE"]
WANTED_USECOLS = [ALL_COLS_49.index(c) for c in WANTED]  # [3,4,5,13]


def ensure_schema(con: sqlite3.Connection):
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS state_counts (
            yeartxt  TEXT NOT NULL,
            maketxt  TEXT NOT NULL,
            modeltxt TEXT NOT NULL,
            state    TEXT NOT NULL,
            count    INTEGER NOT NULL,
            PRIMARY KEY (yeartxt, maketxt, modeltxt, state)
        );
        """
    )
    con.execute(
        "CREATE INDEX IF NOT EXISTS idx_state_counts_vehicle ON state_counts(yeartxt, maketxt, modeltxt);"
    )
    con.commit()


def upsert_counts(con: sqlite3.Connection, df_counts: pd.DataFrame):
    # expected columns: YEARTXT, MAKETXT, MODELTXT, STATE, count
    rows = list(df_counts.itertuples(index=False, name=None))
    con.executemany(
        """
        INSERT INTO state_counts (yeartxt, maketxt, modeltxt, state, count)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(yeartxt, maketxt, modeltxt, state)
        DO UPDATE SET count = state_counts.count + excluded.count;
        """,
        rows,
    )
    con.commit()


def main():
    if not os.path.exists(INPUT_TXT):
        raise FileNotFoundError(
            f"Missing {INPUT_TXT}. Put the extracted FLAT_CMPL.txt into data/ first."
        )

    os.makedirs(os.path.dirname(OUT_DB), exist_ok=True)

    total_kept = 0
    total_groups = 0

    with sqlite3.connect(OUT_DB) as con:
        ensure_schema(con)

        reader = pd.read_csv(
            INPUT_TXT,
            sep="\t",
            header=None,               # <-- KEY FIX: file often has NO header row
            names=ALL_COLS_49,         # <-- assign correct column names
            usecols=WANTED_USECOLS,    # <-- read only the 4 columns we need
            dtype=str,
            chunksize=CHUNK_SIZE,
            engine="c",
            quoting=csv.QUOTE_NONE,
            on_bad_lines="skip",
            encoding_errors="ignore",
        )

        for i, chunk in enumerate(reader, start=1):
            # Normalize
            chunk["MAKETXT"] = chunk["MAKETXT"].fillna("").str.strip().str.upper()
            chunk["MODELTXT"] = chunk["MODELTXT"].fillna("").str.strip().str.upper()
            chunk["YEARTXT"] = chunk["YEARTXT"].fillna("").str.strip()
            chunk["STATE"] = chunk["STATE"].fillna("").str.strip().str.upper()

            # Keep only plausible rows
            chunk = chunk[
                (chunk["STATE"].str.len() == 2)
                & (chunk["MAKETXT"] != "")
                & (chunk["MODELTXT"] != "")
                & (chunk["YEARTXT"].str.len() == 4)
            ]

            if chunk.empty:
                continue

            total_kept += len(chunk)

            df_counts = (
                chunk.groupby(["YEARTXT", "MAKETXT", "MODELTXT", "STATE"])
                .size()
                .reset_index(name="count")
            )

            total_groups += len(df_counts)
            upsert_counts(con, df_counts)

            print(f"Processed chunk {i}, kept_rows={len(chunk):,}, groups={len(df_counts):,}")

    print(f"✅ Done. Built geo index at: {OUT_DB}")
    print(f"Total kept rows: {total_kept:,}")
    print(f"Total groups inserted: {total_groups:,}")


if __name__ == "__main__":
    main()
