# Household Budget App — Product Requirements Document (PRD)

**Version:** 1.2
**Status:** For Review
**Date:** August 3, 2026
**Owner:** Product

---

## 1. Product Overview

A collaborative, cross-platform mobile app that lets households manage shared finances with full transparency. Every member sees the same budget, the same transactions, and the same real-time picture of where the money is going. The product replaces spreadsheets and "who paid for what" guesswork with a single shared source of truth, built around fast transaction logging and at-a-glance visual feedback.

**Design system:** "Stability & Growth" — Manrope typeface, deep slate neutrals (`#0f172a`) with teal for positive/on-track states and coral/red for warnings, rounded 8px corners, card-based layout, persistent bottom navigation.

---

## 2. Goals & Success Metrics

### Business goals
- Establish a sticky, daily-use household finance habit (not a once-a-month reconciliation tool).
- Drive multi-user adoption per household — value compounds as more members log activity.

### User goals
- Know, at a glance, how much budget is left in any category.
- Log a transaction in under 10 seconds.
- Avoid awkward money conversations by making spending visible to everyone automatically.

### Success metrics (KPIs)
| Metric | Target (post-launch) |
|---|---|
| Households with ≥2 active members | ≥ 60% of registered households |
| Median time to log a transaction | < 10 seconds |
| Transactions logged within 24h of purchase | ≥ 70% |
| Monthly retention (household level) | ≥ 50% at month 3 |
| Households that complete budget setup during onboarding | ≥ 65% |

---

## 3. Target Users & Personas

**1. The Organizer** — Usually initiates the household, sets up the budget and categories, invites members, and checks the dashboard most often. Wants control and visibility.

**2. The Contributor** — A partner, roommate, or family member who mainly logs transactions and checks their own spending against shared limits. Wants speed and simplicity, not setup overhead.

**3. The Solo Budgeter** — Uses the app individually without inviting anyone. Wants the same tracking value without any collaboration friction.

---

## 4. Scope

### In scope (v1 / MVP)
- Email-based signup, login, and PIN recovery ("Forgot PIN"), plus household creation/joining
- Single monthly budget per household, with categories and limits
- Manual transaction logging (expenses and income)
- Dashboard with spend-vs-budget gauge, category snapshots, activity feed
- Category and transaction detail/edit/delete
- Household invites via email or shareable link
- Currency, language, and dark mode preferences
- Account and data deletion (Google Play Console requirement), via a standalone web page rather
  than an in-app screen — see Section 6.E3

### Out of scope (future phases — see Section 10)
- Push notifications for member activity and budget thresholds
- Receipt OCR (auto-extracting amount/merchant from a photo)
- Savings goals, budget rollover, or multi-month trend analytics
- Exportable reports (CSV/PDF)
- Multiple concurrent budgets or multiple households per user

---

## 5. User Roles & Permissions

| Action | Owner | Admin | Member |
|---|---|---|---|
| Create/edit household budget & category limits | ✅ | ✅ | 🚫 |
| Invite / remove members | ✅ | ✅ | 🚫 |
| Add / edit / delete their own transactions | ✅ | ✅ | ✅ |
| Edit / delete other members' transactions | ✅ | ✅ | 🚫 |
| View all household transactions & activity feed | ✅ | ✅ | ✅ |
| Change household currency/language | ✅ | ✅ | 🚫 |
| Promote / demote Member ↔ Admin | ✅ | ✅ | 🚫 |
| Transfer ownership (promote an Admin to Owner) | ✅ | 🚫 | 🚫 |
| Be removed or demoted by another member | 🚫 | ✅ (by Owner/Admin) | ✅ (by Owner/Admin) |
| Leave household | ✅ (must transfer ownership first) | ✅ | ✅ |

