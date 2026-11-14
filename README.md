# Veylix API

A first-draft FastAPI backend for managing fleets, vehicles, and telematics
devices. Data is held in PostgreSQL. Authentication and telemetry ingestion
are not included yet.

## Run with Docker Compose

Docker Compose builds the API and simulator, starts PostgreSQL and the local
MQTT broker, applies migrations, then starts the API and three simulated
vehicles:

```bash
make dev-all
```

Open `http://127.0.0.1:8000/docs` to try the API. The simulator publishes
synthetic telemetry every five seconds to topics such as
`veylix/v1/vehicles/{vehicle_id}/telemetry`. The local MQTT broker listens on
`localhost:1883`. Each JSON message includes generated vehicle/device IDs,
`observed_at`, and signals for GPS position, speed, odometer, battery charge
and voltage, motor temperature, RPM, tire pressure, and parked/driving state.
Inspect one message with:

```bash
docker compose exec mqtt mosquitto_sub -h localhost -t "veylix/v1/vehicles/+/telemetry" -v -C 1
```

Follow simulator logs or stop services with:

```bash
docker compose logs -f simulator
make down-all
```

The simulator currently generates demo vehicle/device IDs; it does not create
database records or feed telemetry into the API yet. MQTT ingestion and linking
simulated IDs to registered vehicles/devices are a future step.

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