import os
import re
import json
from typing import Optional, Any

import pandas as pd

# Defer optional imports (dotenv, openai) to runtime to avoid import-time errors when packages
# are not installed in the environment. load_api_client will import them when needed.

def load_api_client():
    try:
        from dotenv import load_dotenv as _load_dotenv
    except Exception:
        _load_dotenv = None

    try:
        from openai import OpenAI as _OpenAI
    except Exception:
        _OpenAI = None

    if _load_dotenv:
        _load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not found. Set it in your environment or .env file.")
    if _OpenAI is None:
        raise RuntimeError("openai package not available in the environment")
    return _OpenAI(api_key=api_key)

def build_prompt(company_name: str, cik: Optional[str]) -> str:
    prompt = f"""
You are an accuracy-focused data enrichment assistant. Use the web-search capability to find the public business contact details for the target company.

Target:
- Company name: {company_name}
"""
    if cik:
        prompt += f"- CIK: {cik}\n"
    prompt += """
Your task:
1. Find the official company LinkedIn page.
2. Find a publicly available company contact email address.
3. Find the official company website URL.

Required output:
Return ONLY valid JSON with the following fields:
{
  "linkedin": "LinkedIn company URL or null",
  "email": "public contact email or null",
  "website": "official website URL or null"
}
"""
    return prompt.strip()

def extract_json(text: str) -> dict:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {}

def extract_fallbacks(text: str) -> dict:
    result = {"linkedin": None, "email": None, "website": None}
    linkedin_match = re.search(r'https?://(?:www\.)?linkedin\.com/[A-Za-z0-9_/\-\?=&%]+', text)
    if linkedin_match:
        result["linkedin"] = linkedin_match.group(0).rstrip('.,;')
    email_match = re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', text)
    if email_match:
        result["email"] = email_match.group(0).rstrip('.,;')
    website_match = re.search(r'https?://(?:www\.)?[A-Za-z0-9.-]+\.[A-Za-z]{2,6}(?:/[A-Za-z0-9_\-./?=&%]*)?', text)
    if website_match:
        url = website_match.group(0).rstrip('.,;')
        if "linkedin.com" not in url:
            result["website"] = url
    return result

def normalize_company_name(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = name.strip()
    name = re.sub(r"\(CIK\s*\d+\)", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9\s]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name

def enrich_row(client: Any, company_name: str, cik: Optional[str] = None, verbose: bool = False) -> dict:
    prompt = build_prompt(company_name, cik)
    if verbose:
        print(f"\nEnriching: {company_name} | CIK={cik}")
    try:
        completion = client.chat.completions.create(
            model="gpt-4o-mini-search-preview",
            max_tokens=400,
            web_search_options={"user_location": {"type": "approximate", "approximate": {"country": "US"}}},
            messages=[
                {"role": "system", "content": "You must respond with valid JSON only, no additional text."},
                {"role": "user", "content": prompt}
            ]
        )
        content = completion.choices[0].message.content
    except Exception:
        # If the OpenAI client call fails, return empty enrichment fields
        return {"linkedin": None, "email": None, "website": None}
    data = extract_json(content)
    if not data:
        fallback = extract_fallbacks(content)
        data = {"linkedin": fallback.get("linkedin"), "email": fallback.get("email"), "website": fallback.get("website")}
    else:
        for field in ("linkedin", "email", "website"):
            if field in data and data[field] is not None:
                data[field] = str(data[field]).strip() or None
            else:
                data[field] = None
    return data

if __name__ == "__main__":
    print("form_d_enricher is a helper module for the Streamlit app.")