The household creator is the default Owner. **Owner is a single-holder role** — exactly one member holds it at all times, and it's *transferred*, never duplicated: only the current Owner can promote an existing Admin to Owner, and doing so automatically demotes the outgoing Owner to Admin in the same action. Because a household must always have an Owner, the Owner cannot be removed, demoted, or leave the household directly — they must transfer ownership to an Admin first. Any number of members can hold the Admin role; an Owner or an existing Admin can promote a Member to Admin or demote an Admin back to Member.

---

## 6. Functional Requirements

### A. Onboarding & Setup

**A0. Backend endpoint selection**
- Before the Welcome journey, first launch lets the user choose which backend the app talks to: the
  hosted backend operated by us (**default**, zero configuration required) or a **custom URL** pointing
  at their own self-hosted deployment (e.g. via `scripts/install.sh`).
- Choosing "custom" prompts for a base URL and validates it's reachable (health check) before letting
  the user continue; a failed check surfaces an inline error rather than silently falling back to the
  default.
- This is a device-level setting, not a household/account setting — it's stored locally and can be
  changed later from app settings, independent of any signed-in household's data.

**A1. Welcome journey**
- 2–3 screen intro (swipeable) communicating the value proposition: shared visibility, fast logging, real-time family activity.
- Skippable at any point; last screen leads to Signup.

**A2. Signup**
- Fields: Full name, Nickname (displayed in activity feed, e.g. "Mom"), Email, and a **user-chosen 6-digit PIN** (Create PIN + confirm).
- Authentication: email + 6-digit PIN, set by the user at signup — not emailed to them. No email is sent as part of signup; there is nothing to deliver since the user already knows the PIN they just chose.
- On success, user is prompted to either **create a household** or **join one** via an invite link/code.

**A2a. Forgot PIN**
- "Forgot PIN?" link on the Login screen; user enters their email.
- If the email matches an account, a new 6-digit PIN is generated and emailed, immediately replacing (invalidating) the old one. The old PIN no longer authenticates once a new one has been issued.
- The response is identical regardless of whether the email is registered ("If an account exists for this email, a new PIN has been sent") — this prevents an attacker from using the flow to discover which emails have accounts.
- No separate reset token/link: the new PIN is delivered directly over the account's registered email, the same trusted channel already used to verify that address, rather than adding a second secret to manage.

**A3. Budget creation (skippable)**
- Fields: Budget name (default: "[Month] [Year] Budget"), monthly goal amount, cycle start day (default: 1st of month, editable).
- Skipping this step routes straight to the empty Dashboard (see B, empty states) and **also skips Category Configuration**, per brief.

**A4. Category configuration**
- Only shown if A3 was completed.
- Preset category list, multi-select, each with an icon: Groceries, Housing, Transportation, Utilities, Dining Out, Entertainment, Healthcare, Personal Care, Savings, Education, Miscellaneous.
- User assigns a monthly limit per selected category, or chooses "Split budget evenly" to auto-divide the total goal across selected categories.
- Custom categories can be added here or later.

### B. Dashboard & Insights

**B1. Overview gauge**
- Linear progress bar (horizontal): total spent vs. total monthly budget, spanning the width of the dashboard header card.
- Color states: teal (< 75% used), amber (75–99%), coral/red (≥ 100%, over budget).
- Label above the bar shows amount spent vs. total ("$1,240 of $2,000"); label below (or trailing) shows amount remaining, or amount over in red if exceeded.

**B2. Quick actions (FAB)**
- Persistent floating action button, bottom-right, above nav bar.
- Tap → Add Transaction form. Long-press (or tap-and-hold) reveals two shortcuts: "Add Expense" / "Add Income."

**B3. Category snapshots**
- Scrollable list of active categories, each showing: icon, name, mini progress bar, amount spent / limit, remaining balance.
- Sorted by % utilized (descending) by default.
- Tap → Category Detail screen (see C3).

**B4. Family activity feed**
- Reverse-chronological feed: avatar/nickname, action, amount, category, relative timestamp ("2m ago").
- Updates in real time (push/websocket) as other members log transactions.
- Tap an entry → opens that transaction's detail view.

