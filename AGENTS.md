# AGENTS.md — budge-yet

Instructions for AI coding agents working in this repository. Read this before making changes. Update the AGENTS.md regularly to reflect new reality.

## What this is

`budge-yet` is a collaborative household budget app (v1/MVP, currently early scaffolding). Households share a
single monthly budget with categories, limits, and a transaction ledger; members see each other's spending
in real time. Full product intent lives in [docs/household-budget-app-prd.md](docs/household-budget-app-prd.md)
— **read it before implementing any feature**, since business rules (roles, limits, rollover behavior) are
specific and easy to get wrong by guessing. Technical design lives in [docs/architecture.md](docs/architecture.md).

Monorepo with two independently-built projects:

```
budge-yet/
├── backend/     FastAPI (Python 3.11+) REST API
├── frontend/    Kotlin Multiplatform + Compose Multiplatform (Android, iOS, Web/Wasm)
└── docs/        PRD + architecture spec — source of truth for product behavior
```

Backend and frontend have separate CI pipelines gated by path (`backend/**`, `frontend/**`) — see
`.github/workflows/`. Only touch the toolchain relevant to the files you're changing.

## Current state (important)

- Backend: v1 MVP REST surface is implemented — auth (email + 6-digit PIN chosen by the user at
  signup, JWT, forgot-PIN reissue, account deletion — see "Account deletion" below), households (create/update, invites, join, member roles — Owner/Admin/Member, with
  single-holder ownership transfer, leave/remove), budgets,
  categories (with reassign-before-delete), transactions (role-scoped edit/delete, filterable by
  category/payer/type/payment mode/date range/amount range/merchant-or-category search), dashboard,
  and a polling activity feed. Follows a Router → Controller → Service → Repository layering under
  `app/` (`api/v1/endpoints/` → `controllers/` → `services/` → `repositories/`). `alembic/versions/`
  now holds a full migration chain (not a single initial migration) — schema has evolved
  incrementally (login lockout fields, per-IP login-failure table, denormalized/atomic household
  member counter, unique constraints, Numeric money columns, indexes, Owner-role backfill) since the original v1 cut; see
  "Auth hardening" below and the Alembic note under Backend conventions before assuming the schema
  matches `e2eaf9009180_initial_schema.py` alone. `backend/tests/` has unit tests (`tests/unit/`) for
  `core/security.py` and `services/cycle_utils.py`, and integration tests (`tests/integration/`)
  per resource group hitting the API via `httpx.AsyncClient` against an in-memory SQLite DB.
- **Auth hardening (since v1):** login now has two independent throttles — a per-account lockout
  (`User.failed_login_attempts`/`locked_until`, tunable via `MAX_LOGIN_ATTEMPTS`/
  `LOGIN_LOCKOUT_MINUTES` in `core/config.py`) and a per-IP rate limit backed by the `login_failures`
  table (`models/login_attempt.py`, `repositories/login_attempt_repository.py`), tunable via
  `MAX_LOGIN_FAILURES_PER_IP`/`IP_LOCKOUT_WINDOW_MINUTES`. The IP throttle exists specifically to
  catch an attacker spraying guesses across many accounts, which the per-account counter alone can't
  see. Both live in `AuthService.login` (`services/auth_service.py`) and raise `RateLimitError`
  (→ HTTP 429) or `AuthenticationError` (→ HTTP 401, and see the commit carve-out on
  `AuthenticationError` under `core/database.py` below). Money amounts (`Transaction.amount`,
  `Budget.monthly_goal_amount`) are `Numeric(12, 2)`/`Decimal`, not `Float` — keep new money columns
  consistent with that.
- Frontend: All three phases (onboarding/auth, core daily-use loop, collaboration/profile) are
  complete. The app covers the full PRD surface across ~18 screens (Dashboard, Categories, History,
  Add Transaction, Profile, Household Members, Invite Member, Welcome, Auth, Backend Config,
  PIN Sent, Forgot PIN, Household Choice, Create Household, Join Household, Budget Goal,
  Configure Categories). Every repository is real — `RealAuthRepository`, `RealCategoryRepository`,
  `RealTransactionRepository`, `RealDashboardRepository`, `RealProfileRepository` — wired through
  `AppContainer`. `Fake*Repository` classes remain as reference implementations but are not
  constructed anywhere. `App.kt` gates on a persisted `AuthSession?`
  (`core/persistence/SettingsStorage`): `null` renders the onboarding route, non-null renders the
  main app shell. The backend base URL is user-configurable via the Backend Configuration screen,
  stored as a device-level `BackendConfig`.

Don't assume a feature exists because it's in the PRD or in a model/schema — check the actual endpoint
router and frontend screens first.

