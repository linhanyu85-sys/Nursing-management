# 本地基础设施一键启动
$ErrorActionPreference = "Stop"

$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Resolve-Path (Join-Path $ScriptRoot "..")

Push-Location $ProjectRoot
try {
  if (-not (Test-Path ".env.local")) {
    Copy-Item ".env.example" ".env.local"
    Write-Host "已创建 .env.local，请按需修改（包含模型路径与密钥）。" -ForegroundColor Yellow
  }

  docker compose --env-file .env.local -f docker-compose.local.yml up -d
  Write-Host "基础设施已启动：PostgreSQL/Qdrant/NATS/MinIO/pgAdmin" -ForegroundColor Green
} finally {
  Pop-Location
}
