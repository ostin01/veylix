from fastapi import FastAPI
from routes import health
from routes import fleet
from routes import vehicle


app = FastAPI(
    title="Veylix API",
    description="Cloud-based IoT Automotive infrastructure platform",
    version="0.1.0",
)


@app.get("/")
def read_root():
    return {"Hello": "World"}

app.include_router(health.router)
app.include_router(fleet.router)
app.include_router(vehicle.router)
