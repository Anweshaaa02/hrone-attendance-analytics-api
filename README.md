# Employee Attendance & Analytics API

A REST API for employee management, attendance tracking, attendance regularization, and workforce analytics, built with **Python, FastAPI, and MongoDB**.

The application provides endpoints for employee records, punch-in and punch-out operations, attendance history, monthly employee analytics, department summaries, late-arrival leaderboards, and department attendance trends.

## Features

- **Employee Management:** Create and retrieve employee records.
- **Attendance Tracking:** Record employee punch-ins and punch-outs.
- **Attendance Regularization:** Update attendance records with a reason and audit history.
- **Monthly Analytics:** Calculate attendance, late arrivals, overtime, leave, and attendance percentages.
- **Department Analytics:** Generate department-level summaries and daily attendance trends.
- **Late-Arrival Leaderboard:** Rank employees by accumulated late minutes.
- **Database Indexing:** Use MongoDB indexes to support data integrity and query performance.
- **API Documentation:** Explore and test endpoints through Swagger UI.

## Tech Stack

- **Language:** Python 3.11+
- **API Framework:** FastAPI
- **Database:** MongoDB 6.0+
- **Database Driver:** PyMongo
- **API Documentation:** OpenAPI / Swagger UI

## Prerequisites

Before running the application, ensure you have:

- Python 3.11 or later installed.
- Access to a MongoDB 6.0+ database, either locally or through MongoDB Atlas.
- Git installed if cloning the repository.

## Project Setup

### 1. Clone the repository

```bash
git clone https://github.com/Anweshaaa02/hrone-attendance-analytics-api.git
cd hrone-attendance-analytics-api
```

### 2. Create and activate a virtual environment

**Windows — PowerShell**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure environment variables

Create a `.env` file in the project root directory and configure your MongoDB connection details:

```dotenv
MONGO_URI=your_mongodb_connection_string
MONGO_DB=attendance_db
```

Replace the example connection string with your own MongoDB URI. Use the database name expected by your configuration.

**Security:** Never commit `.env` or expose database credentials in your source code or public repository.

### 5. Start the application

From the project root directory, run:

```bash
uvicorn app.main:app --reload --port 8000
```

The API will be available at:

- **Base URL:** http://127.0.0.1:8000
- **Swagger UI:** http://127.0.0.1:8000/docs
- **OpenAPI schema:** http://127.0.0.1:8000/openapi.json
- **Health check:** http://127.0.0.1:8000/health

The application creates the configured MongoDB indexes during startup.

## Sample Data

The repository includes `sample_seed.py` and sample JSON data files for local testing.

The seed script populates the configured MongoDB database with sample employee and attendance records. Use it when you want to test the API with sample data instead of creating records manually.

Run the seed script from the project root:

```bash
python sample_seed.py
```

**Important:** Review the seed script and verify your `MONGO_URI` and `MONGO_DB` before executing it. The script clears the `employees` and `attendance_logs` collections before inserting sample records. Do not run it against a database containing data you need to preserve.

Sample data is intended for local development and testing.

## API Endpoints

The following endpoints are available in the application. Open Swagger UI at `/docs` to inspect request parameters, schemas, and responses.

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/health` | Check application and database readiness |
| POST | `/employees` | Create an employee |
| GET | `/employees` | Retrieve employee records |
| POST | `/attendance/punch-in` | Record a punch-in |
| POST | `/attendance/punch-out` | Record a punch-out |
| GET | `/attendance` | Retrieve attendance records |
| PATCH | `/attendance/{emp_code}/{date}` | Regularize an attendance record |
| GET | `/analytics/employees/{emp_code}/monthly` | Retrieve monthly employee analytics |
| GET | `/analytics/departments/summary` | Retrieve department summaries |
| GET | `/analytics/leaderboard/late` | Retrieve the late-arrival leaderboard |
| GET | `/analytics/departments/{department}/trend` | Retrieve department attendance trends |
| GET | `/admin/explain/{endpoint}` | Inspect MongoDB query execution plans |

## Implementation Notes

- API timestamps are represented as epoch milliseconds.
- MongoDB stores date-time values in UTC, while attendance dates and shift calculations follow Indian Standard Time (IST).
- Attendance calculations include work hours, late minutes, overtime, and half-day status.
- MongoDB indexes support uniqueness constraints and commonly used query patterns.
- Additional implementation decisions and review notes are documented in `DECISIONS.md` and `REVIEW.md`.

## Project Documentation

- `README.md` — Setup instructions and usage guide.
- `DECISIONS.md` — Design choices and implementation rationale.
- `REVIEW.md` — Review notes on starter-code defects and implementation changes.
- `requirements.txt` — Python dependencies.
- `sample_seed.py` — Script for loading sample data.

## License

This project was developed as part of an engineering assignment.
