---
name: tdd
description: Red -> green test-driven workflow for Moron Fitness, and how the pytest suite is laid out (fixtures, builders, frozen clock, FakeClaude). Use for any feature, bug fix, or behavior change in this repo — before editing app code — and whenever writing or fixing tests.
---

# Test-driven development in Moron Fitness

Every behavior change goes **test first → watch it fail → change code → whole suite green**.
The suite runs in ~3 seconds, so run it constantly.

```bash
./run test                 # whole suite (same as .venv/bin/pytest)
./run test -x --lf         # rerun last failures, stop at the first
./run test -k recap        # tests matching a name
./run test tests/unit      # one layer
```

`./run deploy` runs the suite first and refuses to deploy on a failure
(`./run deploy --skip-tests` overrides — say why if you use it).

## The cycle

1. **Write the test(s) first.** Pick the layer (below), use builders + `clock`, assert on
   the behavior the user would notice. One behavior per test; the test name states it
   ("late evening meal lands on its local day", not "test_rollup_2").
2. **Run it and watch it go red — for the right reason.** The failure should be an
   assertion about the missing/wrong behavior. An `ImportError` for a function that
   doesn't exist yet is fine; a fixture error, typo, or wrong selector is not — fix the
   test until it fails on the assertion. Show the red output to the user.
3. **Make the smallest code change that turns it green.** Don't add behavior no test asks for.
4. **Run the whole suite**, not just the new test. All green (xfails stay xfail) before
   you're done. Then refactor if needed, staying green.
5. **Show the green run** in your summary.

**Bug reports:** first write a test that reproduces exactly what was reported (same
times, same data shape — e.g. a meal at 9pm Eastern, a question asked on a Sunday). It must
fail against the current code. Then fix. That test is the regression guard forever.

**Bugs you find but aren't fixing yet:** `@pytest.mark.xfail(reason="BUG-n: ...")`.
`xfail_strict` is on, so the moment it's fixed the run fails until you delete the marker.

**If a test fails and you think the test is wrong**, say so and explain before changing it —
never weaken an assertion just to get green.

## Layout — where a test goes

| Folder | For | Uses |
|---|---|---|
| `tests/unit/` | Pure functions: week/period math, `week_summary` on hand-built rollups, timezone helpers, parsing | No DB (except `claude` for meal_ai) |
| `tests/integration/` | Code that reads/writes the DB but isn't a page: `daily_rollup`, `weight_progress`, coach tools, coach context, recap | `user`, `db`, builders, `clock`, `claude` |
| `tests/routes/` | Anything done through a page or form: status, redirects, rows written, what renders | `client`, `soup()`, builders |

Cross-cutting route tests that new code must keep passing:
- `routes/test_access.py` — every route requires login; every `<int:id>` route 404s for
  another user's record. **Adding a route with an id? Add a row to `OWNED`.**
- `routes/test_forms.py` — every POST form that creates/updates has `guard-double-submit`
  (deletes, `/achieve`, and fetch-driven forms are exempt by rule, listed in the file).

If logic is buried in a route and needs many cases, extract it to a pure function and unit
test it (as `progress.exercise_week_status` was pulled out of the dashboard route), with
one route test proving it's wired up.

## Fixtures (`tests/conftest.py`)

- `app` — fresh app per test; temp SQLite DB and temp instance dir (photos go there, never
  to the real `instance/`). Runs inside an app context, so `Model.query` just works.
- `user`, `other_user` — two accounts (password `pw`).
- `client` — logged in as `user`. `anon_client` — logged out.
- `clock` — `clock.at("2026-09-30 21:30")` freezes *everything* (`datetime.now`, `utcnow`,
  `date.today`) at that **US Eastern** time; date-only means noon. Call again to move time.
  Never depend on the real today. The `client` re-logs-in when the clock moves (session
  cookies signed "in the future" are rejected).
- `claude` — scripted fake Anthropic client (`tests/fakes.py`):
  `claude.replies_text("...")`, `claude.calls_tool("log_meal", {...})`,
  `claude.saves_recap(headline, recap)`, `claude.fails()`. Each queued item answers one API
  call, in order. Inspect `claude.calls[i]` (`system`, `messages`, `tools`, `tool_choice`)
  and `claude.prompt_text()`. Unqueued calls fail the test.
- **Real Anthropic calls are blocked** in every test that doesn't use `claude`.
- `soup(response)` — BeautifulSoup the response; find things by id/class/action rather than
  slicing HTML strings.

## Builders (`tests/builders.py`)

`SUNDAY` (2026-09-27) and `day(n)` anchor dates — weeks run Sun–Sat. `local_dt(d, "21:30")`
gives the naive-UTC timestamp for a local Eastern time. Row builders, all `(user, ...)` with
defaults: `make_period`, `log_weight`, `log_measurement`, `log_meal` (`time=` local, or
`at=` exact UTC), `log_drink`, `log_workout`, `make_goal`, `make_note`, `make_saved_meal`,
`make_chat`, `make_recap`. Pass only what the test is about. Add a builder rather than
constructing models inline in more than one test.

## What to test / not test

Test: rows written and their fields, numbers shown, redirects, which section something
renders in, what data/tools are sent to Claude, and the day-boundary edges this app keeps
hitting — evening Eastern after UTC midnight, Sunday as day 1, period start/end clipping,
DST (Nov 1 2026 is inside the Fall period).

Don't test: prompt wording, the quality of AI output, Bootstrap/CSS details, or exact
flash-message text beyond a distinctive word. Never call the real API.

## Keeping it fast and isolated

- Each test builds its own data; no shared state, any order works.
- Keep the whole suite under ~5s. Test user passwords use a 1-iteration hash for this reason.
- New dev-only packages go in `requirements-dev.txt` (never `requirements.txt` — it's what
  the server installs).
