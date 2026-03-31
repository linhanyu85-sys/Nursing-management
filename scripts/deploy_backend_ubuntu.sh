#!/usr/bin/env bash
set -euo pipefail

if [[ "${EUID}" -ne 0 ]]; then
  echo "Please run as root." >&2
  exit 1
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/.env.server"
LOG_DIR="${PROJECT_ROOT}/logs"
VENV_DIR="${PROJECT_ROOT}/.venv"

install_docker() {
  if command -v docker >/dev/null 2>&1; then
    return
  fi

  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc

  local arch
  arch="$(dpkg --print-architecture)"
  local codename
  codename="$(. /etc/os-release && echo "${VERSION_CODENAME}")"

  cat >/etc/apt/sources.list.d/docker.list <<EOF
deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${codename} stable
EOF
}

write_unit() {
  local name="$1"
  local service_path="$2"
  local port="$3"
  local unit_file="/etc/systemd/system/ai-nursing-${name}.service"

  cat >"${unit_file}" <<EOF
[Unit]
Description=AI Nursing ${name}
After=network.target docker.service
Wants=docker.service

[Service]
Type=simple
WorkingDirectory=${PROJECT_ROOT}/${service_path}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_DIR}/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port ${port}
Restart=always
RestartSec=3
StandardOutput=append:${LOG_DIR}/${name}.out.log
StandardError=append:${LOG_DIR}/${name}.err.log

[Install]
WantedBy=multi-user.target
EOF
}

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing ${ENV_FILE}. Copy .env.server.example to .env.server and fill secrets first." >&2
  exit 1
fi

set -a
# Load server-specific ports and secrets so generated units match the active deployment.
source "${ENV_FILE}"
set +a

SERVICES=(
  "audit-service:services/audit-service:${AUDIT_SERVICE_PORT:-8007}"
  "auth-service:services/auth-service:${AUTH_SERVICE_PORT:-8012}"
  "patient-context-service:services/patient-context-service:${PATIENT_CONTEXT_SERVICE_PORT:-8002}"
  "agent-orchestrator:services/agent-orchestrator:${AGENT_ORCHESTRATOR_SERVICE_PORT:-8003}"
  "handover-service:services/handover-service:${HANDOVER_SERVICE_PORT:-8004}"
  "recommendation-service:services/recommendation-service:${RECOMMENDATION_SERVICE_PORT:-8005}"
  "document-service:services/document-service:${DOCUMENT_SERVICE_PORT:-8006}"
  "asr-service:services/asr-service:${ASR_SERVICE_PORT:-8008}"
  "tts-service:services/tts-service:${TTS_SERVICE_PORT:-8009}"
  "multimodal-med-service:services/multimodal-med-service:${MULTIMODAL_MED_SERVICE_PORT:-8010}"
  "collaboration-service:services/collaboration-service:${COLLAB_SERVICE_PORT:-8011}"
  "device-gateway:services/device-gateway:${DEVICE_GATEWAY_PORT:-8013}"
  "api-gateway:services/api-gateway:${API_GATEWAY_PORT:-8000}"
)

mkdir -p "${LOG_DIR}"

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y \
  software-properties-common \
  curl \
  ca-certificates \
  gnupg \
  lsb-release \
  git \
  unzip \
  ffmpeg \
  espeak-ng \
  libsndfile1 \
  build-essential \
  pkg-config \
  python3 \
  python3-venv \
  python3-pip

install_docker
apt-get update
apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
systemctl enable --now docker

docker compose --env-file "${ENV_FILE}" -f "${PROJECT_ROOT}/docker-compose.local.yml" up -d postgres qdrant nats minio

if [[ ! -d "${VENV_DIR}" ]]; then
  python3 -m venv "${VENV_DIR}"
fi

source "${VENV_DIR}/bin/activate"
python -m pip install --upgrade pip setuptools wheel

while IFS= read -r requirements_file; do
  python -m pip install -r "${requirements_file}"
done < <(find "${PROJECT_ROOT}/services" -name requirements.txt | sort)

for entry in "${SERVICES[@]}"; do
  IFS=":" read -r name service_path port <<<"${entry}"
  write_unit "${name}" "${service_path}" "${port}"
done

systemctl daemon-reload

for entry in "${SERVICES[@]}"; do
  IFS=":" read -r name _port_path _port <<<"${entry}"
  systemctl enable "ai-nursing-${name}.service"
  systemctl restart "ai-nursing-${name}.service"
done

sleep 8

echo
echo "API gateway health:"
curl -fsS "http://127.0.0.1:${API_GATEWAY_PORT:-8000}/health"
echo
echo
echo "Runtime health:"
curl -fsS "http://127.0.0.1:${API_GATEWAY_PORT:-8000}/api/ai/runtime"
echo
