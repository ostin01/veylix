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


def evaluate_diagnostics(
    signals: Mapping[str, object],
    thresholds: Mapping[str, Mapping[str, float]],
) -> list[DiagnosticFinding]:
    findings: list[DiagnosticFinding] = []
    metadata = {
        "motor_temperature_c": ("motor_temperature_high", "Motor temperature"),
        "battery_soc_percent": ("battery_soc_low", "Battery state of charge"),
        "battery_voltage_v": ("battery_voltage_abnormal", "Battery voltage"),
        "tire_pressure_psi": ("tire_pressure", "Tire pressure"),
        "speed_kmh": ("speed_high", "Vehicle speed"),
        "rpm": ("rpm_high", "Engine speed"),
    }

    for signal_name, raw_thresholds in thresholds.items():
        if signal_name not in metadata:
            raise ValueError(f"unsupported diagnostic signal: {signal_name}")
        value = _number(signals, signal_name)
        if value is None:
            continue
        critical_min = raw_thresholds.get("critical_min")
        warning_min = raw_thresholds.get("warning_min")
        warning_max = raw_thresholds.get("warning_max")
        critical_max = raw_thresholds.get("critical_max")

        direction: str | None = None
        severity: AlertSeverity | None = None
        if critical_min is not None and value < critical_min:
            direction = "low"
            severity = AlertSeverity.CRITICAL
        elif critical_max is not None and value > critical_max:
            direction = "high"
            severity = AlertSeverity.CRITICAL
        elif warning_min is not None and value < warning_min:
            direction = "low"
            severity = AlertSeverity.WARNING
        elif warning_max is not None and value > warning_max:
            direction = "high"
            severity = AlertSeverity.WARNING
        if severity is None or direction is None:
            continue

        code, description = metadata[signal_name]
        if signal_name == "tire_pressure_psi":
            code = f"{code}_{direction}"
        unit = SIGNAL_UNITS[signal_name]
        if direction == "low":
            threshold = (
                f"< {critical_min:g} {unit} critical; < {warning_min:g} {unit} warning"
            )
        else:
            threshold = (
                f"> {critical_max:g} {unit} critical; > {warning_max:g} {unit} warning"
            )
        findings.append(
            DiagnosticFinding(
                code=code,
                signal_name=signal_name,
                severity=severity,
                message=f"{description} is {direction}: {value:g} {unit}",
                threshold=threshold,
                value_numeric=value,
                value_text=None,
                unit=unit,
            )
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
    thresholds: Mapping[str, Mapping[str, float]],
) -> VehicleHealthResponse:
    values = {name: value for name, (value, _, _) in latest_signals.items()}
    findings = evaluate_diagnostics(values, thresholds)
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
