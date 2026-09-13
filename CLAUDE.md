# CLAUDE.md — Moron Fitness

Personal health & fitness tracker for the user and a friend or two. Tracks weight, body
fat %, body measurements, meals (calories/protein/carbs/fat), exercise, and goals, with
an in-app AI coach chat that has read access to all logged data. Designed as a phone
web app (PWA-installable) that's also just a normal web page.

Production URL (planned): **https://moron.bigpour.app**

Sibling project: [vibe-split](../vibe-split) (`split.bigpour.app`) — same server, same
stack, same conventions. This app follows its patterns deliberately so both are easy to
maintain together.

---

## Architecture

```
Browser (phone or desktop)
  │
  ▼ HTTPS :443
Nginx  (reverse proxy, SSL termination, shares the box with vibe-split)
  │
  ▼ HTTP 127.0.0.1:5003
Gunicorn  (2 gevent workers)
  │
  ▼ WSGI
Flask app  (wsgi.py → app/__init__.py)
  │
  ├── SQLite  (instance/moronfitness.db)
  └── Anthropic API  (meal nutrition parsing + coach chat)
```

**Stack:**
- Python / Flask 3.x + SQLAlchemy (ORM) + SQLite
- Gunicorn + gevent workers, bound to 127.0.0.1:5003 (vibe-split uses 5002 on this box)
- Nginx on port 443 with Let's Encrypt cert, same box as vibe-split
- Systemd process manager
- Bootstrap 5.3 + Jinja2 templates (server-rendered, minimal JS)
- PWA manifest + apple-mobile-web-app meta tags so it installs to a phone home screen;
  no service worker / offline support (not needed — it's always used online)

---

## Key Files

| File | Purpose |
|------|---------|
| `wsgi.py` | Gunicorn entry point — `application = create_app()` |
| `app/__init__.py` | Flask app factory, config, login/logout, dashboard route |
| `app/models.py` | All SQLAlchemy models |
| `app/meal_ai.py` | Claude Vision + text nutrition estimation for meals |
| `app/ai_coach.py` | AI coach: builds a context summary from logged data, calls Claude |
| `app/blueprints/body.py` | Weight, body fat %, and measurements (waist/hips/chest/bicep/thigh) |
| `app/blueprints/meals.py` | Log a meal (photo/text/quick-repeat), AI parse, review/confirm, history |
| `app/blueprints/exercise.py` | Simple activity log (type, duration, notes) |
| `app/blueprints/goals.py` | Targets for weight/body-fat/measurements + daily calorie/protein targets |
| `app/blueprints/coach.py` | AI coach chat + `/coach/notes` CRUD for persistent memory |
| `init_db.py` | Create tables, seed the first user from `AUTH_USERNAME`/`AUTH_PASSWORD` |
| `manage.py` | CLI to add a user / reset a password / list users (no UI for this yet) |
| `cleanup_photos.py` | Deletes meal photos older than `PHOTO_RETENTION_DAYS` (run daily via cron) |
| `run` | Bash deploy helper (same shape as vibe-split's) |
| `moronfitness.service` | Systemd unit file |
| `nginx-moronfitness.conf` | Nginx config (HTTPS, proxies to :5003) |

---

## Data Model (app/models.py)

- **User** — username/password (hashed), display name, daily calorie/protein targets.
  Auth is real per-user accounts (not vibe-split's single shared login) so a friend's
  data stays private when they're added later.
- **BodyStat** — one row per day: weight_lbs and/or body_fat_pct + notes
- **Measurement** — one row per (date, metric) — metric is one of waist/hips/chest/bicep/thigh
- **MealEntry** — a logged meal: description, optional photo, calories/protein/carbs/fat,
  status (`pending` while awaiting confirmation after AI parse, `confirmed` once saved)
- **FoodItem** — individual food items within a meal, as parsed/edited
- **SavedMeal** — a reusable meal template (name + nutrition) for one-tap re-logging of
  meals eaten repeatedly; not itself a logged meal, see Meal Logging Flow below
- **ExerciseEntry** — activity, duration, optional calories burned, free-text notes
- **Goal** — target value for a `goal_type` (weight, body_fat_pct, or a measurement),
  with starting value (captured from the latest entry when the goal is created) and
  optional target date
- **ChatMessage** — one turn (user or assistant) of the AI coach conversation, kept so
  the coach has continuity across sessions
- **CoachNote** — a durable, keyed fact for the coach's persistent memory (see AI Coach
  section below) — independent of `ChatMessage` and not subject to its rolling window

---

## Double-Submit Protection (`app/static/js/guard-double-submit.js`)

The AI-calling forms (`/meals/new`, coach chat) each got their own hand-built fetch-based
busy-state fix (see Meal Logging Flow / AI Coach below) because they needed more than a
guard — a "Thinking…"/"Analyzing…" placeholder, JSON responses, etc. But the *same root
cause* — a plain form POST gives zero visual feedback between click and the next page
render, so a normal network delay looks like nothing happened and a second click fires a
second request — applies to every plain form in the app, not just the AI ones. Confirmed
in production: a double-click on "Log a workout" with no AI involved at all created two
identical `ExerciseEntry` rows.

`guard-double-submit.js` is the generic fix for all of those: add `class="guard-double-
submit"` to any `<form>` (works for forms rendered in a loop too — it's a class, not an
ID) and it will (1) block a second submit while the first is still in flight via a
`form.dataset.submitting` flag, and (2) disable the submit button and swap it to a
"Saving…" spinner. As documented in the AI Coach section, **disabling the button
synchronously inside the submit handler can cancel the very submission it's reacting
to** — that's why the disable is deferred via `setTimeout(fn, 0)` while the submit-
blocking flag itself is still set synchronously (blocking a second submit doesn't have
that problem; only disabling a button that's mid-submission does).

Applied to every form that creates or updates a record via a plain POST:
- `exercise/index.html` — Log a workout (real duplicate-row risk before this — the
  reported bug)
- `body/index.html` — Log weight/body fat, Log a measurement (the latter had the same
  real duplicate-row risk; the former is upsert-by-date so a double-click was always
  data-safe, just silently wasteful and equally confusing to use)
- `goals/index.html` — Add a goal (real risk), Daily nutrition targets (idempotent
  overwrite, not a risk)
- `meals/index.html` — each Quick meals button (real risk — `quick_log()` has no dedup)
- `meals/review.html` — Confirm & save (updates the same meal row; upserts `SavedMeal`
  by name if checked — not a duplication risk, still deserved feedback)
- `coach/notes.html` — Add a note (upsert by key) and each note's edit form (updates the
  same row) — neither is a duplication risk, both deserved feedback

**Deliberately not guarded:** delete forms (`exercise.delete`, `body.delete_stat`,
`goals.delete`, `meals.delete`, `coach.delete_note`, etc.) already get a `confirm()`
dialog as their own feedback/friction, and a repeat delete attempt is harmless — either
idempotent or a 404 on the second click, never a duplicate. Not worth the complexity of
composing this guard with an existing `onsubmit="return confirm(...)"` handler for a
class of route where double-submission isn't actually a problem.

---

## Quick Weight Entry (dashboard)

Tapping the Weight or Body Fat tile on the dashboard (`app/templates/index.html`) opens
a Bootstrap modal that posts straight to `body.add_stat` for today's date — no need to
visit the Body page for the common case of "just log today's number." The weight and
body-fat fields are plain `type="text"` inputs with **no `inputmode` hint** (not
`type="number"`, not `inputmode="decimal"` either — see gotcha below), specifically so
they accept free text like "185.4 pounds and 19 percent body fat" — either typed, or
dropped in by **the phone keyboard's own built-in dictation mic** (iOS/Android both put
one on every text field automatically; nothing in this app provides it).
`extractReadings()` in the modal's script pulls a weight and, optionally,
a body-fat % out of that text: whichever number sits next to `%`/`percent`/`body fat` is
body fat, the matched substring is stripped out, and the remaining number (if any) is
weight. Falls back to weight-only if no body-fat marker is found. `normalizeFields()`
runs this on each field's `change` event (fires on blur — right after dictation finishes
or you tab away) and again on submit as a safety net, rewriting the field to the clean
extracted number so you see exactly what will be saved before hitting Save.