- **Account deletion (Google Play Console requirement, PRD E3):** `POST /auth/delete-account`
  (`schemas/auth.py DeleteAccountRequest{email, pin}`) authenticates with email+PIN (via
  `AuthService._authenticate`, the same throttled logic `login` uses) and then, in
  `AuthService.delete_account`: (1) calls `HouseholdService.remove_user_for_account_deletion`,
  which auto-transfers ownership to the longest-tenured Admin/Member if the user is an Owner with
  other members, deletes the whole household if the user is its sole member (relies on
  `Household`'s `cascade="all, delete-orphan"` relationships — see
  `HouseholdRepository.delete`), or just removes the membership otherwise; then (2) anonymizes the
  `User` row (tombstoned email, scrubbed name/nickname, randomized PIN hash, `is_deleted=True`,
  `deleted_at` set) rather than hard-deleting it — `transactions.paid_by_id`/`created_by_id` and
  `invites.invited_by_id` all `ondelete=CASCADE` to `users.id`, so an actual row delete would wipe
  shared household transaction history other members still rely on. `users.is_deleted`/
  `deleted_at` were added in migration `b1c2d3e4f5a6`. **The frontend surface for this is
  deliberately not in the Compose app** (Android/iOS/Web all ship the same `commonMain` code, and
  Play's requirement is that deletion works without the app installed) — it's a standalone static
  page at `frontend/composeApp/src/jsMain/resources/delete-account.html`, plain HTML/CSS/JS with
  no Compose/Kotlin build step, calling the hosted backend's REST endpoint directly via `fetch`
  (base URL hardcoded there — keep it in sync with `HOSTED_BASE_URL` in
  `core/network/ApiEndpoint.kt` if that ever changes). It ships as-is into the JS dist bundle
  alongside `index.html`/`favicon.png` (see "Frontend" → jsMain below), reachable at
  `/delete-account.html` on the deployed site.

### Known gaps (deliberately deferred, see PR discussion)

- **Email delivery goes through Resend, gated by `RESEND_API_KEY`.** `app/core/email.py` POSTs to
  Resend's REST API (`https://api.resend.com/emails` via `httpx`, no SDK) when
  `settings.RESEND_API_KEY` is set; when it's blank (the default — local dev and all tests run this
  way), it falls back to logging PIN/invite messages instead of sending them, same as the original
  stub. `EMAIL_FROM_ADDRESS`/`EMAIL_FROM_NAME` (`core/config.py`) default to
  `noreply@notify.imhx.top` / `BudgeYet` — a Resend-verified sending subdomain on the project's
  Cloudflare-hosted domain. A failed Resend call is logged, not raised — it must not break the
  signup/forgot-PIN/invite request itself. This only affects **forgot-PIN** (which still generates
  and emails a fresh PIN server-side — `AuthService.forgot_pin`) and invites: when running in stub
  mode, those PINs/tokens are **not** echoed back in any API response, so retrieving them requires
  reading server logs or querying the DB directly (see how `backend/tests/helpers.py` does it for
  tests, by monkeypatching the generators). **Signup is unaffected** — the user chooses and submits
  their own PIN (`UserCreate.pin`), so there's nothing to email or dig out of logs for that flow.
- **Real-time activity feed is REST-only.** `GET /households/{id}/activity-feed` is polled, not pushed.
  The PRD's WebSocket/live-push behavior (B4) was explicitly deferred to a follow-up.
- **Receipt photo upload is fully out of scope**, backend and frontend. `Transaction.receipt_url`
  exists on the model but there is no upload endpoint or storage integration, and no client-side
  capture flow either.
- **Per-IP login rate limit is bypassable on a bare deployment.** `get_client_ip` (`core/security.py`)
  unconditionally trusts `CF-Connecting-IP`/`X-Real-IP`/`X-Forwarded-For` from the incoming request,
  with no check that the request actually passed through a trusted proxy that sets/overwrites those
  headers. This is safe behind a CDN that strips client-supplied versions of them (Cloudflare, etc.),
  but on the installer's default path (`install.sh` → `docker-compose up` on a bare VPS, no CDN
  required) any client can spoof a different `X-Forwarded-For` on every request and evade
  `MAX_LOGIN_FAILURES_PER_IP` entirely — the per-account lockout (`User.failed_login_attempts`) still
  holds, but the per-IP throttle doesn't. Fix is to gate header-trust behind an explicit
  `TRUSTED_PROXY_COUNT`/`BEHIND_PROXY` setting (off by default), falling back to `request.client.host`
  when unset — see `core/security.py`.
- **Language selection removed from UI.** The Profile screen's Household Settings card previously had a Language dropdown (`languageOptions` in `ProfileScreen.kt`, wired through `ProfileController.onLanguageChange` → `ProfileRepository.updateLanguage`). The feature was removed because changing the value on the household record has no actual effect on the app's UI language — the Compose Multiplatform frontend is English-only with no i18n wiring. The backend endpoint (`PATCH /households/{id}`) still accepts `language` as a field, the `RealProfileRepository.updateLanguage` still sends it, and `Household.language` remains on the model — but there is no UI affordance for it. Adding real i18n later should restore the dropdown and wire it to an actual localization framework.
- **No resend-invite endpoint on the backend**, and no frontend affordance for it either.
  `HouseholdService`/`InviteRepository` only have create/list/revoke — no resend. The frontend
  originally added a matching `ProfileRepository.resendInvite` (fake-repo-only, no real endpoint to
  call), but it was removed since there was nothing real for it to do; see Phase 3 below. If resend
  is wanted later, add the backend endpoint first (likely: reissue token + `expires_at`, re-trigger
  `send_invite_email`), then bring the frontend button back against real networking.

