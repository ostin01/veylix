# Veylix API

A FastAPI backend for fleet management, vehicle telemetry, diagnostics, and
alerts. PostgreSQL stores application and validated telemetry data.

## Run with Docker Compose

The local setup creates ignored `.env` and `secrets/` files containing random
API/MQTT credentials and a local MQTT CA/server certificate. Start the stack
with:

```bash
make dev-all
```

The initial administrator username is in `.env`; its generated password is
also stored there. Keep both `.env` and `secrets/` private. The bootstrap step
creates the initial admin only when no administrator exists, so rerunning the
stack does not reset an existing account's password.

This Compose setup and the credentials in `.env.example` are for local
development only. PostgreSQL settings are required Compose variables rather
than values embedded in `docker-compose.yml`. For production, inject
`POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, and `DATABASE_URL_DOCKER`
from your deployment platform's secret/configuration manager, and mount the
JWT key at the path supplied by `JWT_SECRET_KEY_FILE`. Keep the database URL
consistent with the PostgreSQL credentials; use a URL-safe, high-entropy
database password or correctly URL-encode it. Do not deploy with the
`.env.example` values or commit production secrets.

### API authentication and roles

Except for `/`, `/health`, and `POST /api/v1/auth/token`, API endpoints require
a short-lived bearer token. Exchange the bootstrap or an administrator-created
account's credentials for a token:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<your-local-admin-password>"}'
```

Send the returned `access_token` as `Authorization: Bearer <token>`. Access
tokens expire after 15 minutes. The response also includes a 30-day refresh
token; exchange it at `POST /api/v1/auth/refresh` to rotate the refresh token
and obtain a new access token. Refresh tokens are single-use: reuse of a
rotated token revokes its token family. Store tokens securely in the client
and call `POST /api/v1/auth/logout` to revoke a refresh token. Use
`GET /api/v1/auth/me` to inspect the authenticated account.

| Role | Permissions |
| --- | --- |
| `viewer` | Read fleet, vehicle, device, telemetry, health, profile, and alert data |
| `operator` | Viewer access, fleet/vehicle/device management, and alert acknowledgement |
| `admin` | Operator access, user and diagnostic-profile management, and dead-letter management |

Administrators create accounts with `POST /api/v1/users`. Account passwords
are stored as Argon2 hashes. Authorization checks the current account and role
in the database, so inactive accounts cannot continue using existing tokens.
Users change their own password with `POST /api/v1/auth/password`, providing
the current password and a new password of at least 12 characters. Changing
it revokes refresh tokens and immediately invalidates existing access tokens;
log in again with the new password.

Administrators deactivate or reactivate accounts with
`PATCH /api/v1/users/{user_id}/status` and `{"is_active": false}` or
`{"is_active": true}`. Deactivation revokes refresh tokens and invalidates
access tokens immediately. An administrator cannot deactivate their own
account.

### Fleet and device setup

Create a fleet, vehicle, and device through the API or Swagger UI at
`http://127.0.0.1:8000/docs`, then assign the device to a vehicle. Create
requests for vehicles use the default diagnostic profile for their vehicle
type unless a compatible `diagnostic_profile_id` is supplied. The simulator
discovers active device assignments and publishes synthetic telemetry every
five seconds.

## MQTT security and telemetry contract

The local broker listens on TLS port `8883`, bound to `127.0.0.1`. Anonymous
access and plaintext MQTT are disabled. The simulator and consumer have
separate credentials and broker ACLs: the simulator may publish telemetry,
while the consumer may only subscribe. Compose mounts the credentials and
certificates from files under the ignored `secrets/` directory.

The version 1 telemetry topic is:

```text
veylix/v1/fleets/{fleet_id}/vehicles/{vehicle_id}/telemetry
```

The topic contains the fleet and vehicle IDs. The JSON envelope has
`schema_version` set to `"1.0"`, `message_id`, `vehicle_id`, `device_id`,
timezone-aware `observed_at` and `sent_at` timestamps, and a `signals` object.
The consumer validates the topic fleet and vehicle against the registered
vehicle, checks the message device and assignment, and stores accepted signals
in PostgreSQL. The signal catalogue and validation rules are in
`telemetry/schemas.py`.

Only registered and assigned devices publish; the simulator does not create
demo records. Invalid, unassigned, and exhausted messages are quarantined in
`telemetry_dead_letters`. Processing failures are retried up to
`TELEMETRY_MAX_ATTEMPTS` times (default 5) with exponential backoff. A message
is acknowledged only after storage or quarantine succeeds. If quarantine
storage fails, it remains unacknowledged for broker redelivery. A full
consumer queue triggers a non-blocking disconnect rather than stalling the
MQTT network thread.

Administrators can inspect quarantined messages with
`GET /api/v1/telemetry/dead-letters`, replay one with
`POST /api/v1/telemetry/dead-letters/{id}/replay`, or remove one with
`DELETE /api/v1/telemetry/dead-letters/{id}`. Payloads in list responses are
Base64 encoded. Replay removes a record only after successful ingestion;
rejected messages remain quarantined.

## Vehicle health and alerts

Each vehicle is assigned a diagnostic profile. Profiles are seeded by the
migration for electric, hybrid, petrol, and diesel vehicle types, with
high-voltage or 12V battery defaults as appropriate. Administrators can list,
create, update, and delete profiles at `/api/v1/diagnostic-profiles`. Profiles
define warning and critical ranges for supported telemetry signals; default
profiles cannot be deleted, and a profile cannot be deleted while assigned.
Vehicles can be moved to another compatible profile by updating
`diagnostic_profile_id`.

