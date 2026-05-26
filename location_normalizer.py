#!/usr/bin/env python3
"""
Local copy of location_normalizer used by the HeyReach UI.
"""
from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Set
import pandas as pd

COUNTRIES: Dict[str, str] = {
    "united states": "US", "usa": "US", "us": "US", "america": "US",
    "united kingdom": "GB", "uk": "GB", "great britain": "GB",
    "australia": "AU", "canada": "CA", "germany": "DE", "france": "FR",
}

CITY_COUNTRY_MAP = {"sydney": "AU", "melbourne": "AU", "new york city": "US", "london": "GB"}

def normalize_locations_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    def _norm(loc):
        if not isinstance(loc, str):
            return {"country_code":"","country_name":"","region":"","city":"","location_status":"unknown"}
        t = loc.lower()
        for city, cc in CITY_COUNTRY_MAP.items():
            if city in t:
                return {"country_code":cc, "country_name": city.title(), "region":"", "city":city.title(), "location_status":"local"}
        for name, cc in COUNTRIES.items():
            if name in t:
                return {"country_code":cc, "country_name": name.title(), "region":"", "city":"", "location_status":"local"}
        return {"country_code":"","country_name":"","region":"","city":"","location_status":"unknown"}
    rows = df.get("lead_location", pd.Series([None]*len(df)))
    out = rows.apply(lambda x: _norm(x))
    out_df = pd.DataFrame(out.tolist(), index=df.index)
    return pd.concat([df, out_df], axis=1)

if __name__ == "__main__":
    print("location_normalizer helper")
