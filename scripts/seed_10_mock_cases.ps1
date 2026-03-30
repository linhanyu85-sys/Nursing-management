param(
  [string]$ProjectRoot = "",
  [string]$PgHost = "localhost",
  [int]$Port = 5432,
  [string]$Db = "ai_nursing",
  [string]$User = "postgres",
  [string]$Password = "postgres"
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
  $ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}

$sqlPath = Join-Path $ProjectRoot "infra\postgres\init\002_seed_10_mock_cases.sql"
if (-not (Test-Path $sqlPath)) {
  throw "Seed SQL not found: $sqlPath"
}

$psql = (Get-Command psql -ErrorAction SilentlyContinue)
if ($psql) {
  $env:PGPASSWORD = $Password
  & $psql.Source -v ON_ERROR_STOP=1 -h $PgHost -p $Port -U $User -d $Db -f $sqlPath
  if ($LASTEXITCODE -ne 0) {
    throw "psql execute failed"
  }
  Write-Host "[OK] Seed finished by psql." -ForegroundColor Green
  exit 0
}

$docker = (Get-Command docker -ErrorAction SilentlyContinue)
if ($docker) {
  $container = "ai_nursing_postgres"
  $running = & $docker.Source ps --filter "name=$container" --format "{{.Names}}"
  if ($running -contains $container) {
    & $docker.Source exec -e PGPASSWORD=$Password $container psql -v ON_ERROR_STOP=1 -U $User -d $Db -f "/docker-entrypoint-initdb.d/002_seed_10_mock_cases.sql"
    if ($LASTEXITCODE -eq 0) {
      Write-Host "[OK] Seed finished by docker exec." -ForegroundColor Green
      exit 0
    }
  }
}

Write-Host "[WARN] 未检测到可用 PostgreSQL 客户端/容器，未能执行入库。" -ForegroundColor Yellow
Write-Host "请先启动数据库后再执行：.\\scripts\\seed_10_mock_cases.ps1" -ForegroundColor Yellow
exit 1