**Superseded approach, worth knowing about if this regresses:** this used to be a custom
mic button calling the browser's `SpeechRecognition`/`webkitSpeechRecognition` API
directly (same extraction regex, just triggered on a speech-recognition `result` event
instead of `change`). Removed because that JS-exposed API is a measurably slower, clunkier
code path in Safari than the OS's native keyboard dictation — extra permission friction,
noticeably higher latency — for output that's identical once transcribed. Plain text
fields get the fast native dictation for free with zero custom code; the only reason
`type="number"` couldn't be kept is that number inputs reject or mangle a dictated phrase
like "185.4 pounds" outright, so the field has to be `type="text"` for this to work at all.

**Gotcha hit here:** the first version of this fix used `type="text" inputmode="decimal"`,
reasoning that `inputmode="decimal"` would give a numeric keypad for convenience while
still being a free-text field underneath. On iOS Safari that reasoning is wrong in a way
that broke the feature completely — `inputmode="decimal"` (like `"numeric"` and `"tel"`)
makes iOS show its digits-only numeric keypad, which **has neither letter keys nor a
dictation mic button**. The only keyboard layout that reliably has the mic is the default
full QWERTY one, which means no `inputmode` hint at all. Confirmed via user report ("no
mic and i can't write text") that exactly matched what that keypad looks like — not a
caching issue, not a deploy issue, just this one attribute quietly defeating the entire
point of the change.

Voice just **fills the fields** — the user still has to hit Save, so a misheard number
is always caught before it's written.

(A scale-photo option — snap a picture, Claude Vision reads the display — was tried and
removed; not worth the friction of photographing a scale display well enough to read.)

`body.add_stat()` accepts an allowlisted `next` form field (`_safe_next()` in
`app/blueprints/body.py`) so this modal — and the Body page's own form — can each
redirect back to where they were submitted from, rather than always landing on
`/body/`. The allowlist (rather than trusting `next` directly) exists specifically to
avoid an open-redirect vector, since `next` is user-supplied form input.

---

## Dashboard Layout (`app/templates/index.html`)

The dashboard was redesigned around how the user actually uses the app day to day,
following an explicit priority order they gave: talking to the coach is the primary
interaction, weight/body-fat/calories/protein are worth a glance but don't need detail,
exercise matters as a weekly on-track/off-track signal rather than a history, and goals
aren't worth permanent screen space since they change rarely. Iterated through several
mockup rounds before implementation; the name greeting, a mic icon on the vitals row, a
literal "Xd this week" label, the old goals/exercise list-group cards, and the old
separate "Ask your coach" button were all explicitly cut along the way as not earning
their space.

**Vitals grid (`.vitals` in `app/static/css/style.css`):** five cells — weight+trend,
today's calories, exercise dots, body-fat+trend, today's protein — laid out with
`grid-template-columns: 1fr 1fr auto` and relying on CSS Grid auto-placement rather than
explicit `grid-column`/`grid-row` on every cell: with the cells in DOM order (weight,
calories, dots, body-fat, protein) and only the dots cell given `grid-row: span 2`, the
algorithm naturally places weight/body-fat stacked in column 1, calories/protein stacked
in column 2, and the dots spanning both rows in column 3 — the desired "vitals paired
vertically, dots alongside both rows" arrangement without hand-assigning positions.
Weight and body-fat each get an up/down caret + delta rather than raw numbers alone, from
independent `latest_and_prior()` lookups per field in the `index()` route (not a single
shared latest/prior `BodyStat` pair) — weight and body fat aren't always logged on the
same row, so pairing them by field rather than by row avoids showing a stale or missing
trend when only one of the two was logged most recently. The vitals cells stay tappable
(`data-bs-toggle="modal"`) into the same `quickWeightModal`/`quickMealModal` used before
the redesign — the compact grid is a new presentation of the same quick-log entry points,
not a new set of interactions.

**Exercise dots:** seven dots, fixed **Sunday-through-Saturday calendar week** (not a
rolling trailing-7-days window) — `days_since_sunday = (today.weekday() + 1) % 7` (Python's
`weekday()` returns Monday=0..Sunday=6), then `week_start = today - timedelta(days=days_since_sunday)`.
Colored as a group by that week's total exercise-day count, not per-dot: red at 1 day,
yellow at 2-3, green at 4+, matching the user's own stated exercise goal cadence — the
color alone is meant to answer "am I on track this week," no separate count/label needed.

**Coach widget (`app/templates/coach/_widget.html`):** the dashboard embeds the *same*
functional chat as the full `/coach/` page — recent messages plus a live send/receive
input — rather than a static preview, since talking to the coach is the primary way this
app gets used. Extracted into one Jinja partial taking an optional `compact` flag (compact
card styling for the dashboard vs. the full-page layout on `/coach/`) so the two contexts
don't duplicate chat markup; both variants render the same element IDs
(`chatMessages`/`chatForm`/`chatInput`/`chatSendBtn`), so the driving JS didn't need to
branch on which page it's running on. That JS was pulled out to
`app/static/js/coach-chat.js` for the same reason meal-type guessing and double-submit
guarding were already shared files — logic used on 2+ pages goes in `static/js/`, not
duplicated inline per page.

**Chat fills to the bottom of the viewport, not a fixed height.** The dashboard's vitals
+ coach widget are wrapped in `.dashboard-chat-shell` (`app/templates/index.html` /
`app/static/css/style.css`), sized to `height: calc(100dvh - 56px - 3rem)` (navbar height
+ the `.container.my-4` top/bottom margins) — a phone-sized viewport was only filling
about half the screen with the original fixed `max-height: 260px` on `.chat-messages-
compact`, wasting the exact space the user most wants for the coach. Getting the chat
card itself to grow into that shell needed no new flex plumbing: Bootstrap 5's `.card` is
already `display:flex;flex-direction:column`, and `.card-body` is already `flex:1 1
auto`, so giving `.card` `flex: 1 1 auto; min-height: 0` inside the shell is enough for it
to fill the remaining height — `.chat-messages-compact` only needed its old `max-height`
swapped for `min-height: 0` (unlocking the flex item to shrink and scroll internally
instead of forcing the card to overflow) since it already had `flex-grow-1` in the
markup. `100dvh` (not `100vh`) specifically so this doesn't miscalculate when a mobile
browser's chrome shows/hides.

---

## Meal Logging Flow

1. User submits a photo and/or free-text description at `/meals/new`
2. `meal_ai.parse_meal()` sends both to **Claude Sonnet** (vision + text in one call),
   asking for structured JSON: line items + total calories/protein/carbs/fat
3. Result lands on `/meals/<id>/review` — an editable form pre-filled with the AI
   estimate; user adjusts anything that looks wrong and confirms, including `meal_type`
   itself (the AI's/time-based guess isn't always right, e.g. a late lunch that gets
   guessed as a snack) — this is the one field on the review form that doesn't come from
   `_parse_float`/`_parse_int`, just `request.form.get("meal_type") or None` directly
4. If AI parsing fails (bad key, rate limit, etc.) the user still lands on the review
   page with an error banner and can enter nutrition manually — the flow never blocks
   on the AI being available
5. Confirming sets `status = confirmed`, which is what dashboard/coach summaries count

Meal photos are stored at `instance/photos/meals/<uuid>.<ext>` and deleted by
`cleanup_photos.py` after `PHOTO_RETENTION_DAYS` (default 30) — the `MealEntry` row and
its nutrition data are kept, only the image file goes away.

**Submission UI:** like the coach chat, `/meals/new` submits via `fetch` with a
`FormData(form)` body rather than a plain multipart POST — the Claude Vision call can
take 5–15+ seconds and there's no dedup on `MealEntry` creation (unlike `log_body_stat`'s
upsert-by-date), so an un-debounced double click would create a real duplicate meal and
a second billed API call. `meals.new()` detects the fetch via `X-Requested-With` and
returns JSON (`{"redirect": ...}` or `{"error": ...}`) instead of redirecting/re-rendering.
A photo thumbnail preview (via `URL.createObjectURL`) shows on file selection.

