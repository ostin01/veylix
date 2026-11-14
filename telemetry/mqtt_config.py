import os
from pathlib import Path

import paho.mqtt.client as mqtt


def configure_mqtt_client(client: mqtt.Client) -> None:
    username = os.getenv("MQTT_USERNAME")
    password_file = os.getenv("MQTT_PASSWORD_FILE")
    ca_cert = os.getenv("MQTT_TLS_CA_CERT")
    if not username or not password_file or not ca_cert:
        raise RuntimeError(
            "MQTT_USERNAME, MQTT_PASSWORD_FILE, and MQTT_TLS_CA_CERT must be configured"
        )

    password_path = Path(password_file)
    if not password_path.is_file():
        raise FileNotFoundError(f"MQTT password secret file does not exist: {password_path}")
    password = password_path.read_text(encoding="utf-8").strip()
    if not password:
        raise ValueError("MQTT password secret file must not be empty")

    ca_path = Path(ca_cert)
    if not ca_path.is_file():
        raise FileNotFoundError(f"MQTT CA certificate file does not exist: {ca_path}")
    client.username_pw_set(username, password)
    client.tls_set(ca_certs=str(ca_path))
