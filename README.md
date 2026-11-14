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
created automatically. Invalid or unassigned messages are rejected and logged.
Telemetry readings are persisted, but a telemetry retrieval endpoint is not
implemented yet.

`make down-all` preserves the PostgreSQL data volume. To remove the database
and all its data, run `docker compose down --volumes`.

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
be deleted, preserving audit references. Vehicle status values are `active`,
`inactive`, and `maintenance`. Device connection status values are `unknown`,
`online`, and `offline`. Device registration can optionally include a
`vehicle_id`; assigning or reassigning through the API records timestamped
history. The `connection_status` and `last_seen_at` fields are read-only in
public device requests and will be updated by the future telemetry/heartbeat
pipeline.