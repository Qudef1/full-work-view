# Full Work View

This folder contains a self-contained Streamlit aggregator app combining HeyReach, SEC EDGAR, and Patent viewers.

Run locally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Environment variables (put real values into `.env`):

- `OPENAI_API_KEY` — required for enrichment/scoring features
- `HEYREACH_API_KEY` — HeyReach API key for inbox extraction
- `HEYREACH_ACCOUNTS` — optional JSON array of account objects
