import os
import re
import sqlite3
from datetime import datetime
from typing import Any, Dict, Tuple

import pandas as pd
import plotly.express as px
import streamlit as st

from analytics import (
    summarize_severity,
    component_frequency,
    complaints_over_time,
    complaints_by_state,
    simple_case_strength_label,
)
from nhtsa_client import NHTSAClient
from search import keyword_search
from storage import (
    DB_NAME,
    VehicleKey,
    get_cached_vehicle,
    init_db,
    set_cached_vehicle,
    upsert_flat_complaints,
)

# ---------------- Page Config ----------------
st.set_page_config(
    page_title="Vehicle Defect Intelligence (MVP)",
    page_icon="app/assets/logo.png",
    layout="wide",
)

# ---------------- Helpers ----------------
def is_valid_vin(vin: str) -> bool:
    vin = (vin or "").strip().upper()
    return bool(re.match(r"^[A-HJ-NPR-Z0-9]{17}$", vin))


@st.cache_data(ttl=60 * 60 * 24)
def fetch_vehicle_payloads(model_year: int, make: str, model: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    client = NHTSAClient()
    recalls = client.get_recalls_by_vehicle(model_year=model_year, make=make, model=model)
    complaints = client.get_complaints_by_vehicle(model_year=model_year, make=make, model=model)
    return recalls, complaints


def load_complaints_flat(key: VehicleKey) -> pd.DataFrame:
    key = key.norm()
    with sqlite3.connect(DB_NAME) as con:
        df = pd.read_sql_query(
            """
            SELECT
              odi_number, date_filed, state, crash, fire, injuries, deaths, components, summary
            FROM complaints_flat
            WHERE model_year=? AND make=? AND model=?
            """,
            con,
            params=(key.model_year, key.make, key.model),
        )
    for col in ["crash", "fire", "injuries", "deaths"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype(int)
    return df


# ---------------- Local ODI Geo Index Helpers ----------------
GEO_DB = "data/geo_state_counts.sqlite"


def _norm_model(s: str) -> str:
    # Normalize model strings: "F-150" -> "F150", "ACCORD LX" -> "ACCORDLX"
    return "".join(ch for ch in (s or "").upper().strip() if ch.isalnum())


def load_state_counts_local(model_year: int, make: str, model: str) -> pd.DataFrame:
    """
    Returns state-level complaint counts from local ODI FLAT_CMPL index.
    Matching is tolerant to ODI model variants by comparing normalized strings.
    """
    if not os.path.exists(GEO_DB):
        return pd.DataFrame(columns=["state", "count"])

    y = str(model_year).strip()
    mk = (make or "").strip().upper()
    md_norm = _norm_model(model)

    with sqlite3.connect(GEO_DB) as con:
        cand = pd.read_sql_query(
            """
            SELECT modeltxt, state, count
            FROM state_counts
            WHERE yeartxt = ? AND maketxt = ?
            """,
            con,
            params=(y, mk),
        )

    if cand.empty:
        return pd.DataFrame(columns=["state", "count"])

    cand["model_norm"] = cand["modeltxt"].astype(str).map(_norm_model)

    # Match ODI variants like "ACCORD 4DR", "ACCORDLX", "F150", etc.
    matched = cand[cand["model_norm"].str.startswith(md_norm)]

    if matched.empty:
        return pd.DataFrame(columns=["state", "count"])

    out = (
        matched.groupby("state", as_index=False)["count"]
        .sum()
        .sort_values("count", ascending=False)
    )
    return out


def top_odi_model_variants(model_year: int, make: str, limit: int = 25) -> pd.DataFrame:
    """Fallback table when ODI model naming differs from vPIC naming."""
    if not os.path.exists(GEO_DB):
        return pd.DataFrame(columns=["modeltxt", "total"])

    y = str(model_year).strip()
    mk = (make or "").strip().upper()

    with sqlite3.connect(GEO_DB) as con:
        df = pd.read_sql_query(
            """
            SELECT modeltxt, SUM(count) as total
            FROM state_counts
            WHERE yeartxt = ? AND maketxt = ?
            GROUP BY modeltxt
            ORDER BY total DESC
            LIMIT ?
            """,
            con,
            params=(y, mk, int(limit)),
        )
    return df
def complaints_over_time_from_df(df: pd.DataFrame, freq: str = "M") -> pd.DataFrame:
    if df is None or df.empty or "date_filed" not in df.columns:
        return pd.DataFrame(columns=["period", "count"])

    d = pd.to_datetime(df["date_filed"], errors="coerce")
    d = d.dropna()
    if d.empty:
        return pd.DataFrame(columns=["period", "count"])

    s = pd.Series(1, index=d)

    if freq == "Y":
        grouped = s.resample("Y").sum()
        periods = grouped.index.strftime("%Y")
    else:
        grouped = s.resample("M").sum()
        periods = grouped.index.strftime("%Y-%m")

    return pd.DataFrame({"period": list(periods), "count": grouped.values})


# ---------------- Session State Defaults ----------------
if "has_report" not in st.session_state:
    st.session_state.has_report = False
if "vehicle_key" not in st.session_state:
    st.session_state.vehicle_key = None
if "recalls_payload" not in st.session_state:
    st.session_state.recalls_payload = None
if "complaints_payload" not in st.session_state:
    st.session_state.complaints_payload = None
if "last_refreshed" not in st.session_state:
    st.session_state.last_refreshed = None


def main():
    init_db()

    # ---------------- Header ----------------
    col1, col2 = st.columns([1, 8])

    with col1:
        st.image("app/assets/logo.png", width=120)

    with col2:
        st.markdown(
            """
    <div style="display:flex; flex-direction:column; justify-content:center;">

    <h1 style="margin:0; padding:0; line-height:1.05;">
    Vehicle Defect Intelligence Dashboard
    </h1>

    <h1 style="margin-top:2px; margin-bottom:4px; padding:0; line-height:1.05;">
    SLP Prototype
    </h1>

    <p style="margin:0; color:#9ca3af; font-size:15px;">
    NHTSA-powered recall & complaint analytics for legal intake
    </p>

    </div>
    """,
            unsafe_allow_html=True
        )


    client = NHTSAClient()

    # ---------------- Sidebar: Use a Form ----------------
    with st.sidebar:
        st.header("Vehicle Lookup")

        with st.form("vehicle_lookup_form"):
            vin = st.text_input("VIN (optional)", placeholder="17 characters")
            st.markdown("— OR —")
            year = st.text_input("Model Year", placeholder="2021")
            make = st.text_input("Make", placeholder="Toyota")
            model = st.text_input("Model", placeholder="Camry")

            use_model_picker = st.checkbox("Use official model picker (recommended)", value=True)

            picked_model = None
            if use_model_picker and year.strip() and make.strip():
                try:
                    y_int = int(year.strip())
                    models_list = client.get_models_for_make_year(make.strip(), y_int)
                    if models_list:
                        picked_model = st.selectbox("Pick Model (NHTSA/vPIC)", options=models_list)
                except Exception:
                    pass

            run = st.form_submit_button("Run", type="primary")

        if st.session_state.has_report and st.button("Clear current report"):
            st.session_state.has_report = False
            st.session_state.vehicle_key = None
            st.session_state.recalls_payload = None
            st.session_state.complaints_payload = None
            st.session_state.last_refreshed = None
            st.rerun()

    # ---------------- Landing Prompt ----------------
    if not run and not st.session_state.has_report:
        st.markdown(
            """
            <div style="
                background: linear-gradient(90deg, rgba(37,99,235,0.20), rgba(30,64,175,0.25));
                padding: 14px 18px;
                border-radius: 10px;
                color: #bfdbfe;
                border: 1px solid rgba(59,130,246,0.25);
                margin-top: 12px;
                margin-bottom: 8px;
                font-size: 15px;
            ">
                Enter a VIN or <b>Year / Make / Model</b> and click <b>Run</b> to begin.
            </div>
            """,
            unsafe_allow_html=True,
        )
        return

    # ---------------- If Run clicked, fetch and store report ----------------
    if run:
        # VIN decode (optional)
        if vin.strip():
            vin_clean = vin.strip().upper()

            if not is_valid_vin(vin_clean):
                st.error("Invalid VIN format. VIN must be 17 characters (letters + numbers, no I, O, Q).")
                st.stop()

            try:
                decoded = client.decode_vin(vin_clean)

                if decoded.get("model_year") and str(decoded["model_year"]).isdigit():
                    year = decoded["model_year"]
                if decoded.get("make"):
                    make = decoded["make"]
                if decoded.get("model"):
                    model = decoded["model"]

                st.success(f"VIN decoded → {year} {make} {model}")
            except Exception:
                st.error("VIN could not be decoded. Please verify VIN or use Year / Make / Model instead.")
                st.stop()

        # If model picker picked, override model
        if picked_model:
            model = picked_model

        # Validate inputs
        try:
            model_year = int(str(year).strip())
        except Exception:
            st.error("Model Year must be a valid number (e.g., 2021).")
            st.stop()

        if not (make or "").strip() or not (model or "").strip():
            st.error("Make and Model are required.")
            st.stop()

        key = VehicleKey(model_year=model_year, make=make, model=model).norm()

        # Use SQLite cache
        cached = get_cached_vehicle(key, ttl_hours=24)
        if cached:
            recalls_payload, complaints_payload = cached
        else:
            recalls_payload, complaints_payload = fetch_vehicle_payloads(key.model_year, key.make, key.model)
            set_cached_vehicle(key, recalls_payload, complaints_payload)

        # Store flat complaints for symptom search
        upsert_flat_complaints(key, complaints_payload)

        # Persist to session state
        st.session_state.vehicle_key = key
        st.session_state.recalls_payload = recalls_payload
        st.session_state.complaints_payload = complaints_payload
        st.session_state.has_report = True
        st.session_state.last_refreshed = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ---------------- Always read from session state after that ----------------
    if not st.session_state.has_report:
        st.info("Run a vehicle lookup to start.")
        st.stop()

    key = st.session_state.vehicle_key

    st.markdown(
        f"""
        <div style="margin-top:-6px; margin-bottom:10px; color:#cbd5e1; font-size:16px;">
            <b>Report for:</b> {key.model_year} {str(key.make).title()} {str(key.model).title()}
        </div>
        """,
        unsafe_allow_html=True,
    )

    recalls_payload = st.session_state.recalls_payload
    complaints_payload = st.session_state.complaints_payload

    # ---------------- Safe Counts + API Failure Handling ----------------
    recalls_items = []
    complaints_items = []

    if isinstance(recalls_payload, dict):
        if recalls_payload.get("error"):
            st.warning(
                "⚠️ Recalls lookup failed for this exact model string. "
                "Complaints data may still be available. Try using the official model picker."
            )
        else:
            recalls_items = recalls_payload.get("results") or recalls_payload.get("Results") or []

    if isinstance(complaints_payload, dict):
        if complaints_payload.get("error"):
            st.warning(
                "⚠️ Complaint lookup failed for this vehicle. "
                "NHTSA sometimes blocks certain queries or returns empty responses."
            )
        else:
            complaints_items = complaints_payload.get("results") or complaints_payload.get("Results") or []

    recalls_count = len(recalls_items) if isinstance(recalls_items, list) else 0
    complaints_count = len(complaints_items) if isinstance(complaints_items, list) else 0

    severity = summarize_severity(complaints_payload)
    label, reason = simple_case_strength_label(recalls_count, complaints_count, severity)

    tabs = st.tabs(["Overview", "Defect Patterns", "Symptom Search", "Geography", "Trends"])

    # ---------------- Overview ----------------
    with tabs[0]:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Complaints", complaints_count)
        col2.metric("Recalls", recalls_count)
        col3.metric("Crashes", severity.crashes)
        col4.metric("Fires", severity.fires)
        col5.metric("Injuries / Deaths", f"{severity.injuries} / {severity.deaths}")

        last_refreshed = st.session_state.get("last_refreshed", "Unknown")
        st.caption(f"Data source: NHTSA API (live query) • Last refreshed: {last_refreshed}")

        st.subheader("Recommended Follow-up")
        if label == "Strong signal":
            st.success("✅ Immediate attorney review recommended (high severity and/or high volume).")
        elif label == "Moderate signal":
            st.warning("🟡 Secondary screening recommended (review top narratives + recall details).")
        else:
            st.info("ℹ️ Low priority intake (monitor trend / check adjacent years or nearby models).")

        if recalls_count == 0 and complaints_count == 0:
            st.warning(
                "No recalls or complaints returned for this exact Year/Make/Model. "
                "Try the model picker or a nearby year."
            )

        st.subheader("Quick Intake Answers")
        st.write(f"**Known issue?** {'Yes (complaints exist)' if complaints_count > 5 else 'Limited evidence'}")
        st.write(f"**Recall?** {'Yes' if recalls_count > 0 else 'No recall found'}")
        st.write(f"**Pattern?** {'Pattern detected' if complaints_count >= 10 else 'Possibly isolated'}")

        severe_any = severity.crashes or severity.fires or severity.injuries or severity.deaths
        st.write(f"**Severity indicators?** {'Yes' if severe_any else 'None reported'}")

        # Geographic concentration check (live state OR ODI fallback)
        df_state_live = complaints_by_state(complaints_payload)
        if df_state_live.empty:
            df_state_geo = load_state_counts_local(key.model_year, str(key.make).upper(), str(key.model).upper())
        else:
            df_state_geo = df_state_live

        if not df_state_geo.empty:
            total = int(df_state_geo["count"].sum()) if "count" in df_state_geo.columns else 0
            peak = int(df_state_geo["count"].max()) if "count" in df_state_geo.columns else 0
            if total > 0 and peak > int(total * 0.30):
                st.write("**Geographic concentration?** Possible regional clustering")
            else:
                st.write("**Geographic concentration?** Appears broad / nationwide")
        else:
            st.write("**Geographic concentration?** Unknown (no state fields available for this query)")

        st.subheader("Recalls")
        if recalls_count == 0:
            st.write("No recalls returned.")
        else:
            df_r = pd.json_normalize(recalls_items)
            st.dataframe(df_r, use_container_width=True, height=250)

        st.subheader("Complaints (preview)")
        df_c = load_complaints_flat(key)
        if df_c.empty:
            st.write("No complaints returned.")
        else:
            st.dataframe(
                df_c.sort_values(by=["deaths", "injuries", "fire", "crash"], ascending=False).head(30),
                use_container_width=True,
                height=350,
            )
            st.download_button(
                "Download Complaint Evidence CSV",
                df_c.to_csv(index=False),
                file_name=f"{key.make}_{key.model}_{key.model_year}_complaints.csv",
                mime="text/csv",
            )

    # ---------------- Defect Patterns ----------------
    with tabs[1]:
        st.subheader("Most Frequently Reported Components")
        df_comp = component_frequency(complaints_payload, top_n=15)
        if df_comp.empty:
            st.write("No component data available.")
        else:
            fig = px.bar(df_comp, x="component", y="count", title="Top components in complaints")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_comp, use_container_width=True)

    # ---------------- Symptom Search ----------------
    with tabs[2]:
        st.subheader("Search for Similar Cases by Symptom")
        q = st.text_input(
            "Search complaint narratives",
            placeholder="e.g., transmission slipping, jerking, stalling at highway speeds",
        )

        df_all = load_complaints_flat(key)
        colA, colB, colC = st.columns(3)
        only_crash = colA.checkbox("Only crash-related", value=False)
        only_fire = colB.checkbox("Only fire-related", value=False)
        min_inj = colC.selectbox("Min injuries", options=[0, 1, 2, 3, 5], index=0)

        if df_all.empty:
            st.write("No complaints available to search.")
        else:
            df_f = df_all.copy()
            if only_crash:
                df_f = df_f[df_f["crash"] == 1]
            if only_fire:
                df_f = df_f[df_f["fire"] == 1]
            df_f = df_f[df_f["injuries"] >= int(min_inj)]

            limit = st.selectbox("Max results", [25, 50, 100, 200], index=1)

            if q.strip():
                df_res = keyword_search(df_f, q.strip(), top_k=int(limit))
            else:
                df_res = df_f.sort_values(by=["deaths", "injuries", "fire", "crash"], ascending=False).head(int(limit))

            st.write(f"Showing {len(df_res)} results (sorted by severity relevance).")
            st.dataframe(
                df_res[["odi_number", "date_filed", "state", "components", "crash", "fire", "injuries", "deaths", "summary"]],
                use_container_width=True,
                height=520,
            )

    # ---------------- Geography ----------------
    with tabs[3]:
        st.subheader("Where are complaints coming from?")

        # 1) Try live complaints feed (often missing state fields)
        df_state = complaints_by_state(complaints_payload)

        used_source = "NHTSA live complaints feed"

        if df_state.empty:
            used_source = "Local ODI FLAT_CMPL geo index (offline)"
            st.caption(
                "Live complaints API does not include state/location for this query. "
                "Using local ODI FLAT_CMPL index for state counts (offline)."
            )

            df_state = load_state_counts_local(
                key.model_year,
                str(key.make).upper(),
                str(key.model).upper(),
            )

        if df_state.empty:
            st.info(
                "No state counts found for this vehicle/year. "
                "Try a nearby year or confirm the ODI FLAT_CMPL index is built."
            )

        else:
            # Clean state codes
            df_state["state"] = df_state["state"].astype(str).str.upper().str.strip()
            df_state = df_state[df_state["state"].str.len() == 2]

            # Map
            fig = px.choropleth(
                df_state,
                locations="state",
                locationmode="USA-states",
                color="count",
                scope="usa",
                title="Complaint concentration by state",
            )

            st.plotly_chart(fig, use_container_width=True)

            # Table
            st.dataframe(
                df_state.sort_values("count", ascending=False),
                use_container_width=True,
            )

            # ✅ ADD THIS HERE (after map + table)
            st.caption(
                f"Source: {used_source}. "
                "ODI FLAT_CMPL data provided by NHTSA (data.transportation.gov). "
                "Counts aggregated locally by year, make, model, and state."
            )


    # ---------------- Trends ----------------
    with tabs[4]:
        st.subheader("Complaint Volume Trends Over Time")
        gran = st.radio("Granularity", options=["Monthly", "Yearly"], horizontal=True)
        freq = "M" if gran == "Monthly" else "Y"

        df_all = load_complaints_flat(key)  # <-- local DB, always consistent with your app
        df_trend = complaints_over_time_from_df(df_all, freq=freq)

        if df_trend.empty:
            st.write("No complaint date data available.")
        else:
            fig = px.line(df_trend, x="period", y="count", markers=True, title="Complaints over time")
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_trend, use_container_width=True)



if __name__ == "__main__":
    main()
