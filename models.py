from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Uuid,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from db import Base
from enums import DeviceConnectionStatus, VehicleStatus, VehicleType


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Fleet(Base):
    __tablename__ = "fleets"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Vehicle(Base):
    __tablename__ = "vehicles"
    __table_args__ = (
        CheckConstraint("year >= 1900 AND year <= 2100", name="ck_vehicles_year_range"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    fleet_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("fleets.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    vin: Mapped[str | None] = mapped_column(String(17), nullable=True, unique=True)
    registration_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    make: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False)
    year: Mapped[int] = mapped_column(nullable=False)
    vehicle_type: Mapped[VehicleType] = mapped_column(
        Enum(
            VehicleType,
            name="vehicle_type",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
    )
    status: Mapped[VehicleStatus] = mapped_column(
        Enum(
            VehicleStatus,
            name="vehicle_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
        default=VehicleStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    serial_number: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vehicles.id", ondelete="SET NULL"), nullable=True
    )
    device_type: Mapped[str] = mapped_column(String(50), nullable=False)
    firmware_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    connection_status: Mapped[DeviceConnectionStatus] = mapped_column(
        Enum(
            DeviceConnectionStatus,
            name="device_connection_status",
            native_enum=False,
            create_constraint=True,
            values_callable=lambda enum_type: [member.value for member in enum_type],
        ),
        nullable=False,
        default=DeviceConnectionStatus.UNKNOWN,
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class DeviceAssignment(Base):
    __tablename__ = "device_assignments"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    device_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("devices.id", ondelete="CASCADE"), nullable=False
    )
    vehicle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    unassigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


Index(
    "uq_vehicles_registration_number_lower",
    func.lower(Vehicle.registration_number),
    unique=True,
)
Index("ix_devices_vehicle_id", Device.vehicle_id)
Index("ix_devices_connection_status", Device.connection_status)
Index("uq_devices_serial_number_lower", func.lower(Device.serial_number), unique=True)
Index("ix_device_assignments_vehicle_id", DeviceAssignment.vehicle_id)
Index(
    "uq_device_assignments_active_device",
    DeviceAssignment.device_id,
    unique=True,
    postgresql_where=DeviceAssignment.unassigned_at.is_(None),
    sqlite_where=DeviceAssignment.unassigned_at.is_(None),
)


class TelemetryReading(Base):
    __tablename__ = "telemetry_readings"
    __table_args__ = (
        UniqueConstraint("message_id", "signal_name", name="uq_telemetry_message_signal"),
        Index("ix_telemetry_vehicle_observed_at", "vehicle_id", "observed_at"),
        Index("ix_telemetry_signal_observed_at", "signal_name", "observed_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    vehicle_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("vehicles.id", ondelete="RESTRICT"), nullable=False
    )
    device_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("devices.id", ondelete="RESTRICT"), nullable=False
    )
    signal_name: Mapped[str] = mapped_column(String(50), nullable=False)
    value_numeric: Mapped[float | None] = mapped_column(nullable=True)
    value_text: Mapped[str | None] = mapped_column(String(50), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    schema_version: Mapped[int] = mapped_column(nullable=False)
    message_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
