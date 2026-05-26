"""
SEC EDGAR — Multi-Form Parser (copied for full-work-view)
This is a local copy of the original `form_d_companies.py` used by the aggregator.
"""

import requests, time, json, csv, re, argparse, sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict
try:
    from bs4 import BeautifulSoup
except Exception:
    BeautifulSoup = None

def log(msg, level="info", show_time=True):
    icons = {"info":"ℹ️","success":"✅","warning":"⚠️","error":"❌","debug":"🔍"}
    ts = f"{datetime.now().strftime('%H:%M:%S')} " if show_time else ""
    print(f"{ts}{icons.get(level,'•')} {msg}")

def format_eta(rem, speed):
    if speed<=0: return "∞"
    s = rem/speed
    return f"~{int(s)} сек" if s<60 else f"~{int(s/60)} мин" if s<3600 else f"~{s/3600:.1f} ч"

class Timer:
    def __init__(self, l=""): self.l, self.t = l, time.time()
    def __enter__(self): return self
    def __exit__(self, *a): log(f"⏱️ [{self.l}] Завершено за {self._fmt(time.time()-self.t)}")
    def _fmt(self, s): return f"{s:.1f} сек" if s<60 else f"{s/60:.1f} мин" if s<3600 else f"{s/3600:.2f} ч"

SUPPORTED_FORMS = {"D": "Form D", "C": "Form C", "A": "Form 1-A"}
TARGET_INDUSTRIES_D = [
    "Technology", "Computers", "Internet", "Telecommunications", "Other Technology",
    "Banking & Financial Services", "Insurance", "Investing",
    "Health Care", "Biotechnology", "Other Health Care", "Hospitals & Physicians",
    "Retailing", "Business Services", "Energy Conservation", "Other Energy",
    "Other Real Estate", "Other",
]

INDUSTRY_KEYWORDS = {
    "software": ["software", "SaaS", "platform", "mobile app", "web application", "cloud computing", "API", "artificial intelligence", "machine learning", "AI"],
    "fintech": ["fintech", "payment processing", "digital banking", "neobank"],
    "healthtech": ["digital health", "telehealth", "telemedicine", "EHR", "EMR", "healthcare platform"],
    "retail_proptech": ["proptech", "real estate technology", "smart home", "logistics platform"],
}

HEADERS = {"User-Agent":"yours","Accept":"application/json, text/xml, */*","Accept-Encoding":"gzip, deflate"}
PAGE_SIZE = 100
MAX_PAGES = 40
CHUNK_DAYS = 1

API_DELAY = 1.5
MAX_RETRIES = 3
BACKOFF_FACTOR = 2
OFFSET_LIMIT = 1000

def build_query(kw, op="OR"):
    return f" {op} ".join(f'"{k}"' if " " in k and not k.startswith('"') else k for k in kw if k.strip())

def search_api_with_retry(forms, start, end, off=0, q=None, verbose=False):
    params = {"dateRange":"custom","startdt":start,"enddt":end,"from":off,"size":PAGE_SIZE,"forms":",".join(forms)}
    if q: params["q"] = q
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://efts.sec.gov/LATEST/search-index", params=params, headers=HEADERS, timeout=25)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code in (429, 500, 502, 503, 504):
                wait = API_DELAY * (BACKOFF_FACTOR ** attempt)
                time.sleep(wait)
                last_error = resp
                continue
            else:
                return None
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(API_DELAY * (BACKOFF_FACTOR ** attempt))
                continue
            return None
    return None

def extract_hit(hit):
    s = hit.get("_source", {})
    aid = hit.get("_id","")
    file_num_raw = s.get("file_num", "")
    if isinstance(file_num_raw, list) and len(file_num_raw) > 0:
        file_num_clean = str(file_num_raw[0]).strip()
    else:
        file_num_clean = str(file_num_raw).strip() if file_num_raw else ""
    return {
        "company_name": s.get("entity_name") or s.get("company_name") or "",
        "cik": s.get("cik","") or aid.replace("-","")[:10].lstrip("0"),
        "accession": aid,
        "form_type": s.get("form_type","D"),
        "file_date": s.get("file_date",""),
        "period": s.get("period_of_report",""),
        "file_num": file_num_clean,
        "industry_group": "",
        "offering_amount": None,
        "sold_amount": None,
        "keywords_found": [],
    }

def fetch_all(forms, start, end, kw_q=None, min_d=500_000, min_ca=100_000, max_amt=20_000_000, ind_d=None, kw_list=None, keep_all=False, show_reasons=False, verbose=False):
    res, cur = [], datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while cur < end_dt:
        nxt = min(cur + timedelta(days=CHUNK_DAYS), end_dt)
        s_str, e_str = cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")
        off = 0
        while True:
            data = search_api_with_retry(forms, s_str, e_str, off, kw_q, verbose)
            if not data:
                break
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break
            for h in hits:
                res.append(extract_hit(h))
            if len(hits) < PAGE_SIZE:
                break
            off += PAGE_SIZE
        cur = nxt
    return res

if __name__ == "__main__":
    print("This module is intended to be imported by the Streamlit app.")