## Backend (`backend/`)

**Stack:** FastAPI + Pydantic v2 + SQLAlchemy 2.0 async ORM + Alembic. SQLite (`aiosqlite`) or Postgres
(`asyncpg`) selected via `DATABASE_TYPE` env var — code must stay driver-agnostic (no SQLite- or
Postgres-only SQL/features) since both are supported deployment targets.

**One-command server installer:** [`scripts/install.sh`](scripts/install.sh) (top-level, not
`backend/scripts/`) is a standalone `curl | bash`-able installer for deploying the backend on a fresh
server — clones the repo, drives `backend/scripts/setup_env.py` for DB setup, and runs the right
`docker-compose*.yml` file. It shells out to `setup_env.py sqlite|postgres` and reads
`POSTGRES_USER`/`POSTGRES_PASSWORD`/`POSTGRES_DB`/`DATABASE_TYPE` back out of the generated `.env`, so
if you change that script's CLI (arg names, non-interactive env var names) or either compose file's
name/service names/port mapping, update `install.sh` to match — nothing type-checks that coupling.
It also patches a `COMPOSE_PROJECT_NAME` into `.env` (compose otherwise derives it from the `backend/`
dirname, which collides across separate installs on one host) — don't remove that without accounting
for the collision it fixes.

**Layout convention** (`app/`) — strict Router → Controller → Service → Repository layering:
- `models/` — SQLAlchemy ORM classes (one file per aggregate: `user.py`, `household.py` (also holds
  `HouseholdMember`), `invite.py`, `budget.py`, `category.py`, `transaction.py`, `login_attempt.py`
  (holds `LoginFailure`, the per-IP login-throttle table — see "Auth hardening" above)). Declare
  `Mapped[...]`/`mapped_column` style, not legacy `Column`.
- `schemas/` — Pydantic request/response models, mirroring `models/` filenames. Follow the existing
  `XBase` / `XCreate` / `XUpdate` / `XResponse` naming split (see `schemas/user.py`). `common.py` has
  the generic `Page[T]` pagination envelope.
- `api/v1/endpoints/` — one router module per resource; registered in `api/v1/router.py`. Routers only
  do HTTP concerns (path/query/body parsing, status codes, `Depends`) and call into `controllers/` —
  they never touch a repository or session-scoped business rule directly.
- `api/deps.py` — shared FastAPI dependencies: `get_db`, `get_current_user` (JWT bearer), and household
  access-control deps (`get_household_membership`, `require_admin_membership` — passes Admin *or*
  Owner, since Owner is a superset of Admin permissions, `get_current_household`). Owner-only actions
  (transferring ownership) enforce that narrower check themselves in the service layer, on top of
  `require_admin_membership`.
- `controllers/` — thin orchestration between routers and services; maps request schemas to service
  calls and service results back to response schemas. No query-building here — a few controllers
  (`auth_controller.py`, `dashboard_controller.py`, `user_controller.py`) import `AsyncSession`
  purely to type-hint the `db` param they pass through to services, but none construct queries
  with it directly.
- `services/` — business rules (role permissions, the 3-member cap, future-date rejection, cycle
  math in `cycle_utils.py`, delete-blocked-by-transactions, invite expiry, "always exactly one
  Owner" (single-holder, transferred via `HouseholdService._transfer_ownership` — only the current
  Owner can promote an Admin to Owner, which auto-demotes the outgoing Owner to Admin; the Owner
  can't be removed/demoted/leave directly), login lockout/rate-limit — see "Auth hardening" above).
  Raises the domain exceptions in
  `core/exceptions.py` (`NotFoundError`, `ConflictError`, `PermissionDeniedError`,
  `ValidationAppError`, `AuthenticationError`, `RateLimitError`) — never `fastapi.HTTPException`
  directly. `main.py` registers exception handlers that translate these to HTTP responses
  (`_ERROR_STATUS_CODES`; anything else raised as a bare `AppError` falls back to 400).
- `repositories/` — the only layer that touches `AsyncSession`/SQLAlchemy queries directly. No business
  logic — just CRUD and filtered/aggregated reads. Includes `login_attempt_repository.py` (per-IP
  failure counting/recording). Race-condition-prone invariants are enforced as atomic DB operations
  here rather than check-then-act service code: the 3-member household cap is a conditional `UPDATE`
  on `Household.member_count` (`HouseholdRepository.try_reserve_member_slot`/`release_member_slot`,
  backed by a `CheckConstraint`), one-household-per-user is a `unique=True` on
  `HouseholdMember.user_id`, and one-budget-per-household-per-cycle is a `UniqueConstraint` on
  `Budget(household_id, month, year)` — don't reintroduce a read-then-insert check for any of these.
- `core/config.py` — `Settings` (pydantic-settings), loaded from `.env`. Add new config here, not as
  scattered `os.environ` reads. Includes login-throttle knobs (`MAX_LOGIN_ATTEMPTS`,
  `LOGIN_LOCKOUT_MINUTES`, `MAX_LOGIN_FAILURES_PER_IP`, `IP_LOCKOUT_WINDOW_MINUTES`). `SECRET_KEY`
  still has an in-code default, but `docker-compose.yml`/`docker-compose.sqlite.yml` require
  `SECRET_KEY`/`POSTGRES_PASSWORD` to be set (`${VAR:?...}`) and fail fast with a pointer to
  `scripts/setup_env.py` instead of silently falling back to a repo-committed value — don't
  reintroduce a `:-default` fallback for either in the compose files.
- `core/database.py` — async engine/session setup and `Base`. `get_async_db` commits once at the end of
  a request if the handler didn't raise, and rolls back otherwise — repositories only ever `flush()`,
  they never commit, so don't add commits anywhere else. One deliberate carve-out: it also commits (rather
  than rolling back) on `AuthenticationError`, since login-failure bookkeeping (e.g. the failed-attempt
  counter in `AuthService.login`) is flushed right before that error is raised and must survive it. If you
  need writes to survive some other exception type, extend that one `except` clause — don't reach for a
  manual `session.commit()` in a service.