**B5. Empty states**
- No budget created: card prompting "Set up your first budget" → routes to A3.
- Budget exists, no transactions yet: prompt "Log your first transaction" → routes to D1.

### C. Budget & Category Management

**C1. Category limits screen**
- List of all categories with editable monthly limit (currency-formatted numeric input).
- Add new category (name, icon, limit) or delete existing.
- Deleting a category with existing transactions requires reassigning those transactions to another category first (blocking delete otherwise).
- Limits reset to the configured amount at the start of each new cycle — unused balance does not roll over. Each prior month's transactions and spend-vs-limit snapshot remain intact and viewable via date-range filtering (see D2).

**C2. Visual tracking**
- Same teal/amber/coral thresholds as B1, applied per-category.
- Progress bar fill reflects % of limit used; overflow past 100% shown as a filled red bar with an "over by $X" label.

**C3. Category detail**
- Header: category name, icon, limit, spent, remaining, % utilized.
- Transaction list scoped to that category, same grouped/searchable list as D2.
- Edit limit inline from this screen (Admin or Owner only).

### D. Transaction Management

**D1. Add transaction**
- Toggle: Expense / Income.
- Fields: Amount (required), Merchant/description (required), Category (searchable picker, required for expenses), Date (defaults to today; future dates disallowed), Who Paid (household member picker, defaults to current user), Payment mode (Cash, Card, Bank Transfer/UPI, Other), Notes (optional), Receipt photo (optional, camera or library).
- Save posts immediately to the shared household ledger and activity feed.

**D2. Transaction history**
- Full list, grouped by date (most recent first).
- Search by merchant, category, or amount.
- Filters: category, household member, date range, payment mode, expense/income.

**D3. Detail & edit**
- Full transaction detail: all fields from D1, plus who logged it and when.
- Edit (own transactions for Members; any transaction for Admins/Owner) or delete (with confirmation dialog).
- Full-screen receipt image viewer if a photo was attached.

### E. Collaboration & Profile

**E1. Family sharing**
- Invite via email (sends a link) or a shareable join link/QR code with expiry (7 days).
- Household hard cap: 3 members total (including the Owner) in v1. Invite flow disables/hides once the cap is reached.
- Invitee: taps link → signup (if new) or login (if existing) → auto-joins the household as a Member.
- Admin or Owner can revoke a pending invite or remove an existing member (except the Owner themself, who cannot be removed — see Section 5).
- Member management screen shows each member's role badge (Owner/Admin/Member) and, for non-Owner rows, an action menu: Members get "Promote to Admin"; Admins get "Promote to Owner" (transfers ownership, Owner-only action) and "Demote to Member"; both get "Remove from Household."

**E2. Profile & preferences**
- Editable: name, nickname. No photo upload in v1 — avatars are rendered from profile initials.
- Email shown read-only post-signup; editing is not allowed.
- Household-level settings (Admin/Owner-editable): currency, language.
- Personal settings: display mode (Light / Dark / System).

**E3. Account deletion**
- Required by Google Play Console's account/data deletion policy: a user must be able to request
  deletion of their account and data via a path that doesn't require the app to be installed.
- Delivered as a standalone web page (not a screen inside the app itself), reachable at
  `/delete-account.html` on the hosted web deployment. The user authenticates with their email +
  6-digit PIN — the same credential used to sign in — proving ownership without needing an
  existing session, then confirms via a dialog before the deletion is submitted.
- Deletion semantics (chosen to protect other household members' shared data, since transactions
  can be logged by one member and relied on by others):
  - The user's profile (name, nickname, email, PIN) is anonymized/scrubbed rather than the row
    being hard-deleted, since transactions the user logged or paid for must not vanish from a
    household other members still use.
  - If the user is their household's only member, the household and everything in it (budget,
    categories, transactions, invites) is deleted outright.
  - If the user is the household's Owner and other members remain, ownership auto-transfers to
    the longest-tenured Admin (or, absent any Admin, the longest-tenured Member) before the
    user's membership is removed — no manual "transfer ownership first" step is required.
  - If the user is an Admin or Member (not Owner), they're simply removed from the household;
    other members keep the shared budget, categories, and transaction history untouched.
