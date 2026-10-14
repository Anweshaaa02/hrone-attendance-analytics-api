# Starter code review

| # | Where (function / line) | What is wrong | How you'd notice it (test, input, or symptom) | How you fixed it |
|---|---|---|---|---|
| 1 | `health` | Always returns 200 without checking MongoDB. | Stop MongoDB and call `/health`. | Ping MongoDB and return 503 on failure. |
| 2 | `create_employee` | Check-then-insert is race-prone; no unique index; naive local creation timestamp. | Send concurrent creates for the same code. | Unique index, catch `DuplicateKeyError`, store UTC timestamp. |
| 3 | `list_employees` | `skip=page*page_size` skips the first page; total ignores filters. | Compare pages and filter by department. | Use `(page-1)*page_size` and count the filtered query. |
| 4 | `punch_in` | Unknown employee can crash; local timestamp/timezone; status/time validation incomplete; check-then-insert race; leaks `id`. | Unknown code, bad timestamp, simultaneous requests. | Validate employee and input, calculate IST attendance date, unique natural-key index, serialize contract fields only. |
| 5 | `compute_late_minutes` | Uses the punch-in date's wall clock without explicit IST/attendance-day handling. | Overnight shift and grace-boundary tests. | Compute against IST shift start for the resolved attendance date and apply strict >10-minute rule. |
| 6 | `compute_work_hours` | Python `round` does not guarantee half-up rounding. | Values exactly at rounding boundaries. | Use `Decimal` with `ROUND_HALF_UP`. |
| 7 | `compute_overtime` | Does not correctly handle overnight shift end and applies no 30-minute minimum. | Overnight shift and 29/30-minute tests. | Resolve shift end on the proper day and apply the 30-minute threshold. |
| 8 | `list_attendance` | Loads all records into Python, sorts incompletely, and returns MongoDB IDs / raw datetimes. | Large dataset, same-date rows, inspect response. | Count in MongoDB; sort, skip and limit in MongoDB; serialize timestamps as epoch milliseconds. |
| 9 | Missing endpoints | Punch-out, regularization, four analytics endpoints and explain endpoint were not implemented. | Contract endpoint checks return 404. | Implemented in `app/main.py`. |

Items considered but not defects: using synchronous PyMongo is acceptable for this small synchronous FastAPI service; `history` and `half_day` can be absent in legacy documents and are treated as empty/false. The assignment requires no authentication, and does not require an endpoint to create ABSENT or LEAVE records.