- `core/security.py` — PIN hashing (via `bcrypt` directly, **not** `passlib`: passlib's bcrypt backend
  self-test breaks under bcrypt ≥ 4.1, a live incompatibility, not a hypothetical) and JWT issue/decode.
  `generate_pin()` is only used by `AuthService.forgot_pin` now — signup takes the user's own PIN
  (`UserCreate.pin`, validated `^\d{6}$` in `schemas/user.py`) and just hashes it, it doesn't generate
  one. Don't reintroduce server-generated PINs at signup without a product reason; see PRD Section 9.1.
- `core/email.py` — sends via Resend when `RESEND_API_KEY` is set, else falls back to logging only
  — see "Known gaps" above for the gating logic.

**Dependency management is [uv](https://docs.astral.sh/uv/), not pip/venv.** `pyproject.toml` +
`uv.lock` (committed) are the source of truth; don't `pip install` anything directly or hand-edit
`.venv`. Runtime deps live in `[project.dependencies]`; dev-only tools (pytest, ruff, httpx) live in
`[dependency-groups].dev`, which `uv sync` installs by default (use `--no-dev` to skip, as the
Dockerfile does).

**Commands:**
```bash
cd backend
uv sync                                        # creates/updates .venv from uv.lock (incl. dev group)
uv run python scripts/setup_env.py sqlite      # or: postgres — generates .env non-interactively
uv run uvicorn app.main:app --reload --port 8000
uv run ruff check app/                         # lint — CI runs this, must be clean
uv run pytest -v                                # CI runs this
```
Swagger UI at `/docs`, health check at `/health` (DB-backed), and a DB-independent `/ping` liveness
check (`api/v1/endpoints/health.py`) for the frontend's Backend Configuration "Server Reachable"
validation — `/health` isn't suitable there since it depends on the target server's DB being
configured/online, which a not-yet-validated custom URL may not guarantee. Docker: `docker-compose up --build -d` (Postgres) or
`docker-compose -f docker-compose.sqlite.yml up --build -d` (SQLite) — the Dockerfile also uses uv
internally (multi-stage: installs the locked deps via `uv sync --frozen --no-dev`, then copies the
resulting `.venv` into the runtime image).

Added a new dependency? Run `uv add <package>` (or `uv add --group dev <package>` for dev-only tools)
instead of editing `pyproject.toml` by hand — it keeps `uv.lock` in sync automatically. If you do edit
`pyproject.toml` directly, run `uv lock` afterward and commit the updated `uv.lock`.

**Conventions:**
- All route handlers are `async def`; use the async session from `api/deps.get_db`, never a sync session.
- Integer autoincrement PKs (see `models/user.py`), not UUIDs — stay consistent with existing models.
- `created_at`/`updated_at` via `server_default=func.now()` / `onupdate=func.now()` on every table.
- New DB schema changes need an Alembic migration (`alembic/`) — don't rely on `Base.metadata.create_all`
  (nothing calls it; SQLite schema creation via `create_all` was deliberately removed so SQLite and
  Postgres go through the identical migration path). Alembic is the only schema authority for both
  SQLite and Postgres; run `alembic upgrade head` after pulling new migrations or setting up a fresh DB.
  If two branches each add a migration off the same parent, you'll get divergent heads on merge
  (`alembic heads` shows more than one) — resolve with `alembic merge heads` (see
  `448438686134_merge_heads.py` / `91bd6c67df47_merge_login_lockout_and_missing_indexes_.py` for
  precedent) rather than hand-editing `down_revision`.
- Run `uv run ruff check app/` before considering backend work done; CI will fail otherwise.

## Frontend (`frontend/`)

**Stack:** Kotlin Multiplatform + Compose Multiplatform targeting Android, iOS, and Web (JS), with
Ktor as the HTTP client. Package root is `com.budgeyet`. The web target uses `js(IR)` (Kotlin/JS) with
`org.jetbrains.compose.experimental.jscanvas.enabled=true` in `gradle.properties` — the `wasmJs`
target was replaced because Ktor 2.3.9 doesn't support Wasm. Web output is a static webpack bundle
deployable to any static host (Cloudflare Pages, Netlify, Vercel).

**Source sets** (under `composeApp/src/`):
- `commonMain/` — shared UI (Compose), state, domain models, networking. Put new feature code here by
  default; only drop into a platform-specific source set for genuine platform APIs.
- `androidMain/` — `MainActivity`, manifest, Android-only integrations.
- `iosMain/` — `MainViewController` bridge consumed by the Xcode wrapper in `iosApp/`.
- `jsMain/` — browser entrypoint (`main.kt`), `index.html`, and platform `actual` implementations
  for the Kotlin/JS target (`js(IR)`). Uses `ktor-client-js` as the HTTP engine (same Ktor 2.3.9
  version as Android/iOS). Four `expect`/`actual` pairs live here:
  - `SettingsStorage.js.kt` — backed by `window.localStorage`
  - `LocalFileStorage.js.kt` — backed by `window.localStorage` with `budgeyet_cache_` key prefix
  - `BackHandler.js.kt` — no-op (browser handles its own back navigation)
  - `ConnectivityObserver.js.kt` — backed by `navigator.onLine` + `online`/`offline` events
  The old `wasmJsMain/` directory is orphaned (the `wasmJs` target was replaced by `js(IR)`).

For KMP/Compose development guidance (architecture, Koin, Ktor, Room KMP, iOS interop, testing), see the vendored
guide in [`docs/kmp-compose-multiplatform/`](docs/kmp-compose-multiplatform/README.md) — start at `SKILL.md` and
drill into `references/`. It's mirrored from the MIT-licensed
[felipechaux/kmp-compose-multiplatform-skill](https://github.com/felipechaux/kmp-compose-multiplatform-skill);
where it conflicts with this file's frontend conventions, this file wins.

**Commands:**
```bash
cd frontend
./gradlew :composeApp:assembleDebug                          # Android
./gradlew :composeApp:jsBrowserDevelopmentRun                 # Web (serves at localhost:8080, hot-reload)
./gradlew :composeApp:jsBrowserProductionWebpack              # Web production bundle (output: build/dist/js/productionExecutable/)
./gradlew :composeApp:embedAndSignAppleFrameworkForXcode      # iOS framework (then open iosApp/iosApp.xcodeproj in Xcode)
```
Toolchain: Kotlin 1.9.23, Compose Multiplatform 1.6.1, Ktor 2.3.9, AGP 8.2.2, JDK 17. Versions are pinned
centrally in `gradle/libs.versions.toml` — add new dependencies there, referenced via the version catalog
(`libs.xxx`), not as inline coordinate strings in `build.gradle.kts`.

**Design system — "Stability & Growth"** (`theme/Color.kt`, `theme/Theme.kt`): Manrope typeface; Slate 900
(`#0f172a`) base; Teal `#0d9488` = on-track/positive; Amber `#d97706` = 75–99% of a budget/limit used;
Coral `#e11d48` = at/over 100% (over-budget warning). 8px rounded corners, card-based lists, persistent
bottom nav + FAB. Reuse these tokens for any new UI — don't hardcode new colors ad hoc.

**App icon / logo:** Source master lives at `composeApp/icon-source/budge-yet-master.png` (2048×2048
raster illustration — a panda mascot on a teal `#91CBBD` opaque square background; not shipped directly,
used only to regenerate platform assets via ImageMagick, e.g. `magick icon-source/budge-yet-master.png
-resize <N>x<N>^ -gravity center -extent <N>x<N> <dest>` — see git history for the exact export commands).
Regenerate all exported PNGs from this source — never hand-edit the exported PNGs/XMLs directly. Wired up as:
- **Android**: adaptive icon (`res/mipmap-anydpi-v26/ic_launcher*.xml` + `res/drawable/ic_launcher_background.xml`
  teal gradient vector matching the master's background + per-density full-bleed
  `res/mipmap-*/ic_launcher_foreground.png`) with legacy `ic_launcher.png`/`ic_launcher_round.png`
  fallback (identical square art; the OS applies its own mask) for API <26. Referenced from
  `AndroidManifest.xml` via `android:icon`/`android:roundIcon`.
- **iOS**: `iosApp/iosApp/Assets.xcassets/AppIcon.appiconset/` (single 1024×1024 opaque PNG, modern
  Xcode "universal" format), wired into `project.pbxproj` via a `PBXResourcesBuildPhase` and
  `ASSETCATALOG_COMPILER_APPICON_NAME = AppIcon` on both Debug/Release configs.
- **Web**: `jsMain/resources/favicon.png` (512×512 raster, `image/png`) + `apple-touch-icon.png` (180×180),
  linked from `index.html`'s `<head>`. `jsMain/resources/` contents are copied as-is into the JS dist
  bundle — no webpack/gradle wiring needed.
- **In-app**: `commonMain/composeResources/drawable/budge_yet_logo.png` (first drawable resource in the
  project — Compose Multiplatform resources generates `Res.drawable.budge_yet_logo`), used on
  `WelcomeScreen.kt` as the brand mark.

## Frontend current state

All three phases of the v1 frontend are complete. The app covers the full PRD surface across ~18 screens (Dashboard, Categories, History, Add Transaction, Profile, Household Members, Invite Member, Welcome, Auth, Backend Config, PIN Sent, Forgot PIN, Household Choice, Create Household, Join Household, Budget Goal, Configure Categories). Every repository is real — `RealAuthRepository`, `RealCategoryRepository`, `RealTransactionRepository`, `RealDashboardRepository`, `RealProfileRepository` — wired through `AppContainer`. `Fake*Repository` classes remain as reference implementations but are not constructed anywhere. `App.kt` gates on a persisted `AuthSession?` (`core/persistence/SettingsStorage`): `null` renders the onboarding route, non-null renders the main app shell. The backend base URL is user-configurable via the Backend Configuration screen, stored as a device-level `BackendConfig`.

### Screen map

- **Onboarding & auth (PRD A):** Welcome → Auth (Sign In/Sign Up as tabs) → Backend Configuration (gear icon, with live `GET /api/v1/ping` reachability check) → Forgot PIN → PIN Sent → Household Choice → Create Household → Budget Goal → Configure Categories, or Join Household (skips Budget Goal/Configure Categories — attaches to an existing household). `ReachabilityIndicator` composable renders all five states (IDLE, INVALID, CHECKING, REACHABLE, UNREACHABLE); Save disabled until confirmed reachable. The Budget Goal screen no longer has a "Budget Period" field (free-text, then briefly a month/year picker via the now-deleted `core/ui/MonthYearPickerDialog.kt`) — it was removed outright rather than fixed, since the backend budget cycle is derived, not user-set.
- **Core daily-use loop (PRD B/C/D):** Dashboard (budget overview, category snapshots, activity feed preview), Category Limits (admin-gated add/edit/delete with reassign-before-delete confirmation dialog), Category Detail, Transaction History (grouped/search/filtered with pagination), Transaction Detail (role-gated edit/delete), Add Transaction (expense/income with payer picker). Persistent bottom nav + FAB with long-press shortcuts (Add Expense / Add Income). Dashboard's "set up budget" prompt navigates to a `Screen.BudgetSetup` route (`App.kt`) — it reuses the same `BudgetGoalRoute`/`BudgetGoalController`/`BudgetGoalScreen` as onboarding, gated by an `isOnboarding: Boolean` param: post-onboarding it shows a "Save Budget" CTA (no "Skip for now"). Saving switches to the **Categories** tab, not Dashboard — a freshly-saved budget has no categories yet, and Categories' empty state (`CategoryListScreen.kt`) renders an `AddCategoryButton` CTA (`onAddCategory` → `Screen.AddCategory`) instead of a dead-end "no categories" message, so onboarding-skip households always have a path into category setup. The Dashboard's own category-snapshot grid has a matching `AddCategoryPlaceholderCard` (`core/ui/CategorySnapshotCard.kt`) wired to the same `Screen.AddCategory` target — historically it rendered with no `onClick`/`clickable` at all (dead UI), so any new placeholder-style card needs an explicit callback wired end-to-end (composable → Screen → Route → `App.kt`), not assumed from the visual design.
- **Category icon picker:** `categoryIconChoices` (`core/ui/IconMapper.kt`) holds the full set of selectable icon keys (22 as of this writing); only the first `categoryIconGridPreviewCount` (10) render inline on the Add Category form (`AddCategoryScreen.kt`'s `IconSelectionCard`, plain rows of 5 — not a `LazyVerticalGrid`, see next point) so the form's height stays fixed as the icon set grows. The rest are reachable via a "See all icons" button opening `IconPickerSheet.kt`, a scrollable full-set grid in a bottom sheet.
- **Grid-of-squares sizing gotcha:** Any fixed/non-scrolling icon-style grid (`IconSelectionCard`'s inline preview) should be laid out as plain `Row`s of `chunked(n)` items with `aspectRatio(1f)` + `Modifier.weight(1f)`, not a `LazyVerticalGrid` with a hardcoded `.height(...)`. A guessed pixel height clips the square cells whenever the real screen-width-dependent cell size comes out taller than the guess. `LazyVerticalGrid` is fine when the grid itself scrolls (e.g. `IconPickerSheet`'s full-set grid), since there's no fixed-height container to overflow.
- **Dialog-as-bottom-sheet gotcha:** `TransactionFilterSheet.kt` and `IconPickerSheet.kt` both build a bottom-anchored sheet from a plain `Dialog(properties = DialogProperties(usePlatformDefaultWidth = false))` rather than Material3's `ModalBottomSheet` (kept for iOS portability, per `TransactionFilterSheet.kt`'s doc comment). The platform dialog window defaults to `WRAP_CONTENT` height + center gravity — giving the *outer* content a fractional height (e.g. `fillMaxHeight(0.75f)`) shrinks the whole window to that fraction and centers it on screen (a floating card) instead of docking it to the bottom. Fix/pattern: make the outermost `Box` `fillMaxSize()` (forces the window to size to the full screen) and put the height fraction on the `Surface` nested inside it, so `Alignment.BottomCenter` has real slack to anchor at the bottom. Apply this pattern to any new Dialog-based sheet.
- **Collaboration & profile (PRD E):** Household member list with roles, promote/demote/remove (role-gated: Members can't see admin actions, Admins can't promote to Owner, only the current Owner can), invite-by-email (revocable pending invites rendered as `PendingInviteCard`), editable profile (name/nickname, read-only email), household currency, display mode preference. Push notifications toggle removed from the UI (no backend field to persist to — `ProfileRepository.updatePushNotifications` method remains for later wiring).

### Real networking

Every repository is real. `RealCategoryRepository`, `RealTransactionRepository`, `RealDashboardRepository`, and `RealProfileRepository` resolve the current household id from `core/network/HouseholdRequestContext.kt` (`HouseholdRequestContextProvider`), which bundles the access token + `BackendConfig` + household id — set on restore/onboarding-complete, cleared on sign out. `RealProfileRepository` fans out to `/users/me`, `/households/{id}`, `/households/{id}/invites`, and `/households/{id}/members/{id}`; `HouseholdResponse` never includes pending invites (admin-only fetch), so `fetchHousehold()` catches `PermissionDeniedException` on the invites call and treats it as "no invites" for plain Members.

**Inline-editable money fields:** Category Limits (`feature/category/presentation/CategoryListScreen.kt`, `CategoryLimitRow`) edits each category's monthly limit via a per-row `OutlinedTextField` with a currency-symbol `leadingIcon`. Size that field generously (currently 150dp wide, `bodyLg` text style) — a narrow field + large text style + leading icon leaves too little room for the digits, and since an unfocused `OutlinedTextField` renders from the start of its value, the overflow silently clips off the right edge (the bug, not a crash) rather than wrapping or scrolling into view. Any other inline amount-editing field should size the same way.

**Dtos and mappers:** The backend's `monthly_limit`/`spent`/`amount` are Pydantic `Decimal` fields that serialize as JSON strings (not numbers) — all feature DTOs declare these as `String` with `.toDouble()` conversion in the mapper. `remaining` is derived client-side, never decoded from the API. `UserResponseDto`/`DisplayModeDto`/`HouseholdResponseDto`/`HouseholdMemberResponseDto`/`MemberRoleDto`/`CategoryWithStatsDto`/`TransactionTypeDto` live in shared `core/network/dto/`+`core/network/mapper/` (not per-feature copies).

### Offline support (PRD §7) — queued transaction writes + read-through cache

Every feature repository in `AppContainer` is now an `OfflineFirst*Repository` wrapping its `Real*Repository`.

- **Reads** are network-first with cache fallback: `core/offline/NetworkFirstRead.kt` catches `AppException.NetworkException`/`TimeoutException` and serves the last successful fetch from `core/cache/LocalCacheStore` (JSON blobs in `core/cache/LocalFileStorage`, an expect/actual file store — `filesDir` on Android, `Library/Caches` on iOS; deliberately not DataStore/Room, same version-risk reasoning as `SettingsStorage`). Any other error (auth, permission, validation) propagates untouched so a stale cache cannot mask a real rejection.

- **Transaction writes** are the only offline write surface (per PRD §7: "Transactions can be added offline and sync automatically on reconnect"): `OfflineFirstTransactionRepository`'s `addTransaction`/`updateTransaction`/`deleteTransaction` park the operation in `core/offline/OfflineQueue` (persistent FIFO JSON array via `SyncManager.enqueue`) when the network call fails, and return a synthetic `Transaction` with a negative temp id + `clientId` (`Transaction.isPending`) so the UI shows it immediately. Deleting a still-pending create drops the queued `AddTransaction` outright. Every other write surface (categories, profile, members) deliberately passes through and surfaces the `NetworkException` inline.

- **Sync:** `core/offline/SyncManager` drains the queue FIFO against the real transaction repo (never the wrapper) on each offline→online transition — `App.kt` observes `core/util/ConnectivityObserver` (`ConnectivityManager` on Android, Network.framework's `nw_path_monitor_*` C API on iOS). `ConflictResolver` implements "server wins, append-only safe": adds never conflict (new rows); edit/delete conflicts and permanent 4xx rejections discard the change + emit a `SyncEvent.Rejected` (snackbar); transient / 5xx / 429 / expired-token keep it queued. Pending creates resolve to server ids via a clientId→serverId map populated as adds replay (queue is FIFO, so the Add always precedes ops that reference it). `pendingCount` StateFlow drives the amber "N pending" top-bar badge. Cache is updated on every successful sync so offline reads stay current. Unit tests live in `composeApp/src/commonTest/.../core/offline/`.

### Architecture choices

- Navigation is a hand-rolled `core/navigation/AppNavController` (sealed `Screen` + back-stack list), not `androidx.navigation.compose` — avoids version risk against the pinned Kotlin 1.9.23/Compose Multiplatform 1.6.1 toolchain. Keep using it rather than introducing a nav library mid-build.
- DI is a manual `core/di/AppContainer` (composition root + `CompositionLocal`), not Koin — repos are interface-first (`XRepository` + `FakeXRepository`) so swapping in Koin + real Ktor implementations later only touches the container, not screens.
- State holders are plain Kotlin classes exposing `StateFlow<UiState>`/`SharedFlow<Event>` with a manually-scoped `CoroutineScope`, not `androidx.lifecycle.ViewModel` (same version-risk reasoning).
- Persistence is a hand-rolled `core/persistence/SettingsStorage` (`expect`/`actual`: `SharedPreferences` on Android, `NSUserDefaults` on iOS), deliberately not DataStore/Room, same version-risk reasoning.

### Dummy data scenarios

`fixtures/DummyScenario.kt` — code-level switch only (change the constant in `App.kt` and rebuild; no in-app dev switcher by design): `NoBudgetSetup`, `EmptyBudgetNoTransactions`, `HealthyMidMonth`, `NearLimitAmber`, `OverBudgetCoral`, `SoloBudgeter`, `FullHouseholdThreeMembers`, `LongTransactionHistory`, `SimulatedLoadingAndError`. Fake repos add a short `delay()` before returning so Loading states are real, and `SimulatedLoadingAndError` forces a throw once so Error/retry UI is exercised too — these aren't just Success-state fixtures. Nothing currently reads `DummyScenario` except the unused `Fake*Repository` classes and `App.kt`/`AppContainer`'s now-inert `scenario` parameter.

## Key business rules to respect (from the PRD)

These affect any backend logic or UI you write around budgets/transactions — get them from the PRD, not
assumptions:
- Roles are **Owner / Admin / Member**. Members can add/edit/delete only their *own* transactions;
  Admins and the Owner can edit/delete anyone's, and manage categories, limits, invites, and household
  currency/language. Owner is a **single-holder role per household** — exactly one member holds it at
  all times, transferred (not duplicated): only the current Owner can promote an existing Admin to
  Owner, which auto-demotes the outgoing Owner to Admin in the same operation. The Owner can't be
  removed, demoted, or leave the household directly — ownership must be transferred to an Admin first.
- One budget per household, one currency per household (not per-transaction).
- Category limits **reset every cycle with no rollover** — but historical transactions/snapshots for prior
  cycles must remain intact and queryable by date range.
- Household hard cap: **3 members** (including the Owner) in v1.
- Future-dated transactions are **disallowed**.
- Auth is email + 6-digit PIN, not password-based. The PIN is **user-chosen at signup**
  (`UserCreate.pin`) — the backend only generates/emails a PIN for the forgot-PIN recovery flow,
  not at signup.
- Invite links expire after **7 days**.
- Status thresholds are consistent across dashboard and category views: teal < 75%, amber 75–99%,
  coral/red ≥ 100%.

## CI expectations

- `backend-ci.yml`: installs uv (`astral-sh/setup-uv`), `uv sync --frozen`, `uv run ruff check app/`,
  `uv run pytest -v` (against a fresh SQLite env via `setup_env.py sqlite`), then a Docker build. Keep
  backend changes lint-clean and test-covered.
- `pyproject.toml` pins `[tool.ruff.lint] select = ["E4", "E7", "E9", "F"]` explicitly. Newer ruff
  releases expand their implicit default rule set well beyond that (hundreds of extra rules, including
  a false-positive on every FastAPI `Depends(...)` default argument) — pinning keeps `ruff check`
  deterministic across ruff versions instead of silently growing scope on every dependency bump.
- `pyproject.toml` also sets `[tool.setuptools.packages.find] include = ["app*"]`. Without it, a flat
  local install (`uv sync`) fails with "Multiple top-level packages discovered" once both `app/` and
  `alembic/` exist side by side — this doesn't affect the Docker build (its builder stage runs
  `uv sync --no-install-project`, so it never builds the local package at all, only the third-party
  deps from the lockfile), but it would otherwise block local dev syncs and CI.
- `uv.lock` is committed and CI runs `uv sync --frozen` (fails instead of silently re-resolving if the
  lockfile is stale) — if you add/bump a dependency, run `uv lock` (or `uv add`/`uv add --group dev`,
  which updates the lock for you) and commit the result alongside the `pyproject.toml` change.
- `frontend-ci.yml`: validates Gradle build graph for Android, Web JS, and iOS framework compile targets
  on every PR touching `frontend/**`. The web JS target uses `jsMainClasses` (compilation, not full
  webpack bundling) for CI speed — the full production bundle is produced by `jsBrowserProductionWebpack`.

Only run/validate the pipeline(s) relevant to the code you changed.
