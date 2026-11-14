from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from enums import AlertSeverity
from schemas.health import HealthIndicator, VehicleHealthResponse
from telemetry.constants import HEALTH_SIGNAL_NAMES, SIGNAL_UNITS


@dataclass(frozen=True)
class DiagnosticFinding:
    code: str
    signal_name: str
    severity: AlertSeverity
    message: str
    threshold: str
    value_numeric: float | None
    value_text: str | None
    unit: str


def _number(signals: Mapping[str, object], name: str) -> float | None:
    value = signals.get(name)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _above_threshold(
    value: float | None,
    warning_threshold: float,
    critical_threshold: float,
) -> AlertSeverity | None:
    if value is None:
        return None
    if value > critical_threshold:
        return AlertSeverity.CRITICAL
    if value > warning_threshold:
        return AlertSeverity.WARNING
    return None


def _below_threshold(
    value: float | None,
    warning_threshold: float,
    critical_threshold: float,
) -> AlertSeverity | None:
    if value is None:
        return None
    if value < critical_threshold:
        return AlertSeverity.CRITICAL
    if value < warning_threshold:
        return AlertSeverity.WARNING
    return None


def evaluate_diagnostics(signals: Mapping[str, object]) -> list[DiagnosticFinding]:
    findings: list[DiagnosticFinding] = []

    def add_numeric(
        code: str,
        signal_name: str,
        value: float | None,
        severity: AlertSeverity | None,
        threshold: str,
        description: str,
    ) -> None:
        if value is not None and severity is not None:
            findings.append(
                DiagnosticFinding(
                    code=code,
                    signal_name=signal_name,
                    severity=severity,
                    message=f"{description}: {value:g} {SIGNAL_UNITS[signal_name]}",
                    threshold=threshold,
                    value_numeric=value,
                    value_text=None,
                    unit=SIGNAL_UNITS[signal_name],
                )
            )

    temperature = _number(signals, "motor_temperature_c")
    add_numeric(
        "motor_temperature_high",
        "motor_temperature_c",
        temperature,
        _above_threshold(temperature, warning_threshold=100, critical_threshold=125),
        "> 125 degC critical; > 100 degC warning",
        "Motor temperature is above its operating range",
    )

    battery_soc = _number(signals, "battery_soc_percent")
    add_numeric(
        "battery_soc_low",
        "battery_soc_percent",
        battery_soc,
        _below_threshold(battery_soc, warning_threshold=20, critical_threshold=10),
        "< 10% critical; < 20% warning",
        "Battery state of charge is low",
    )

    battery_voltage = _number(signals, "battery_voltage_v")
    voltage_severity = None
    voltage_threshold = (
        "< 280 V or > 500 V critical; < 300 V or > 450 V warning"
    )
    if battery_voltage is not None:
        if battery_voltage < 280 or battery_voltage > 500:
            voltage_severity = AlertSeverity.CRITICAL
        elif battery_voltage < 300 or battery_voltage > 450:
            voltage_severity = AlertSeverity.WARNING
    add_numeric(
        "battery_voltage_abnormal",
        "battery_voltage_v",
        battery_voltage,
        voltage_severity,
        voltage_threshold,
        "Battery voltage is outside its expected range",
    )

    tire_pressure = _number(signals, "tire_pressure_psi")
    if tire_pressure is not None:
        if tire_pressure < 25:
            add_numeric(
                "tire_pressure_low",
                "tire_pressure_psi",
                tire_pressure,
                AlertSeverity.CRITICAL,
                "< 25 psi critical; < 28 psi warning",
                "Tire pressure is low",
            )
        elif tire_pressure < 28:
            add_numeric(
                "tire_pressure_low",
                "tire_pressure_psi",
                tire_pressure,
                AlertSeverity.WARNING,
                "< 25 psi critical; < 28 psi warning",
                "Tire pressure is low",
            )
        elif tire_pressure > 48:
            add_numeric(
                "tire_pressure_high",
                "tire_pressure_psi",
                tire_pressure,
                AlertSeverity.CRITICAL,
                "> 48 psi critical; > 42 psi warning",
                "Tire pressure is high",
            )
        elif tire_pressure > 42:
            add_numeric(
                "tire_pressure_high",
                "tire_pressure_psi",
                tire_pressure,
                AlertSeverity.WARNING,
                "> 48 psi critical; > 42 psi warning",
                "Tire pressure is high",
            )

    speed = _number(signals, "speed_kmh")
    add_numeric(
        "speed_high",
        "speed_kmh",
        speed,
        _above_threshold(speed, warning_threshold=160, critical_threshold=200),
        "> 200 km/h critical; > 160 km/h warning",
        "Vehicle speed is unusually high",
    )

    rpm = _number(signals, "rpm")
    add_numeric(
        "rpm_high",
        "rpm",
        rpm,
        _above_threshold(rpm, warning_threshold=8000, critical_threshold=12000),
        "> 12000 rpm critical; > 8000 rpm warning",
        "Engine speed is unusually high",
    )

    vehicle_state = signals.get("vehicle_state")
    if vehicle_state == "offline":
        findings.append(
            DiagnosticFinding(
                code="vehicle_reported_offline",
                signal_name="vehicle_state",
                severity=AlertSeverity.CRITICAL,
                message="Vehicle reported an offline state",
                threshold="vehicle_state = offline",
                value_numeric=None,
                value_text="offline",
                unit=SIGNAL_UNITS["vehicle_state"],
            )
        )

    return findings


def build_vehicle_health(
    vehicle_id: UUID,
    latest_signals: Mapping[str, tuple[float | str, str, datetime]],
) -> VehicleHealthResponse:
    values = {name: value for name, (value, _, _) in latest_signals.items()}
    findings = evaluate_diagnostics(values)
    findings_by_signal = {finding.signal_name: finding for finding in findings}
    indicators: list[HealthIndicator] = []

    for signal_name in HEALTH_SIGNAL_NAMES:
        latest = latest_signals.get(signal_name)
        if latest is None:
            indicators.append(
                HealthIndicator(
                    signal_name=signal_name,
                    status="unknown",
                    value=None,
                    unit=None,
                    observed_at=None,
                    threshold=None,
                    message="No telemetry has been reported for this signal",
                )
            )
            continue

        value, unit, observed_at = latest
        finding = findings_by_signal.get(signal_name)
        indicators.append(
            HealthIndicator(
                signal_name=signal_name,
                status=finding.severity.value if finding is not None else "normal",
                value=value,
                unit=unit,
                observed_at=observed_at,
                threshold=finding.threshold if finding is not None else None,
                message=finding.message if finding is not None else "Within diagnostic thresholds",
            )
        )

    available_statuses = {indicator.status for indicator in indicators} - {"unknown", "normal"}
    if not latest_signals:
        status = "unknown"
        score = None
    elif "critical" in available_statuses:
        status = "critical"
        score = max(
            0,
            100
            - 35 * sum(i.status == "critical" for i in indicators)
            - 15 * sum(i.status == "warning" for i in indicators),
        )
    elif "warning" in available_statuses:
        status = "warning"
        score = max(0, 100 - 15 * sum(i.status == "warning" for i in indicators))
    else:
        status = "healthy"
        score = 100

    return VehicleHealthResponse(
        vehicle_id=vehicle_id,
        status=status,
        score=score,
        indicators=indicators,
    )
