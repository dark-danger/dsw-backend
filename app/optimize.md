Optimize the existing Faculty Portal for PERFORMANCE ONLY.

### STACK

Frontend: existing frontend — DO NOT CHANGE THE UI/design.

Backend:

* FastAPI

Database:

* Supabase PostgreSQL

The application is currently extremely slow.

Observed problems:

* Login/authentication can take around 1 minute.
* Dashboard/data loading can take 1–2 minutes.
* Delete Task is very slow.
* Add Faculty is very slow.
* Other CRUD operations are also slow.

I want you to diagnose and FIX the actual performance bottleneck.

DO NOT simply add loading animations.

---

## STEP 1 — TRACE EVERY SLOW REQUEST

Inspect the complete request flow.

For login:

```text
Frontend
↓
FastAPI
↓
Supabase/Auth
↓
Supabase PostgreSQL
↓
FastAPI response
↓
Frontend
```

Find exactly where the delay occurs.

Add temporary timing logs such as:

```text
LOGIN START
Auth request: 300 ms
User query: 120 ms
Profile query: 80 ms
Tasks query: 150 ms
TOTAL: 650 ms
```

Do the same for:

```text
Dashboard
Task creation
Task deletion
Faculty creation
Faculty loading
Task loading
Submission loading
Review loading
```

After identifying the bottleneck, fix it and remove unnecessary debug logging.

---

# STEP 2 — SUPABASE DATABASE OPTIMIZATION

Inspect the Supabase PostgreSQL schema and ALL frequently used queries.

Look for:

* missing indexes
* N+1 queries
* repeated SELECT queries
* SELECT * unnecessarily
* queries inside loops
* fetching entire tables
* unnecessary joins
* repeated user/profile lookups
* repeated faculty lookups
* repeated task lookups
* unnecessary COUNT queries

Do NOT blindly add indexes.

Add indexes only for columns actually used frequently in:

```text
WHERE
JOIN
ORDER BY
```

Especially inspect relationships involving:

```text
user_id
faculty_id
task_id
submission_id
email
created_at
status
```

Use the actual existing schema rather than assuming these columns exist.

---

# STEP 3 — SUPABASE CONNECTIONS

This is VERY IMPORTANT.

Inspect how FastAPI communicates with Supabase.

Do NOT create a new Supabase client repeatedly for every small operation if the current implementation can reuse a client safely.

Check for code patterns like:

```python
create_client(...)
```

inside every request/function.

If this is happening unnecessarily, restructure it so the client/connection handling is efficient and safe.

Do NOT expose the Supabase service-role key to the frontend.

Keep all privileged database operations server-side.

---

# STEP 4 — AUTHENTICATION

Login taking ~1 minute is the highest priority.

Inspect:

```text
login
→ Supabase authentication
→ token validation
→ profile lookup
→ role lookup
→ faculty lookup
→ dashboard requests
```

Find whether the frontend is making multiple sequential requests after login.

For example:

```text
login
↓
get current user
↓
get profile
↓
get role
↓
get faculty
↓
get tasks
↓
get submissions
```

If several of these are redundant or independent, optimize them.

Where appropriate, return the required initial user/session information in one efficient backend response.

Do NOT weaken authentication.

Do NOT remove:

* authentication
* authorization
* role checks
* password security
* JWT/session validation
* Supabase security

---

# STEP 5 — FRONTEND REQUESTS

Inspect the frontend for duplicate API requests.

Look for:

```text
useEffect
component mount
route change
state change
```

causing the same endpoint to execute multiple times.

Also check whether React development mode / StrictMode is causing duplicate requests during development.

Do not disable security or production functionality merely to hide duplicate requests.

---

# STEP 6 — DASHBOARD

The dashboard should NOT reload the entire database unnecessarily.

Bad:

```text
Delete Task
↓
Reload all faculties
↓
Reload all tasks
↓
Reload all submissions
↓
Reload dashboard
```

Better:

```text
Delete Task
↓
DELETE /tasks/{id}
↓
Update task list locally
```

Similarly:

```text
Add Faculty
↓
CREATE faculty
↓
Add returned faculty to current list
```