**Gotcha hit here (second time, same family of bug as the coach chat fix):** the first
version of this built `FormData(form)` *after* calling the busy-state helper that
disables all form fields for visual feedback — but disabled fields are silently excluded
from `FormData`, so the description/photo/meal_type never made it into the request. Any
"disable fields for feedback + submit via JS" pattern must snapshot the data (`FormData`,
or read `.value`s) **before** disabling anything.

**Meal type defaulting:** `app/static/js/guess-meal-type.js` guesses breakfast / snack /
lunch / snack / dinner / snack from local device time (6–10:30 / 10:30–12 / 12–2 / 2–5 /
5–8 / 8pm–6am) and pre-fills the `meal_type` select — still just a default, always
overridable. Shared by `/meals/new`, the dashboard's quick-meal modal, and the Quick
meals buttons below, since three copies of the same time-boundary logic drifting out of
sync would be worse than one small shared file.

**Quick meals (`SavedMeal`):** for meals eaten repeatedly, checking "Save this as a
quick-entry meal for later" on the review page (with a short name) creates or updates a
`SavedMeal` — nutrition values captured *after* any manual correction on that page, not
the raw AI estimate. Saving under a name that already exists (case-insensitive) updates
that `SavedMeal` in place rather than creating a duplicate, same upsert instinct as
`CoachNote`/`BodyStat`. These show as buttons in a "Quick meals" section at the top of
`/meals/` (`meals.index`); tapping one calls `meals.quick_log()`, which creates an
already-`confirmed` `MealEntry` directly from the template's stored numbers — **no AI
call**, instant, and bumps `last_used_at` so the list naturally surfaces recently-used
meals first (SQLite sorts `NULL` last in `ORDER BY ... DESC`, so never-yet-used saved
meals fall to the end without needing `nullslast()`). An `×` button next to each one
calls `meals.delete_saved_meal()` to remove it from the quick-entry list (the `MealEntry`
rows already logged from it are untouched — this only deletes the reusable template).

