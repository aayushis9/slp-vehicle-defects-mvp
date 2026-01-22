# SLP Vehicle Defects Intelligence MVP (Streamlit)

An attorney intake and investigation tool that analyzes **vehicle defect patterns, severity signals, geographic complaint concentration, and complaint trends** using official NHTSA and ODI datasets.

Built as a fast prototype to help legal teams quickly assess case strength.


## ✨ What This Tool Does

Given a **VIN** or **Year / Make / Model**, the system:

### Intake Intelligence

* Decodes VIN → Vehicle metadata (via NHTSA vPIC)
* Fetches official NHTSA recalls
* Fetches ODI consumer complaints

### Pattern Detection

* Identifies most frequent failing components
* Detects complaint volume patterns
* Highlights repeated defect categories

### Severity Signals

Automatically summarizes:

* Crashes
* Fires
* Injuries
* Deaths

### Symptom Search

* Keyword search over complaint narratives
* Filter by crash/fire/injury severity
* Adjustable result limits (25–200)

### Geographic Context

Two-tier strategy:

1. **Live NHTSA complaints API** (when state is available)
2. **Offline ODI FLAT_CMPL dataset index** (reliable fallback)

Displays:

* Complaint concentration by US state (choropleth map)
* Tabular state ranking

### Trends

* Monthly or yearly complaint volume over time
* Visual time-series analysis


## 📊 Data Sources

All data comes from official U.S. government sources:

### Vehicle Metadata

* **NHTSA vPIC API**

  * Decode VIN → Year/Make/Model
  * Get official model names

### Recalls

* **NHTSA Recalls API**

  * Endpoint: `recallsByVehicle`

### Complaints (Live)

* **NHTSA ODI Complaints API**

  * Endpoint: `complaintsByVehicle`

### Complaints (Offline Geographic Index)

* **ODI FLAT_CMPL Dataset**

  * Source: [https://www.nhtsa.gov/nhtsa-datasets-and-apis](https://www.nhtsa.gov/nhtsa-datasets-and-apis)
  * Used to build local SQLite index for state-level aggregation

> Offline indexing avoids API rate limits and missing location fields.



## 🧠 Architecture Overview

```text
Streamlit UI (app.py)
        │
        ▼
NHTSA Client (nhtsa_client.py)
        │
        ▼
NHTSA APIs (VIN Decode / Recalls / Complaints)
        │
        ▼
SQLite Cache Layer (storage.py)
        │
        ▼
Analytics Engine (analytics.py)
        │
        ▼
Search Engine (search.py)
        │
        ▼
Offline Geo Index (geo_state_counts.sqlite)
```

## 📁 Project Structure
```text

slp-vehicle-defects-mvp/
│
├── app/
│   ├── app.py              # Streamlit UI
│   ├── analytics.py        # Severity + pattern analysis
│   ├── nhtsa_client.py     # API client
│   ├── search.py           # Complaint keyword search
│   ├── storage.py          # SQLite cache
│   └── assets/
│       └── logo.png
│
├── data/
│   ├── FLAT_CMPL.txt               # Raw ODI dataset
│   └── geo_state_counts.sqlite    # Prebuilt geographic index
│
├── scripts/
│   └── build_geo_state_counts.py   # Builds geo index
│
├── requirements.txt
└── README.md

```

### Installation & Setup

### 1. Create Virtual Environment

```bash
python -m venv .venv
```

### Activate

Windows:

```bash
.venv\Scripts\activate
```

Mac/Linux:

```bash
source .venv/bin/activate
```

### 2️. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 3️. (Optional but Recommended) Build Geo Index

This enables **accurate state maps**.

#### Step A — Download ODI FLAT_CMPL Dataset

From:
[https://www.nhtsa.gov/nhtsa-datasets-and-apis](https://www.nhtsa.gov/nhtsa-datasets-and-apis)

Download and extract:

```
FLAT_CMPL.txt
```

Place into:

```
data/FLAT_CMPL.txt
```

#### Step B — Build SQLite Geo Index

```bash
python scripts/build_geo_state_counts.py
```
You should see:

Built geo index at: data/geo_state_counts.sqlite

### 4️⃣ Run The App

```bash
streamlit run app/app.py
```
## Recommended Usage Flow

1. Use VIN when available (best accuracy)
2. Enable **official model picker**
3. Review:

   * Overview → severity + case strength
   * Defect Patterns → component clusters
   * Geography → complaint concentration
   * Trends → time-based signals
   * Symptom Search → narrative evidence

---

##  Important Notes

### Why Some APIs Lack Location Data

The live NHTSA complaints endpoint often omits state fields.

This is why the system:

✔ Automatically falls back to offline ODI dataset
✔ Labels the data source clearly in UI
✔ Never fabricates geographic information

### Accuracy Guarantee

All displayed data comes from:

* NHTSA APIs
* Official ODI complaint datasets

No synthetic or guessed values are generated.


## 🚀 Future Enhancements

Potential upgrades:

* VIN-level geographic linking
* Attorney case scoring ML model
* Similar vehicle clustering
* Exportable PDF intake reports
* Recall defect text classification
* Multi-vehicle comparison dashboard

---

## 🏛 Built For

SLP Legal Intake Prototype
Demonstration of:

* Public safety data integration
* Legal intelligence tooling
* Data engineering + analytics pipeline
* Scalable architecture design

