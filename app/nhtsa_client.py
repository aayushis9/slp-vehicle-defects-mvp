import requests
from typing import Dict, Optional, List

VPIC_DECODEVINVALUES_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/decodevinvalues/{vin}"
VPIC_MODELS_FOR_MAKE_YEAR_URL = "https://vpic.nhtsa.dot.gov/api/vehicles/GetModelsForMakeYear/make/{make}/modelyear/{year}"

NHTSA_RECALLS_BY_VEHICLE_URL = "https://api.nhtsa.gov/recalls/recallsByVehicle"
NHTSA_COMPLAINTS_BY_VEHICLE_URL = "https://api.nhtsa.gov/complaints/complaintsByVehicle"


class NHTSAClient:
    def __init__(self, timeout_s: int = 25):
        self.timeout_s = timeout_s
        self.session = requests.Session()

    def decode_vin(self, vin: str) -> Dict[str, Optional[str]]:
        vin = (vin or "").strip()
        if not vin:
            return {"model_year": None, "make": None, "model": None}

        url = VPIC_DECODEVINVALUES_URL.format(vin=vin)
        r = self.session.get(url, params={"format": "json"}, timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()

        results = (data or {}).get("Results") or []
        row = results[0] if results else {}

        model_year = (row.get("ModelYear") or "").strip() or None
        make = (row.get("Make") or "").strip() or None
        model = (row.get("Model") or "").strip() or None

        return {"model_year": model_year, "make": make, "model": model}

    def get_models_for_make_year(self, make: str, model_year: int) -> List[str]:
        make = (make or "").strip()
        if not make:
            return []

        url = VPIC_MODELS_FOR_MAKE_YEAR_URL.format(make=make, year=int(model_year))
        r = self.session.get(url, params={"format": "json"}, timeout=self.timeout_s)
        r.raise_for_status()
        data = r.json()

        results = data.get("Results") or []
        models = sorted(
            {(x.get("Model_Name") or "").strip().upper() for x in results if isinstance(x, dict)}
        )
        return [m for m in models if m]

    def get_recalls_by_vehicle(self, model_year: int, make: str, model: str) -> dict:
        params = {"modelYear": model_year, "make": make, "model": model}
        try:
            r = self.session.get(NHTSA_RECALLS_BY_VEHICLE_URL, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"Count": 0, "Message": "Recalls lookup failed", "Results": [], "error": str(e)}

    def get_complaints_by_vehicle(self, model_year: int, make: str, model: str) -> dict:
        params = {"modelYear": model_year, "make": make, "model": model}
        try:
            r = self.session.get(NHTSA_COMPLAINTS_BY_VEHICLE_URL, params=params, timeout=self.timeout_s)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            return {"Count": 0, "Message": "Complaints lookup failed", "Results": [], "error": str(e)}
