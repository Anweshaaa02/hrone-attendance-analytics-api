# Employee Attendance & Analytics API

FastAPI + PyMongo implementation for the HROne engineering assignment.

## Run

Python 3.11+ and MongoDB 6.0+ are required.

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
# Set MONGO_URI and MONGO_DB in your shell, then:
uvicorn app.main:app --port 8000
```

The application creates indexes at startup. `GET /health` checks MongoDB readiness. The optional sample JSON files can be loaded into the configured database for local testing; do not use sample data to conclude the hidden analytics tests will pass.

## Implementation notes

All API instants are epoch milliseconds; MongoDB stores UTC BSON dates. Attendance dates and shift times follow IST. Analytics summarize stored derived values. `REVIEW.md` records starter defects and `DECISIONS.md` documents design choices.

## Known limitations to verify before submission

Run the endpoint and edge-case tests against MongoDB 6.0+ before relying on this submission. In particular, validate the trend pipeline and explain plans against the exact server version and dataset, and review all results against the OpenAPI contract.