The seeded profiles use these common defaults: battery state of charge warns
below 20% and is critical below 10%; motor temperature warns above 100 degC
and is critical above 125; tire pressure warns below 28 or above 42 psi and
is critical below 25 or above 48; speed warns above 160 km/h and is critical
above 200; RPM warns above 8,000 and is critical above 12,000. Electric and
hybrid profiles use 300-450 V warning and 280-500 V critical ranges; petrol
and diesel profiles warn outside 12.2-15 V and are critical outside 11.5-16 V.
Adjust profiles for the vehicle and battery configuration before using these
defaults with real vehicles.

`GET /api/v1/vehicles/{vehicle_id}/health` reports a derived health score,
status, and per-signal indicators using the assigned profile. Abnormal
readings create or update an active alert; a later normal reading resolves
that alert. An assigned device is marked offline after
`DEVICE_OFFLINE_AFTER_SECONDS` (default 60 seconds since its last accepted
telemetry), checked every `DEVICE_OFFLINE_CHECK_INTERVAL_SECONDS` (default 10
seconds). The offline sweeper raises or resolves the vehicle's connectivity
alert as assigned devices go offline or recover. New devices remain `unknown`
until first telemetry is received.

`GET /api/v1/alerts` supports `vehicle_id`, `active`, `severity`, pagination,
and sorting by `created_at`, `last_observed_at`, or `severity`. The
`GET /api/v1/alerts/summary` endpoint returns active totals by severity and the
number of vehicles with active alerts. Operators and administrators may
acknowledge active alerts; the API records the acknowledging account.

## Telemetry queries

`GET /api/v1/vehicles/{vehicle_id}/telemetry` returns paginated readings and
supports `device_id`, `signal_name`, `start_time`, and `end_time` filters.
Time filters must include a timezone. For example:

```text
GET /api/v1/vehicles/{vehicle_id}/telemetry?signal_name=speed_kmh&page=1&page_size=20
```

`GET /api/v1/telemetry/latest` returns one entry per vehicle with the latest
latitude, longitude, speed, and battery state-of-charge readings. Each
available signal includes its value, unit, and observation time; missing
signals are `null`.

## Run the API directly

For the API without the simulator or MQTT consumer, install dependencies and
start PostgreSQL:

```bash
uv sync
docker compose up -d postgres
cp .env.example .env
bash scripts/prepare-local-security.sh
set -a
source .env
set +a
make apply-migrations
uv run python -m auth.bootstrap
uv run uvicorn main:app --reload
```

The default local database URL is
`postgresql+psycopg://veylix:veylix@localhost:5432/veylix`. Override
`DATABASE_URL` in `.env` to use another PostgreSQL instance. The API container
uses the `postgres` Compose service as its database host.

Run the test suite with:

```bash
uv run pytest
```

GitHub Actions runs the tests on pushes and pull requests. The database schema
is managed by Alembic migrations; do not use `Base.metadata.create_all()`
against the application database.

## Endpoint overview

All management endpoints use the `/api/v1` prefix. Unless stated otherwise,
these routes require a bearer token. Read access is available to all three
roles; write access is restricted as described above.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/auth/token` | Exchange credentials for access and refresh tokens |
| `POST` | `/api/v1/auth/refresh` | Rotate a refresh token |
| `POST` | `/api/v1/auth/logout` | Revoke a refresh token |
| `POST` | `/api/v1/auth/password` | Change the current account password |
| `GET` | `/api/v1/auth/me` | Get the current account |
| `GET`, `POST` | `/api/v1/users` | List accounts (admin); create an account (admin) |
| `PATCH` | `/api/v1/users/{user_id}/status` | Deactivate or reactivate an account (admin) |
| `GET`, `POST` | `/api/v1/fleets` | List fleets; create a fleet |
| `GET`, `PATCH`, `DELETE` | `/api/v1/fleets/{fleet_id}` | Get, update, or delete a fleet |
| `POST` | `/api/v1/vehicles` | Register a vehicle |
| `GET` | `/api/v1/vehicles` | List vehicles |
| `GET`, `PATCH`, `DELETE` | `/api/v1/vehicles/{vehicle_id}` | Get, update, or delete a vehicle |
| `GET` | `/api/v1/vehicles/{vehicle_id}/telemetry` | List vehicle telemetry |
| `GET` | `/api/v1/vehicles/{vehicle_id}/health` | Get derived vehicle health indicators |
| `GET` | `/api/v1/telemetry/latest` | Get each vehicle's latest selected readings |
| `GET` | `/api/v1/telemetry/dead-letters` | List quarantined messages (admin) |
| `POST`, `DELETE` | `/api/v1/telemetry/dead-letters/{id}/replay`, `/api/v1/telemetry/dead-letters/{id}` | Replay or delete a quarantined message (admin) |
| `GET` | `/api/v1/diagnostic-profiles` | List diagnostic profiles |
| `POST` | `/api/v1/diagnostic-profiles` | Create a diagnostic profile (admin) |
| `PATCH`, `DELETE` | `/api/v1/diagnostic-profiles/{profile_id}` | Update or delete a profile (admin) |
| `GET` | `/api/v1/alerts` | List and filter alerts |
| `GET` | `/api/v1/alerts/summary` | Get active alert and vehicle counts |
| `POST` | `/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge an active alert (operator/admin) |
| `POST` | `/api/v1/devices` | Register a device |
| `GET` | `/api/v1/devices` | List devices |
| `GET`, `PATCH` | `/api/v1/devices/{device_id}` | Get or update device metadata |
| `POST` | `/api/v1/devices/{device_id}/assign` | Assign or reassign a device |
| `DELETE` | `/api/v1/devices/{device_id}/assignment` | Unassign a device |
| `GET` | `/api/v1/devices/{device_id}/assignments` | View assignment history |

`make down-all` preserves PostgreSQL and MQTT data volumes. To remove the
database, broker persistence, and all their data, run
`docker compose down --volumes`.
