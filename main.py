from fastapi import FastAPI
from routes import health
from routes import fleet
from routes import device
from routes import vehicle


app = FastAPI(
    title="Veylix API",
    description="A cloud-connected vehicle intelligence and fleet operations platform for real-time telemetry, vehicle health monitoring, diagnostics, and fleet management",
    version="0.1.0",
)


@app.get("/")
def read_root():
    return {"Hello": "World"}

app.include_router(health.router)
app.include_router(fleet.router)
app.include_router(vehicle.router)
app.include_router(device.router)