"""
SEC EDGAR — Multi-Form Parser (copied for full-work-view)
This is a local copy of the original `form_d_companies.py` used by the aggregator.
"""

import requests, time, json, csv, re, argparse, sys
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from bs4 import BeautifulSoup

def log(msg, level="info", show_time=True):
    icons = {"info":"ℹ️","success":"✅","warning":"⚠️","error":"❌","debug":"🔍"}
    ts = f"{datetime.now().strftime('%H:%M:%S')} " if show_time else ""
    print(f"{ts}{icons.get(level,'•')} {msg}")

def format_eta(rem, speed):
    if speed<=0: return "∞"
    s = rem/speed
    return f"~{int(s)} сек" if s<60 else f"~{int(s/60)} мин" if s<3600 else f"~{s/3600:.1f} ч"

class Timer:
    def __init__(self, l=""): self.l, self.t = l, time.time()
    def __enter__(self): return self
    def __exit__(self, *a): log(f"⏱️ [{self.l}] Завершено за {self._fmt(time.time()-self.t)}")
    def _fmt(self, s): return f"{s:.1f} сек" if s<60 else f"{s/60:.1f} мин" if s<3600 else f"{s/3600:.2f} ч"

SUPPORTED_FORMS = {"D": "Form D", "C": "Form C", "A": "Form 1-A"}
TARGET_INDUSTRIES_D = [
    "Technology", "Computers", "Internet", "Telecommunications", "Other Technology",
    "Banking & Financial Services", "Insurance", "Investing",
    "Health Care", "Biotechnology", "Other Health Care", "Hospitals & Physicians",
    "Retailing", "Business Services", "Energy Conservation", "Other Energy",
    "Other Real Estate", "Other",
]

INDUSTRY_KEYWORDS = {
    "software": ["software", "SaaS", "platform", "mobile app", "web application", "cloud computing", "API", "artificial intelligence", "machine learning", "AI"],
    "fintech": ["fintech", "payment processing", "digital banking", "neobank"],
    "healthtech": ["digital health", "telehealth", "telemedicine", "EHR", "EMR", "healthcare platform"],
    "retail_proptech": ["proptech", "real estate technology", "smart home", "logistics platform"],
}

HEADERS = {"User-Agent":"yours","Accept":"application/json, text/xml, */*","Accept-Encoding":"gzip, deflate"}
PAGE_SIZE = 100
MAX_PAGES = 40
CHUNK_DAYS = 1

API_DELAY = 1.5
MAX_RETRIES = 3
BACKOFF_FACTOR = 2
OFFSET_LIMIT = 1000

def build_query(kw, op="OR"):
    return f" {op} ".join(f'"{k}"' if " " in k and not k.startswith('"') else k for k in kw if k.strip())

def search_api_with_retry(forms, start, end, off=0, q=None, verbose=False):
    params = {"dateRange":"custom","startdt":start,"enddt":end,"from":off,"size":PAGE_SIZE,"forms":",".join(forms)}
    if q: params["q"] = q
    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get("https://efts.sec.gov/LATEST/search-index", params=params, headers=HEADERS, timeout=25)
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code in (429, 500, 502, 503, 504):
                wait = API_DELAY * (BACKOFF_FACTOR ** attempt)
                time.sleep(wait)
                last_error = resp
                continue
            else:
                return None
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                time.sleep(API_DELAY * (BACKOFF_FACTOR ** attempt))
                continue
            return None
    return None

def extract_hit(hit):
    s = hit.get("_source", {})
    aid = hit.get("_id","")
    file_num_raw = s.get("file_num", "")
    if isinstance(file_num_raw, list) and len(file_num_raw) > 0:
        file_num_clean = str(file_num_raw[0]).strip()
    else:
        file_num_clean = str(file_num_raw).strip() if file_num_raw else ""
    return {
        "company_name": s.get("entity_name") or s.get("company_name") or "",
        "cik": s.get("cik","") or aid.replace("-","")[:10].lstrip("0"),
        "accession": aid,
        "form_type": s.get("form_type","D"),
        "file_date": s.get("file_date",""),
        "period": s.get("period_of_report",""),
        "file_num": file_num_clean,
        "industry_group": "",
        "offering_amount": None,
        "sold_amount": None,
        "keywords_found": [],
    }

def fetch_all(forms, start, end, kw_q=None, min_d=500_000, min_ca=100_000, max_amt=20_000_000, ind_d=None, kw_list=None, keep_all=False, show_reasons=False, verbose=False):
    res, cur = [], datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    while cur < end_dt:
        nxt = min(cur + timedelta(days=CHUNK_DAYS), end_dt)
        s_str, e_str = cur.strftime("%Y-%m-%d"), nxt.strftime("%Y-%m-%d")
        off = 0
        while True:
            data = search_api_with_retry(forms, s_str, e_str, off, kw_q, verbose)
            if not data:
                break
            hits = data.get("hits", {}).get("hits", [])
            if not hits:
                break
            for h in hits:
                res.append(extract_hit(h))
            if len(hits) < PAGE_SIZE:
                break
            off += PAGE_SIZE
        cur = nxt
    return res

if __name__ == "__main__":
    print("This module is intended to be imported by the Streamlit app.")