instead of reloading the entire application.

Preserve existing functionality.

---

# STEP 7 — PARALLEL API REQUESTS

If the frontend currently does:

```text
GET faculties
wait
GET tasks
wait
GET submissions
wait
GET reviews
```

and these requests are independent, make them concurrent where safe:

```text
GET faculties ─┐
GET tasks ──────┤
GET submissions ┤
GET reviews ────┘
```

Use `Promise.all()` or the appropriate existing architecture.

Do not parallelize requests that depend on each other's results.

---

# STEP 8 — FASTAPI

Inspect all FastAPI endpoints.

Check for:

* blocking operations
* unnecessary async/sync conversions
* repeated database calls
* expensive serialization
* unnecessary API calls
* sequential independent queries

Do NOT simply convert every function from:

```python
def
```

to:

```python
async def
```

Async should only be used where it actually helps the current stack.

---

# STEP 9 — QUERY OPTIMIZATION

Replace inefficient patterns such as:

```text
fetch all rows
↓
Python filters rows
```

with database-side filtering where appropriate:

```text
SELECT required rows
WHERE ...
```

Do not fetch thousands of records when the page only needs 20–50.

Implement server-side pagination for large datasets where appropriate.

Example:

```text
GET /tasks?page=1&limit=20
```

---

# STEP 10 — SUPABASE RLS

Inspect Supabase Row Level Security policies.

Poorly designed RLS policies can cause unnecessary database work.

Check whether policies contain expensive repeated queries.

Optimize RLS policies where safe.

IMPORTANT:

Do NOT disable RLS just to improve performance.

Security must remain intact.

---

# STEP 11 — CACHING

Identify data that does not change frequently.

Potential candidates:

* faculty list
* static configuration
* current profile
* task metadata

Use appropriate frontend/backend caching only where safe.

Do not cache sensitive authentication information insecurely.

---

# STEP 12 — DELETE TASK

Optimize the existing delete flow.

It should ideally be:

```text
Frontend
↓
DELETE /task/{id}
↓
FastAPI validates permission
↓
Supabase DELETE
↓
return success
↓
frontend removes task from local state
```

Do NOT reload the entire dashboard after deletion.

Also inspect whether deleting a task triggers unnecessary cascading queries.

---

# STEP 13 — ADD FACULTY

Optimize the existing faculty creation flow.

It should be:

```text
Frontend
↓
POST /faculty
↓
validation
↓
Supabase INSERT
↓
return created faculty
↓
frontend updates list
```

Do not reload every table after creating one faculty.

---

# STEP 14 — DATABASE INDEXES

Inspect actual Supabase tables and recommend the indexes required by real queries.

Before adding indexes, verify existing indexes.

Do not create duplicate indexes.

Provide the SQL migration separately so I know exactly what was changed.

---

# PERFORMANCE TARGET

Do not fake numbers.

Measure actual performance before and after.

Aim for approximately:

```text
Login:              ~1–2 sec
Normal CRUD:        <1 sec
Dashboard:          ~1–2 sec
Simple DB query:    <200–500 ms
```

Actual performance depends on network/server/database conditions.

---

# VERY IMPORTANT — DO NOT CHANGE ANYTHING ELSE

Do NOT:

* redesign UI
* change colors
* change fonts
* change layouts
* change routes unnecessarily
* change login behavior
* remove authentication
* remove authorization
* disable RLS
* expose Supabase service-role key
* replace Supabase
* replace FastAPI
* rewrite the whole application
* change business logic
* remove features

Make the smallest possible changes.

---

# FINAL REPORT

After optimization, provide:

### Root causes

List the actual reasons for the slowness.

### Files changed

Give exact filenames.

### Database changes

List every index/query/RLS change.

### Before vs After

Use real measurements:

```text
Login:       X sec → Y sec
Dashboard:   X sec → Y sec
Delete:      X sec → Y sec
Add Faculty: X sec → Y sec
```

If possible, identify the slowest API endpoint and slowest database query.

**Do not claim the site is faster unless you actually measured it.**

Again: PERFORMANCE OPTIMIZATION ONLY. Preserve the existing portal exactly.
