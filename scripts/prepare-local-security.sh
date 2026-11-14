#!/usr/bin/env bash
set -euo pipefail

mkdir -p secrets/mqtt
touch .env

set_env_if_blank() {
    key=$1
    value=$2
    if grep -q "^${key}=" .env; then
        if ! grep -q "^${key}=." .env; then
            sed -i "s|^${key}=.*$|${key}=${value}|" .env
        fi
    else
        printf '%s=%s\n' "$key" "$value" >> .env
    fi
}

set_env_if_blank POSTGRES_DB veylix
set_env_if_blank POSTGRES_USER veylix
set_env_if_blank POSTGRES_PASSWORD veylix
postgres_db=$(grep '^POSTGRES_DB=' .env | cut -d= -f2-)
postgres_user=$(grep '^POSTGRES_USER=' .env | cut -d= -f2-)
postgres_password=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2-)
set_env_if_blank DATABASE_URL "postgresql+psycopg://${postgres_user}:${postgres_password}@localhost:5432/${postgres_db}"
set_env_if_blank DATABASE_URL_DOCKER "postgresql+psycopg://${postgres_user}:${postgres_password}@postgres:5432/${postgres_db}"
set_env_if_blank JWT_SECRET_KEY_FILE ./secrets/jwt_secret_key
set_env_if_blank BOOTSTRAP_ADMIN_USERNAME admin
set_env_if_blank BOOTSTRAP_ADMIN_PASSWORD "$(openssl rand -hex 24)"
set_env_if_blank MQTT_CA_CERT_FILE ./secrets/mqtt/ca.crt
set_env_if_blank MQTT_SERVER_CERT_FILE ./secrets/mqtt/server.crt
set_env_if_blank MQTT_SERVER_KEY_FILE ./secrets/mqtt/server.key
set_env_if_blank MQTT_SIMULATOR_PASSWORD_FILE ./secrets/mqtt/simulator_password
set_env_if_blank MQTT_CONSUMER_PASSWORD_FILE ./secrets/mqtt/consumer_password

if [[ ! -s secrets/jwt_secret_key ]]; then
    openssl rand -hex 32 > secrets/jwt_secret_key
fi
if [[ ! -s secrets/mqtt/simulator_password ]]; then
    openssl rand -hex 32 > secrets/mqtt/simulator_password
fi
if [[ ! -s secrets/mqtt/consumer_password ]]; then
    openssl rand -hex 32 > secrets/mqtt/consumer_password
fi
chmod 600 secrets/jwt_secret_key secrets/mqtt/simulator_password secrets/mqtt/consumer_password

if [[ ! -s secrets/mqtt/ca.crt || ! -s secrets/mqtt/server.crt || ! -s secrets/mqtt/server.key ]]; then
    openssl req -x509 -newkey rsa:3072 -sha256 -days 3650 -nodes \
        -keyout secrets/mqtt/ca.key \
        -out secrets/mqtt/ca.crt \
        -subj "/CN=Veylix local MQTT CA"
    openssl req -new -newkey rsa:3072 -nodes \
        -keyout secrets/mqtt/server.key \
        -out secrets/mqtt/server.csr \
        -subj "/CN=mqtt"
    printf '%s\n' \
        'subjectAltName=DNS:mqtt,DNS:localhost,IP:127.0.0.1' \
        'keyUsage=digitalSignature,keyEncipherment' \
        'extendedKeyUsage=serverAuth' > secrets/mqtt/server.ext
    openssl x509 -req -sha256 -days 825 \
        -in secrets/mqtt/server.csr \
        -CA secrets/mqtt/ca.crt \
        -CAkey secrets/mqtt/ca.key \
        -CAcreateserial \
        -out secrets/mqtt/server.crt \
        -extfile secrets/mqtt/server.ext
    rm secrets/mqtt/server.csr secrets/mqtt/server.ext secrets/mqtt/ca.srl
fi
if [[ -f secrets/mqtt/ca.key ]]; then
    chmod 600 secrets/mqtt/ca.key
fi
chmod 600 secrets/mqtt/server.key
chmod 644 secrets/mqtt/ca.crt secrets/mqtt/server.crt

printf '%s\n' "Generated local secrets and TLS certificates."
printf '%s\n' "Initial admin username: $(grep '^BOOTSTRAP_ADMIN_USERNAME=' .env | cut -d= -f2-)"
printf '%s\n' "Read the generated admin password from the ignored .env file."
