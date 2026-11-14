# Veylix API

A FastAPI backend for managing fleets, vehicles, and telematics devices.
PostgreSQL stores application and validated telemetry data. Authentication is
not included yet.

## Run with Docker Compose

Docker Compose builds the API, telemetry consumer, and simulator; starts
PostgreSQL and the local MQTT broker; applies migrations; then starts the
services. The simulator publishes only for devices currently assigned to
registered vehicles:

```bash
make dev-all
```

Create a fleet, vehicle, and device in `http://127.0.0.1:8000/docs`, and assign
the device to that vehicle. The simulator discovers active assignments from
PostgreSQL and publishes synthetic telemetry every five seconds to
`veylix/v1/vehicles/{vehicle_id}/telemetry`. The consumer validates the
registered vehicle/device and active assignment, then stores one row per
signal in PostgreSQL. Accepted telemetry updates the device connection status
to `online` and its `last_seen_at` timestamp.

The MQTT topic is `veylix/v1/vehicles/{vehicle_id}/telemetry`. Its version-1
JSON envelope contains `schema_version`, `message_id`, `vehicle_id`,
`device_id`, timezone-aware `observed_at`, and a `signals` object. The signal
catalogue is defined in `telemetry/schemas.py` and is shared by the simulator
and consumer.

The local MQTT broker listens on `localhost:1883`. Inspect a message with:

```bash
docker compose exec mqtt mosquitto_sub -h localhost -t "veylix/v1/vehicles/+/telemetry" -v -C 1
```

Follow simulator logs or stop services with:

```bash
docker compose logs -f simulator
make down-all
```

Only registered and assigned devices publish; no demo database records are
created automatically. Invalid or unassigned messages are quarantined in
`telemetry_dead_letters` and are available from
`GET /api/v1/telemetry/dead-letters`. Messages are acknowledged only after
successful storage or quarantine. Processing failures are retried up to
`TELEMETRY_MAX_ATTEMPTS` times (default 5) with exponential backoff; if
quarantine storage also fails, the message remains unacknowledged for broker
redelivery. Dead-letter payloads are returned as Base64. A full
consumer queue triggers a non-blocking disconnect, so unacknowledged QoS 1
messages can be redelivered after the consumer restarts.

The consumer checks device freshness every
`DEVICE_OFFLINE_CHECK_INTERVAL_SECONDS` (default 10) and marks online devices
offline after `DEVICE_OFFLINE_AFTER_SECONDS` (default 60) without accepted
telemetry. New devices remain `unknown` until first telemetry is received.

`GET /api/v1/vehicles/{vehicle_id}/health` reports a derived health score and
per-signal indicators. Diagnostic alerts are created when readings cross
thresholds and automatically resolved on a later normal reading. Defaults are
in `telemetry/health.py`: low battery state of charge, motor temperature,
battery voltage, tire pressure, speed, RPM, and a vehicle-reported offline
state. View alert history with `GET /api/v1/alerts?vehicle_id={vehicle_id}`;
use `active=true` for unresolved alerts and acknowledge one with
`POST /api/v1/alerts/{alert_id}/acknowledge`.

The initial diagnostic thresholds are code-defined defaults: state of charge
below 20% (critical below 10%); motor temperature above 100 degC (critical
above 125); tire pressure below 28 or above 42 psi (critical below 25 or above
48); speed above 160 km/h (critical above 200); and RPM above 8,000 (critical
above 12,000). Battery-voltage thresholds assume the simulator's high-voltage
pack (warning outside 300-450 V, critical outside 280-500 V); tune them for
real vehicles before using this rule with other battery types. Runtime
connectivity and retry settings can be overridden in `.env`.

Retrieve a vehicle's telemetry with
`GET /api/v1/vehicles/{vehicle_id}/telemetry`. Results are paginated and can
be filtered with `device_id`, `signal_name`, `start_time`, and `end_time`.
Time filters must include a timezone. For example:

```text
GET /api/v1/vehicles/{vehicle_id}/telemetry?signal_name=speed_kmh&page=1&page_size=20
```