- Once deleted, the account's original email and PIN no longer authenticate anything, and the
  email becomes available for a fresh signup.

---

## 7. Non-Functional Requirements

- **Platform:** iOS and Android, single cross-platform codebase.
- **Offline support:** Transactions can be added offline and sync automatically on reconnect (queued writes, conflict-safe).
- **Real-time sync:** Activity feed and dashboard reflect other members' actions within a few seconds.
- **Performance:** Dashboard cold-load under 2 seconds on a mid-tier device.
- **Security:** Household data scoped and access-controlled by role; authenticated API access; receipt images stored in access-controlled storage.
- **Accessibility:** Text and status colors (teal/coral on slate) meet WCAG AA contrast; supports dynamic/system font scaling.
- **Localization:** Architecture supports multiple languages at launch even if only one ships initially.

---

## 8. Design System Reference

**Typography:** Manrope — Bold for headers/amounts, Medium for labels, Regular for body text.

**Color tokens**
| Token | Hex | Usage |
|---|---|---|
| Slate 900 (base) | `#0f172a` | Backgrounds, primary text (light mode) |
| Teal (positive) | Brand teal | On-track budgets, positive progress |
| Coral/Red (warning) | Brand coral | Near-limit / over-budget states |

**Components:** 8px rounded corners; card-based grouping for all list items (categories, transactions); persistent bottom nav bar (Dashboard, Categories, Add [FAB], History, Profile); linear progress bar as the dashboard centerpiece.

---

## 9. Confirmed Product Decisions

The following were open questions in the initial draft and have since been confirmed:

1. **Auth method:** Email + 6-digit PIN. The user chooses their own PIN at signup (Create PIN + confirm) — it is not generated or emailed to them; the same PIN is re-entered for subsequent logins.
   - **Forgot PIN:** Requesting a reset by email issues and emails a brand-new, server-generated PIN, invalidating the old one. No separate reset token — the email channel itself is the recovery mechanism. Response is generic (doesn't reveal whether the email is registered).
2. **Role granularity:** Owner + Admin + Member model. The household creator becomes its Owner. Owner is a single-holder role — transferred, not duplicated: only the current Owner can promote an existing Admin to Owner, which automatically demotes the outgoing Owner to Admin. The Owner cannot be removed, demoted, or leave the household without transferring ownership first. Multiple Admins per household are supported; a Member can be promoted to Admin (and demoted) by an existing Owner or Admin.
3. **Budget cycle rollover:** No rollover — each new cycle resets category limits to the configured amount. Prior months' transaction and spend data remain intact and accessible.
4. **Future-dated transactions:** Not required; disallowed in v1.
5. **Household size:** Hard cap of 3 members per household (including the Owner) in v1. Raising the cap is flagged as a future monetization opportunity (see Section 10).
6. **Currency scope:** One currency per household, set at setup — not per-transaction.
7. **Invite link expiry:** 7 days.
8. **Email edit post-signup:** Not allowed; email is permanently read-only after signup.
9. **Backend endpoint:** Configurable at onboarding (see A0) — defaults to our hosted backend, with an
   option to point the client at a self-hosted deployment instead. A device-level setting, not synced
   per-household.

---

## 10. Release Phasing

**v1 (MVP):** Everything in Section 4's "in scope" list.

**Phase 2 (candidates):**
- Push notifications (member activity, budget threshold alerts)
- Receipt OCR for auto-filled transaction details
- Savings goals and budget rollover
- Exportable reports (CSV/PDF)
- Multi-currency support
- Spending trend charts across months
- Paid tier to raise the 3-member household cap
