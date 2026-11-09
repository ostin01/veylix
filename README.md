# Veylix API

A first-draft FastAPI backend for managing fleets, vehicles, and telematics
devices. Data is held in PostgreSQL. Authentication and telemetry ingestion
are not included yet.

## Run with Docker Compose

Docker Compose builds the API image, starts PostgreSQL, applies migrations, and
then starts the API:

```bash
make dev-all
```

Open `http://127.0.0.1:8000/docs` to try the endpoints. Useful commands:

```bash
make docker-logs
make down-all
```

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
| `PATCH` | `/api/v1/devices/{device_id}` | Update device metadata or connection state |
| `POST` | `/api/v1/devices/{device_id}/assign` | Assign or reassign a device to a vehicle |

Create operations return `201`; deletes return `204`. Missing resources return
`404`, duplicate vehicle VINs or registration numbers return `409`, and a fleet
with vehicles cannot be deleted. Vehicle status values are `active`, `inactive`,
and `maintenance`. Device connection status values are `unknown`, `online`, and
`offline`. Newly registered devices are unassigned and have no `last_seen_at`
value until supplied through the API or updated by a future telemetry heartbeat.