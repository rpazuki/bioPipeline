# Authentication and Roles Architecture Plan

Status: first pass implemented
Last updated: 2026-06-07

## Goal

Replace the current local admin-token model with real application users,
password login, authenticated sessions, and role-based authorization.

Roles:

- `admin`: can access every page and API workflow that exists today.
- `user`: can log in, but for now lands on an under-construction page. User
  workflows will be added later.

This first implementation is intentionally small: no teams, projects, sharing
model, OAuth, email reset flow, audit table, hard-delete, or per-resource
ownership yet. Usernames are the login identifier; email is not required.

## Current State

The application now has a general user model and session login. The earlier
`package_admin_token` model has been removed from package-management API usage.
All current backend app routes are admin-only, except `/health` and auth routes.

## Target Model

Use backend-managed browser sessions instead of storing access tokens in
frontend local storage.

```text
Browser
  -> POST /api/v1/auth/login
  <- HttpOnly SameSite session cookie
  -> authenticated API requests include cookie automatically
  -> backend resolves session -> current user -> role checks
```

Sessions are opaque random tokens stored as HttpOnly cookies. Only a hash of the
session token is stored in `auth.sqlite`.

## Runtime State

Add auth persistence under `.bio_pipeline`:

```text
.bio_pipeline/
  auth.sqlite
```

Suggested tables:

```text
users
  id TEXT PRIMARY KEY
  username TEXT UNIQUE NOT NULL
  display_name TEXT NOT NULL DEFAULT ''
  password_hash TEXT NOT NULL
  role TEXT NOT NULL CHECK(role IN ('admin', 'user'))
  is_active INTEGER NOT NULL DEFAULT 1
  created_at TEXT NOT NULL
  updated_at TEXT NOT NULL
  last_login_at TEXT

sessions
  id TEXT PRIMARY KEY
  user_id TEXT NOT NULL
  created_at TEXT NOT NULL
  expires_at TEXT NOT NULL
  revoked_at TEXT
```

No auth audit table is required in the first pass.

## Backend Modules

Add these shared/service modules:

```text
src/bio_pipeline_manager/auth_models.py
src/bio_pipeline_manager/auth_store.py
src/bio_pipeline_manager/auth_service.py
```

Responsibilities:

- `auth_models.py`: user/session dataclasses and `Role` enum.
- `auth_store.py`: SQLite persistence, migrations, path-safe initialization.
- `auth_service.py`: password hashing/verification, session creation,
  session lookup, logout/revoke, bootstrap-admin helper.

Password hashes use salted PBKDF2-SHA256 from Python's standard library. Do not
store plaintext passwords or reversible secrets.

Add auth to `PipelineRuntime` in `backend/app/services/runtime.py`:

```text
PipelineRuntime
  auth: AuthService
```

## Backend API

Add public auth routes:

```text
POST /api/v1/auth/login       username + password -> session cookie + user summary
POST /api/v1/auth/logout      revoke current session and clear cookie
GET  /api/v1/auth/me          current user summary
```

Add admin-only user management routes:

```text
GET    /api/v1/users
POST   /api/v1/users
GET    /api/v1/users/{user_id}
PATCH  /api/v1/users/{user_id}
POST   /api/v1/users/{user_id}/reset-password
POST   /api/v1/users/{user_id}/disable
POST   /api/v1/users/{user_id}/enable
```

Users are disable-only. There is no hard-delete route in the first pass.

Keep `/health` public. Make the current application API admin-only:

```text
/api/v1/runtime
/api/v1/pipeline-yamls
/api/v1/validation
/api/v1/templates
/api/v1/jobs
/api/v1/job-definitions
/api/v1/job-definition-store
/api/v1/job-definition-templates
/api/v1/packages
```

Replace `require_package_admin` with general dependencies:

```text
get_current_user()
require_authenticated_user()
require_admin()
```

`/api/v1/packages` should use `require_admin()` and stop accepting the manually
entered bearer admin token.

## Initial Admin Bootstrap

Do not commit default credentials.

Preferred first implementation:

```bash
bio-pipeline auth bootstrap-admin --username USERNAME
```

The command should prompt for a password without echoing it, create the first
admin only when no admin exists, and refuse to overwrite an existing admin.

Optional deployed-mode bootstrap:

```text
BIO_PIPELINE_BOOTSTRAP_ADMIN_USERNAME
BIO_PIPELINE_BOOTSTRAP_ADMIN_PASSWORD
```

If supported, this should be one-time only and should log/refuse once an admin
already exists.

## Frontend Flow

Add an auth shell above the current app shell:

```text
RootLayout
  AuthProvider
    if unknown: loading screen
    if unauthenticated: LoginPage
    if authenticated admin: AppShell + current admin pages
    if authenticated user: UserUnderConstructionPage
```

Admin pages remain:

```text
/
/job-definitions
/job-storage
/submit
/validation
/storage
/environment
```

Add:

```text
/login
/users                 Admin user management page
/under-construction    Ordinary user landing page for now
```

The header should show the current username/role and a logout control. The
Environment page should remove the admin-token input once package APIs use the
logged-in admin session.

## Frontend API Client

Update `frontend/src/lib/api.ts` so requests include cookies:

```text
fetch(..., { credentials: "include" })
```

Add typed functions:

```text
login(username, password)
logout()
getCurrentUser()
listUsers()
createUser()
updateUser()
resetUserPassword()
enableUser()
disableUser()
deleteUser()
```

Add shared auth/user types in `frontend/src/types/index.ts`.

## Configuration

`package_admin_token` has been removed from the package-management design.

Add config/env values:

```text
auth_session_cookie_name
auth_session_ttl_hours
auth_secure_cookies
```

Development can default `auth_secure_cookies` to false for localhost. Production
should require secure cookies and a non-empty session secret.

## Test Plan

Backend service tests:

- Password hashing verifies correct password and rejects wrong password.
- First admin bootstrap works once and refuses overwrite.
- Disabled users cannot log in.
- Sessions expire and revoked sessions fail.
- Role checks allow admin and reject ordinary users.

Backend route tests:

- Unauthenticated requests to current APIs return 401.
- Ordinary users on current APIs return 403.
- Admins can use current APIs.
- Login/logout/me work.
- Admin user CRUD works and validates duplicate usernames/roles.
- Package routes no longer accept or require the old bearer token.

Frontend tests:

- Unauthenticated users see login.
- Admin login shows current admin navigation.
- Ordinary user login shows under-construction page.
- Admin user-management form lists, creates, disables/enables, and resets
  passwords.
- Environment page no longer asks for admin token.

Manual verification:

- Start backend and frontend.
- Bootstrap an admin.
- Log in as admin.
- Confirm all current pages work.
- Create a normal user.
- Log out, log in as normal user, confirm under-construction landing.
- Confirm direct navigation to admin pages redirects or shows forbidden.

## Implementation Order

1. Add auth domain/store/service and bootstrap-admin CLI.
2. Add FastAPI auth dependencies and `/auth` routes.
3. Protect current routes with `require_admin()`.
4. Replace package admin-token dependency with `require_admin()`.
5. Add user management API routes and schemas.
6. Add frontend auth provider, login page, route gating, and logout.
7. Add admin user management page.
8. Change Environment page and API client to use session auth.
9. Add ordinary user under-construction landing.
10. Update README, `docs/PROJECT_OVERVIEW.md`, and tests.

## Decisions

- Username-only login is enough.
- Users are disable-only; no hard-delete for now.
- No auth audit table is required now.
- Sessions are opaque server-side sessions.