**`/meals/` list is a day → meal-type rollup, not a flat entry log.** The original flat
list (one row per `MealEntry`, photo thumbnail, full description, individually) got
noisy fast — logging a meal as 3-4 separate items (e.g. eggs, toast, coffee all tagged
"breakfast") produced 3-4 rows for what's conceptually one meal, and the AI's full
description text plus a thumbnail was more detail than useful at a glance. Grouping is
done entirely in Python in `meals.index()` — no schema change — via two queries: first
`func.date(MealEntry.logged_at)` distinct + `.limit(PAGE_DAYS + 1)` to find which
calendar days to show (the `+1` is a peek to know if there's an earlier day, i.e.
`has_more`), then one query for every entry across that day range, bucketed in Python
first by day (`e.logged_at.date().isoformat()`) then by `meal_type` within each day.
Only `status == "confirmed"` entries are included in the rollup and its totals — a
`MealEntry` still awaiting AI-parse confirmation doesn't have a "real" number yet, so it
surfaces in a separate "Needs review" section above the day list instead, pulled out
regardless of how far back its date is.

Each meal-type row (`Breakfast`/`Lunch`/`Dinner`/`Snack`, fixed order via
`MEAL_TYPE_ORDER` + `_meal_type_sort_key()` — not alphabetical, which would misorder
them — anything else/`None` sorts last as "Other") is a native `<details>/<summary>`
disclosure, not custom JS: click to expand and see the individual entries underneath
(description, calories/protein, linking to `/meals/<id>/review` for edit/delete) — no
photos or full descriptions at the rollup level, only inside the drill-down. Today's
groups render pre-expanded (`{{ ' open' if day.is_today else '' }}`); every past day
starts collapsed to just its day-total and per-meal-type subtotals. Pagination is by
**day count, not row count** — `PAGE_DAYS = 7` distinct calendar days per page, "Show
earlier days" reissues the page with `?before=<oldest-shown-date>` to fetch the next
chunk further back, rather than infinite-scroll JS.

