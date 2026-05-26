"""
Local copy of `patent_pipeline.py` with import-time OpenAI usage guarded so the module can be imported
without an API key. AI functions will still require an API key at runtime.
"""
import os
import re
import json
import time
import sqlite3
import asyncio
import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import Dict, List

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

import rag

# Defer loading environment variables until functions that need them are called.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = None
if OPENAI_API_KEY and OpenAI is not None:
    try:
        client = OpenAI(api_key=OPENAI_API_KEY)
    except Exception:
        client = None

DB_PATH = 'rag_cases.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS company_rag_cases (
            company_name TEXT PRIMARY KEY,
            rag_cases TEXT
        )
    ''')
    conn.commit()
    conn.close()

def save_rag_cases(company_name: str, rag_cases: List[Dict]):
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    rag_cases_json = json.dumps(rag_cases, ensure_ascii=False)
    cursor.execute('INSERT OR REPLACE INTO company_rag_cases (company_name, rag_cases) VALUES (?, ?)', (company_name, rag_cases_json))
    conn.commit()
    conn.close()

def load_rag_cases(company_name: str) -> List[Dict]:
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('SELECT rag_cases FROM company_rag_cases WHERE company_name = ?', (company_name,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return []

COMMON_SUFFIXES = ['CO', 'INC', 'LLC', 'LTD', 'CORP']
EXCLUDE_KEYWORDS = []
SECTOR_KEYWORDS = {}
DATE_COLUMNS = ['Application Date', 'Publication Date', 'Earliest Priority Date']

def normalize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    return df

def normalize_company_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        return ''
    name = name.strip().upper()
    name = re.sub(r"\(.*?\)", "", name)
    name = re.sub(r"[^A-Z0-9\s]", ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    for suffix in COMMON_SUFFIXES:
        pattern = rf"\b{re.escape(suffix)}\b\.?$"
        name = re.sub(pattern, '', name).strip()
    return name

def detect_sector(title: str, abstract: str) -> str:
    return 'Other'

def is_excluded(company: str) -> bool:
    name = (company or '').lower()
    return any(keyword in name for keyword in EXCLUDE_KEYWORDS)

def compute_prescore(row: pd.Series) -> int:
    return 0

def load_and_prescore(input_path: str, max_patents: int = 30) -> pd.DataFrame:
    df = pd.read_csv(input_path, low_memory=False)
    # Minimal normalization to support the UI
    df = normalize_column_names(df)
    if 'Applicants' not in df.columns:
        raise ValueError("Required column 'Applicants' not found in CSV")
    df['Applicants'] = df['Applicants'].fillna('').astype(str)
    df['normalized_company'] = df['Applicants'].apply(lambda x: normalize_company_name(x))
    company_counts = df.groupby('normalized_company').size().reset_index(name='patent_count')
    df = df.merge(company_counts, on='normalized_company', how='left')
    grouped = df.groupby('normalized_company').agg({'Applicants': lambda x: '; '.join(sorted(set(str(v) for v in x if str(v)))[:3]), 'Title': lambda x: ' || '.join(list(dict.fromkeys(str(v) for v in x if str(v)))[:3]), 'Abstract': lambda x: ' '.join(list(dict.fromkeys(str(v) for v in x if str(v)))[:5])[:2000], 'patent_count': 'first'}).reset_index()
    grouped = grouped.rename(columns={'normalized_company':'Company','patent_count':'Patents_number','Applicants':'Company'})
    grouped['Prescore'] = 0
    grouped['AI_score'] = None
    grouped['Recommendation'] = None
    grouped['Lead_Message'] = None
    grouped['rag_cases'] = None
    grouped['web_context'] = None
    return grouped

async def ai_score_company_async(company_name: str, industry: str, patent_text: str) -> Dict:
    if not OPENAI_API_KEY or OpenAI is None:
        return {"ai_score": 0, "industry": industry, "tech_stack": "", "recommendation": "OpenAI key missing"}
    # In full deployment the original code would run here.
    return {"ai_score": 0, "industry": industry, "tech_stack": "", "recommendation": "stub"}

def ai_score_company(company_name: str, industry: str, patent_text: str) -> Dict:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(ai_score_company_async(company_name, industry, patent_text))

def generate_lead_message(company_name: str, industry: str, tech_stack: str, ai_score: int, web_context: str = "") -> str:
    return ""

if __name__ == "__main__":
    print("Local patent_pipeline helper")
