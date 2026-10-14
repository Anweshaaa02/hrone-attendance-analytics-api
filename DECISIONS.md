# DECISIONS.md

1. **Indexes.** I created a unique index on `employees.emp_code` to enforce employee identity, and a unique compound index on `attendance_logs (emp_code, date)` to enforce one attendance record per employee per attendance day and make simultaneous punch-ins safe. Additional indexes support attendance date ordering, employee punch-out lookup, monthly employee queries, late-minute filtering, and department/join-date headcount queries. I did not add a separate `status` index because it was not justified by the primary query patterns and would add write cost.

2. **Punch-in race.** Both requests may reach the insert, but the unique `(emp_code, date)` index allows only one insert. The winner returns 201; the other gets `DuplicateKeyError`, translated to 409. A pre-check alone would not be safe.

3. **Ties.** The leaderboard uses `$rank` on total late minutes, then filters `rank <= limit`. Employees tied at the cutoff are all returned; the next rank is skipped. Rows are finally ordered by total minutes descending and employee code ascending.

4. **Headcount.** Department summary starts from eligible employees, not attendance logs, then uses `$lookup` with `preserveNullAndEmptyArrays`. Employees with no logs therefore still contribute to headcount.

5. **100x scale.** I would validate query plans and workload with production-like data, then consider pre-aggregated daily summaries and background refreshes for expensive analytics while preserving the raw attendance log as the source of truth.