Day/meal-type grouping uses `func.date()` on the naive-UTC `logged_at` column, i.e. the
same UTC calendar-day boundary the rest of the app already uses for "today" (dashboard
cards, `body`/`exercise` default dates) — consciously chosen over converting to
`USER_TIMEZONE` (see AI Coach below) specifically so this page's day boundaries stay
consistent with those other UTC-based ones instead of introducing a second, different
definition of "today" that could disagree with itself elsewhere on the same day. This is
still a latent app-wide inconsistency (a meal logged at 8pm Eastern is already "tomorrow"
in UTC) worth fixing everywhere at once if it ever causes a visibly wrong day grouping,
but out of scope for this pass.

---

## AI Coach

`/coach` is a chat interface that can both advise *and* log entries — it's the natural-
language logging path for the whole app (e.g. "my weight is 234.5, body fat 19%", "had a
turkey sandwich for lunch", "set my weight goal to 210").

Each turn, `ai_coach.build_context_summary()` pulls:
- **current date/time**, always first, in `USER_TIMEZONE` (`America/New_York`, hardcoded
  — fixed assumption per the user, not a stored setting, since travel is the stated
  exception rather than the common case)
- last 60 days of weight/body fat
- last 90 days of measurements
- last 14 days of meals (confirmed only), rolled up to daily calorie/protein totals
- last 14 days of exercise
- all active goals

...into a text block passed as part of the Claude system prompt, along with the
persisted conversation history (`ChatMessage` rows) and the new message. This grounds
the coach's advice in actual numbers rather than generic guidance.

**Why current time is explicit context, not assumed:** the server runs in UTC with no
notion of the user's local day boundary, and before this the coach had no time signal at
all — confirmed by a real conversation where it couldn't tell whether a new day had
started, asked the user "what's today's date?", and still ended up logging a duplicate
exercise entry from the confusion. `now_local = datetime.now(USER_TIMEZONE)` is computed
fresh on every call (not cached, not the conversation's start time), formatted as e.g.
"Friday, September 11, 2026 at 8:41 AM EDT" (`%Z` via `zoneinfo` correctly resolves
EST/EDT across the DST boundary). The system prompt tells the coach to use it for two
things specifically: noticing a day has rolled over, and inferring meal type when the
user doesn't say one.

**Tool use:** `get_response()` runs a tool-use loop (`TOOLS` in `app/ai_coach.py`) with
eight tools — `log_body_stat`, `log_measurement`, `log_meal`, `log_exercise`, `set_goal`,
`set_nutrition_targets`, `save_note`, `delete_note` — each of which writes directly to
the DB via `_execute_tool()`, scoped to the current user. The system prompt explicitly forbids claiming something was
logged unless a tool was actually called that turn (an earlier version had no tools at
all and would confidently claim to have logged things it never saved — confirmed via a
prod bug report: it told the user "I've logged 233 lbs" four times with zero `BodyStat`
rows in the DB). For meals described in words, the coach estimates nutrition itself
before calling `log_meal` — same estimation approach as `meal_ai.py`, just done inline
by the chat model rather than a separate parsing call. Only the final text reply is
persisted to `ChatMessage`; intermediate tool-use/tool-result blocks are not stored,
so history sent on later turns stays plain user/assistant text.

**Chat UI:** the send form (`app/templates/coach/index.html`) submits via `fetch`
rather than a plain form POST, so the user's message is appended to the DOM and a
"Thinking…" placeholder shown immediately, before Claude has replied — a synchronous
round trip (plus tool calls) can take several seconds, and showing nothing during that
wait is what caused a real prod bug: a user re-clicked Send repeatedly, producing six
duplicate exchanges (harmless here only because `log_body_stat` upserts by date; a
duplicate `log_meal`/`log_exercise` call would have created real duplicate rows).
`coach.send()` detects the fetch request via `X-Requested-With: XMLHttpRequest` and
returns JSON (`{"reply": ...}`) instead of redirecting; a plain form POST (no JS) still
falls back to the old redirect-based flow. The submit handler also guards against a
second click firing while one is in flight — note that **disabling the submit button
synchronously inside its own submit handler can cancel that same submission** in this
environment, so the button-disable in the old (pre-fetch) version had to defer via
`setTimeout(fn, 0)`. With the fetch-based flow this is moot since `preventDefault()` is
called unconditionally and the network request is issued manually.

**Persistent memory (`CoachNote`):** the last-20-messages window means anything older
than ~10 exchanges drops out of what the coach can see conversationally — fine for chat
flow, not fine for durable facts ("this is a big part of my health journey and I have a
strategy for it"). `CoachNote` rows (`app/models.py`) solve this the same way `BodyStat`
etc. do: `build_context_summary()` pulls *all* of a user's notes fresh from the DB every
turn, so they're always in context regardless of chat length or how many messages have
happened since. Each note has a `key` (a stable slug like `alcohol_strategy`, normalized
via `normalize_note_key()`) and free-text `content`. Saving with an existing key updates
that row instead of creating a duplicate — this is deliberate: the point is one coherent,
current fact per topic, not an append-only log of everything ever said about it. Per the
user's direction, key naming is unstructured/organic — no fixed taxonomy, the coach picks
a reasonable slug and the human-editable page works the same way regardless of what keys
exist.

The coach can write notes via the `save_note`/`delete_note` tools (system prompt tells it
to do so proactively for durable context, not one-off data points — those have their own
tools). The user has equal, independent control at `/coach/notes` (linked from the chat
page as "What my coach knows"): a full CRUD page — matching the style of Goals/Body's own
add/edit/delete forms — where every note the coach has ever written is visible in plain
language and directly editable or deletable. Neither side is the sole authority: the
coach's memory of the user is never a black box the user can't see or correct.

---

## Environment Variables (.env)

```
SECRET_KEY=<random-string>                # Flask session signing key
ANTHROPIC_API_KEY=sk-ant-...              # Claude API (meal parsing + coach)
APP_BASE_URL=https://moron.bigpour.app
AUTH_USERNAME=ryan                        # seed account, created by init_db.py once
AUTH_PASSWORD=<something>                 # change after first login
PHOTO_RETENTION_DAYS=30
```

---

## Deployment (same box as vibe-split)

Reuses the `vibesplit` SSH alias — see `deploy/hosts.ini` in vibe-split for the host.

### `./run` script commands

```bash
./run deploy      # rsync code + pip install + systemctl restart
./run sync        # rsync code only (no restart)
./run restart     # systemctl restart moronfitness
./run setup       # first-time provisioning: venv, systemd, nginx (HTTP), cron
./run cert        # certbot + install HTTPS nginx config
./run init-db     # python init_db.py on server
./run status      # systemctl status moronfitness
./run logs        # tail -f access + error logs
./run ssh         # open shell on server
```

### First-time server setup (sequence)

```bash
./run setup       # installs venv, systemd, nginx (HTTP), daily photo-cleanup cron
./run init-db     # create SQLite tables + seed user
./run cert        # certbot cert + switch to HTTPS nginx config
./run deploy      # deploy latest code
./run status      # confirm running
```

**Port note:** vibe-split uses 127.0.0.1:5002 on this box; moron-fitness uses
:5003. Keep them distinct in nginx and in each systemd unit.

---

## Known Gaps / Next Steps

- **No account UI** — adding a friend or changing a password is CLI-only (`manage.py`).
  Fine for "me and maybe a friend or two"; revisit if it grows further.
- **No wearable/third-party integration** (Apple Health, Fitbit, MyFitnessPal) — meals
  and exercise are logged manually or via AI photo/text parsing only.
- **Exercise logging is intentionally simple** — activity/duration/notes, not structured
  sets/reps/weight. Revisit if strength-training detail becomes important.
- **Coach chat has no streaming** — full request/response per turn. Fine at current
  message lengths; would need SSE/websockets if responses get slow.
- **No CSRF protection** — Flask doesn't add CSRF tokens automatically; consider
  Flask-WTF if this is ever exposed beyond a couple of trusted users.
- **Photo capture** uses `<input type="file" capture="environment">`, which opens the
  camera directly on Android and gives a camera option in iOS Safari's file picker —
  no custom camera UI needed.
- **PWA icon is a placeholder SVG** (`app/static/icons/icon.svg`) — fine for Android;
  for a polished iOS "Add to Home Screen" icon, generate proper PNG sizes.
