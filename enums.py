from enum import Enum


class VehicleStatus(str, Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    MAINTENANCE = "maintenance"


class VehicleType(str, Enum):
    ELECTRIC = "electric"
    HYBRID = "hybrid"
    PETROL = "petrol"
    DIESEL = "diesel"


class DeviceConnectionStatus(str, Enum):
    UNKNOWN = "unknown"
    ONLINE = "online"
    OFFLINE = "offline"