For a fleet-wide dashboard snapshot, `GET /api/v1/telemetry/latest` returns one
entry for every vehicle, with the latest known latitude, longitude, speed, and
battery state of charge. Each signal includes its value, unit, and observation
time; signals without a reading are `null`.

`make down-all` preserves the PostgreSQL and MQTT data volumes. To remove the
database, broker persistence, and all their data, run
`docker compose down --volumes`.

## Run the API directly

Install the project and start PostgreSQL:

```bash
uv sync
docker compose up -d postgres
```

Copy `.env.example` to `.env`, apply migrations, and start the API:

```bash
cp .env.example .env
make apply-migrations
uv run uvicorn main:app --reload
```

The default local connection string is
`postgresql+psycopg://veylix:veylix@localhost:5432/veylix`. Override
`DATABASE_URL` in `.env` to use another PostgreSQL instance. The API container
uses the `postgres` Compose service as its database host.

To run the database integration tests:

```bash
uv run pytest
```

GitHub Actions runs the same test suite on pushes and pull requests.

Open `http://127.0.0.1:8000/docs` to try the endpoints interactively.

The database schema is managed by Alembic migrations; do not use
`Base.metadata.create_all()` against the application database.

## Endpoints

All management endpoints use the `/api/v1` prefix.

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/api/v1/fleets` | Create a fleet |
| `GET` | `/api/v1/fleets` | List fleets (`page`, `page_size`) |
| `GET` | `/api/v1/fleets/{fleet_id}` | Get a fleet |
| `PATCH` | `/api/v1/fleets/{fleet_id}` | Partially update a fleet |
| `DELETE` | `/api/v1/fleets/{fleet_id}` | Delete an empty fleet |
| `POST` | `/api/v1/vehicles` | Register a vehicle in a fleet |
| `GET` | `/api/v1/vehicles` | List vehicles (`page`, `page_size`, `fleet_id`, `status`, `search`, `sort_by`, `sort_order`) |
| `GET` | `/api/v1/vehicles/{vehicle_id}` | Get a vehicle |
| `GET` | `/api/v1/vehicles/{vehicle_id}/telemetry` | List vehicle telemetry (filters and pagination) |
| `GET` | `/api/v1/vehicles/{vehicle_id}/health` | Get derived vehicle health indicators |
| `GET` | `/api/v1/telemetry/latest` | Get each vehicle's latest position, speed, and battery reading |
| `GET` | `/api/v1/telemetry/dead-letters` | List quarantined telemetry messages |
| `GET` | `/api/v1/alerts` | List alerts (`vehicle_id`, `active`, pagination) |
| `POST` | `/api/v1/alerts/{alert_id}/acknowledge` | Acknowledge an active alert |
| `PATCH` | `/api/v1/vehicles/{vehicle_id}` | Partially update vehicle details or status |
| `DELETE` | `/api/v1/vehicles/{vehicle_id}` | Delete a vehicle |
| `POST` | `/api/v1/devices` | Register a device |
| `GET` | `/api/v1/devices` | List devices (`page`, `page_size`, `vehicle_id`, `connection_status`, `search`, `sort_by`, `sort_order`) |
| `GET` | `/api/v1/devices/{device_id}` | Get a device |
| `PATCH` | `/api/v1/devices/{device_id}` | Update device metadata |
| `POST` | `/api/v1/devices/{device_id}/assign` | Assign or reassign a device to a vehicle |
| `DELETE` | `/api/v1/devices/{device_id}/assignment` | Unassign a device and close its active assignment |
| `GET` | `/api/v1/devices/{device_id}/assignments` | View assignment history |

Create operations return `201`; deletes return `204`. Missing resources return
`404`, duplicate vehicle VINs or registration numbers return `409`, and a fleet
with vehicles cannot be deleted. Vehicles with device assignment history cannot
be deleted, preserving audit references; vehicles with telemetry history are
also protected. Vehicle status values are `active`, `inactive`, and
`maintenance`. Device connection status values are `unknown`, `online`, and
`offline`. Device registration can optionally include a `vehicle_id`;
assigning or reassigning through the API records timestamped history. The
`connection_status` and `last_seen_at` fields are read-only in public device
requests and are updated when telemetry is accepted.