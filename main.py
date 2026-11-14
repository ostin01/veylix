from fastapi import FastAPI

from routes import (
    alerts,
    auth,
    device,
    diagnostic_profiles,
    fleet,
    health,
    telemetry,
    users,
    vehicle,
)


app = FastAPI(
    title="Veylix API",
    description="A cloud-connected vehicle intelligence and fleet operations platform for real-time telemetry, vehicle health monitoring, diagnostics, and fleet management",
    version="0.1.0",
)


@app.get("/")
def read_root():
    return {"Hello": "World"}

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(diagnostic_profiles.router)
app.include_router(fleet.router)
app.include_router(vehicle.router)
app.include_router(device.router)
app.include_router(telemetry.router)
app.include_router(alerts.router)
