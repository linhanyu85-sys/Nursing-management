param(
  [string]$Username = "linmeili",
  [string]$DepartmentCode = "dep-card-01",
  [int]$BedStart = 1,
  [int]$BedEnd = 40,
  [ValidateSet("auto", "file", "api")]
  [string]$SourceMode = "auto",
  [string]$SourcePath = "",
  [string]$HisApiBaseUrl = "",
  [string]$HisApiPathTemplate = "/api/his/users/{username}/beds",
  [string]$HisApiToken = "",
  [int]$HisApiTimeoutSec = 20,
  [string]$OutputDir = "",
  [switch]$DryRun,
  [switch]$SkipRangeVerify,
  [string]$ContainerName = "ai_nursing_postgres",
  [string]$Db = "ai_nursing",
  [string]$DbUser = "postgres",
  [int]$ApiGatewayPort = 8000,
  [int]$DeviceGatewayPort = 8013,
  [int]$PatientContextPort = 28002
)

$ErrorActionPreference = "Stop"
$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

function Load-EnvFile {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return }
  Get-Content $Path | ForEach-Object {
    $line = $_.Trim()
    if (-not $line -or $line.StartsWith("#")) { return }
    $parts = $line.Split("=", 2)
    if ($parts.Count -ne 2) { return }
    $key = $parts[0].Trim()
    $value = $parts[1].Trim()
    if (-not $key) { return }
    if (-not [Environment]::GetEnvironmentVariable($key, "Process")) {
      [Environment]::SetEnvironmentVariable($key, $value, "Process")
    }
  }
}

function Pick-Value {
  param(
    [object]$Row,
    [string[]]$Keys
  )
  foreach ($key in $Keys) {
    if ($Row.PSObject.Properties.Name -contains $key) {
      $value = $Row.$key
      if ($null -eq $value) { continue }
      $text = [string]$value
      if (-not [string]::IsNullOrWhiteSpace($text)) {
        return $text.Trim()
      }
    }
  }
  return $null
}

function Normalize-BedNo {
  param([string]$RawBedNo)
  if ([string]::IsNullOrWhiteSpace($RawBedNo)) { return $null }
  $trimmed = $RawBedNo.Trim()
  if ($trimmed -match '(\d{1,4})') {
    return ([int]$Matches[1]).ToString()
  }
  $cleaned = ($trimmed -replace '[^0-9A-Za-z\-]', '')
  if ([string]::IsNullOrWhiteSpace($cleaned)) { return $null }
  return $cleaned
}

function Normalize-Row {
  param([object]$Row)
  $bedNo = Normalize-BedNo (Pick-Value -Row $Row -Keys @("bed_no", "bedNo", "bed", "bed_id", "bedId", "bed_number", "ward_bed_no", "bedNoText"))
  $fullName = Pick-Value -Row $Row -Keys @("full_name", "fullName", "name", "patient_name", "patientName")
  $mrn = Pick-Value -Row $Row -Keys @("mrn", "MRN", "patient_mrn", "medical_record_no", "medical_record_number")
  $inpatientNo = Pick-Value -Row $Row -Keys @("inpatient_no", "inpatientNo", "admission_no", "admissionNo", "visit_no", "hospitalization_no")
  if (-not $mrn -and $inpatientNo) {
    $mrn = "AUTO-" + $inpatientNo
  }
  $roomNo = Pick-Value -Row $Row -Keys @("room_no", "roomNo", "room", "room_id", "roomId", "room_number")
  $gender = Pick-Value -Row $Row -Keys @("gender", "sex")
  $age = Pick-Value -Row $Row -Keys @("age")
  $birthDate = Pick-Value -Row $Row -Keys @("birth_date", "birthDate", "dob", "date_of_birth")
  $chiefComplaint = Pick-Value -Row $Row -Keys @("chief_complaint", "chiefComplaint")
  $admissionDiagnosis = Pick-Value -Row $Row -Keys @("admission_diagnosis", "admissionDiagnosis", "diagnosis", "primary_diagnosis")

  return [PSCustomObject]@{
    bed_no = $bedNo
    room_no = $roomNo
    mrn = $mrn
    inpatient_no = $inpatientNo
    full_name = $fullName
    gender = $gender
    age = $age
    birth_date = $birthDate
    chief_complaint = $chiefComplaint
    admission_diagnosis = $admissionDiagnosis
  }
}
function Read-RecordsFromFile {
  param([string]$Path)
  $ext = [System.IO.Path]::GetExtension($Path).ToLower()
  switch ($ext) {
    ".csv" {
      return @(Import-Csv -Path $Path -Encoding UTF8)
    }
    ".json" {
      $raw = Get-Content -Raw -Path $Path -Encoding UTF8
      $obj = ConvertFrom-Json -InputObject $raw -Depth 20
      if ($obj -is [System.Array]) { return @($obj) }
      foreach ($key in @("records", "rows", "data", "items", "result")) {
        if ($obj.PSObject.Properties.Name -contains $key) {
          $value = $obj.$key
          if ($value -is [System.Array]) { return @($value) }
          if ($null -ne $value) { return @($value) }
        }
      }
      return @($obj)
    }
    ".jsonl" {
      $lines = Get-Content -Path $Path -Encoding UTF8
      $rows = @()
      foreach ($line in $lines) {
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $rows += (ConvertFrom-Json -InputObject $line -Depth 20)
      }
      return $rows
    }
    default {
      throw "Unsupported source format: $ext (supported: csv/json/jsonl)."
    }
  }
}

function Normalize-Rows {
  param([object[]]$Rows)
  $normalized = New-Object System.Collections.Generic.List[object]
  foreach ($row in $Rows) {
    $item = Normalize-Row -Row $row
    if (-not $item.bed_no) { continue }
    if (-not $item.full_name) { continue }
    if (-not $item.mrn) { continue }
    $normalized.Add($item) | Out-Null
  }
  if ($normalized.Count -eq 0) {
    return @()
  }
  return $normalized.ToArray()
}

function Get-Coverage {
  param(
    [object[]]$Rows,
    [int]$Start,
    [int]$End
  )
  $unique = @{}
  foreach ($row in $Rows) {
    $bed = [string]$row.bed_no
    if (-not [string]::IsNullOrWhiteSpace($bed)) {
      $unique[$bed] = $true
    }
  }

  $missing = New-Object System.Collections.Generic.List[string]
  for ($i = $Start; $i -le $End; $i++) {
    $key = $i.ToString()
    if (-not $unique.ContainsKey($key)) {
      $missing.Add($key) | Out-Null
    }
  }

  return [PSCustomObject]@{
    total_rows = $Rows.Count
    unique_beds = $unique.Keys.Count
    missing = @($missing)
    missing_count = $missing.Count
    full_covered = ($missing.Count -eq 0)
  }
}

function Discover-BestSourceFile {
  param(
    [string]$Root,
    [int]$Start,
    [int]$End
  )
  if (-not (Test-Path $Root)) { return $null }
  $files = Get-ChildItem -Path $Root -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension.ToLower() -in @(".csv", ".json", ".jsonl") }
  if (-not $files) { return $null }

  $best = $null
  foreach ($file in $files) {
    try {
      $rows = Read-RecordsFromFile -Path $file.FullName
      $normalized = Normalize-Rows -Rows $rows
      if (-not $normalized -or $normalized.Count -eq 0) { continue }
      $coverage = Get-Coverage -Rows $normalized -Start $Start -End $End
      $candidate = [PSCustomObject]@{
        path = $file.FullName
        rows = $normalized
        coverage = $coverage
      }
      if (-not $best) {
        $best = $candidate
        continue
      }
      if ($candidate.coverage.full_covered -and -not $best.coverage.full_covered) {
        $best = $candidate
        continue
      }
      if ($candidate.coverage.unique_beds -gt $best.coverage.unique_beds) {
        $best = $candidate
        continue
      }
      if ($candidate.coverage.unique_beds -eq $best.coverage.unique_beds -and $file.LastWriteTime -gt (Get-Item $best.path).LastWriteTime) {
        $best = $candidate
      }
    } catch {
      continue
    }
  }
  return $best
}

function Merge-SourceFiles {
  param(
    [string]$Root,
    [int]$Start,
    [int]$End
  )
  if (-not (Test-Path $Root)) { return $null }
  $files = Get-ChildItem -Path $Root -File -ErrorAction SilentlyContinue |
    Where-Object { $_.Extension.ToLower() -in @(".csv", ".json", ".jsonl") } |
    Sort-Object LastWriteTime
  if (-not $files) { return $null }

  $byBed = @{}
  $usedFiles = New-Object System.Collections.Generic.List[string]
  foreach ($file in $files) {
    try {
      $rows = Read-RecordsFromFile -Path $file.FullName
      $normalized = Normalize-Rows -Rows $rows
      if (-not $normalized -or $normalized.Count -eq 0) { continue }
      $usedFiles.Add($file.FullName) | Out-Null
      foreach ($row in $normalized) {
        $byBed[[string]$row.bed_no] = $row
      }
    } catch {
      continue
    }
  }

  if ($byBed.Keys.Count -eq 0) { return $null }
  $merged = @($byBed.Keys | Sort-Object {
      if ($_ -match '^\d+$') { [int]$_ } else { 9999 }
    }, {
      $_
    } | ForEach-Object { $byBed[$_] })
  $coverage = Get-Coverage -Rows $merged -Start $Start -End $End
  return [PSCustomObject]@{
    path = "merged-files"
    rows = $merged
    coverage = $coverage
    files_used = @($usedFiles)
  }
}

function New-QueryString {
  param([hashtable]$Params)
  $pairs = @()
  foreach ($key in $Params.Keys) {
    $value = $Params[$key]
    if ($null -eq $value) { continue }
    $text = [string]$value
    if ([string]::IsNullOrWhiteSpace($text)) { continue }
    $pairs += ("{0}={1}" -f [Uri]::EscapeDataString([string]$key), [Uri]::EscapeDataString($text))
  }
  if ($pairs.Count -eq 0) { return "" }
  return "?" + ($pairs -join "&")
}

function Fetch-RowsFromApi {
  param(
    [string]$BaseUrl,
    [string]$PathTemplate,
    [string]$User,
    [string]$DepCode,
    [int]$Start,
    [int]$End,
    [string]$Token,
    [int]$TimeoutSec
  )
  if ([string]::IsNullOrWhiteSpace($BaseUrl)) {
    throw "HIS_API_BASE_URL is empty."
  }
  $base = $BaseUrl.TrimEnd("/")
  $path = ($PathTemplate -replace "\{username\}", $User)
  if (-not $path.StartsWith("/")) { $path = "/" + $path }
  $url = $base + $path
  $headers = @{}
  if (-not [string]::IsNullOrWhiteSpace($Token)) {
    $headers["Authorization"] = "Bearer $Token"
  }

  $params = @{
    username = $User
    department_code = $DepCode
    bed_start = $Start
    bed_end = $End
  }
  $url = $url + (New-QueryString -Params $params)
  $response = Invoke-RestMethod -Method Get -Uri $url -Headers $headers -TimeoutSec $TimeoutSec -ErrorAction Stop

  if ($response -is [System.Array]) { return @($response) }
  foreach ($key in @("records", "rows", "data", "items", "result")) {
    if ($response.PSObject.Properties.Name -contains $key) {
      $value = $response.$key
      if ($value -is [System.Array]) { return @($value) }
      if ($null -ne $value) { return @($value) }
    }
  }
  return @($response)
}

if ($BedStart -gt $BedEnd) {
  $tmp = $BedStart
  $BedStart = $BedEnd
  $BedEnd = $tmp
}

Load-EnvFile -Path (Join-Path $projectRoot ".env.local")

if (-not $HisApiBaseUrl) { $HisApiBaseUrl = [Environment]::GetEnvironmentVariable("HIS_API_BASE_URL", "Process") }
if (-not $HisApiPathTemplate) { $HisApiPathTemplate = [Environment]::GetEnvironmentVariable("HIS_API_PATH_TEMPLATE", "Process") }
if (-not $HisApiToken) { $HisApiToken = [Environment]::GetEnvironmentVariable("HIS_API_TOKEN", "Process") }

if (-not $OutputDir) {
  $OutputDir = Join-Path $projectRoot "data\his_import\synced"
}
if (-not (Test-Path $OutputDir)) {
  New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
}

$selectedSourceLabel = ""
$normalizedRows = @()

if ($SourceMode -eq "file") {
  if (-not $SourcePath) { throw "SourceMode=file requires -SourcePath." }
  if (-not (Test-Path $SourcePath)) { throw "SourcePath not found: $SourcePath" }
  $normalizedRows = Normalize-Rows -Rows (Read-RecordsFromFile -Path (Resolve-Path $SourcePath).Path)
  $selectedSourceLabel = "file:$SourcePath"
}
elseif ($SourceMode -eq "api") {
  $apiRows = Fetch-RowsFromApi -BaseUrl $HisApiBaseUrl -PathTemplate $HisApiPathTemplate -User $Username -DepCode $DepartmentCode -Start $BedStart -End $BedEnd -Token $HisApiToken -TimeoutSec $HisApiTimeoutSec
  $normalizedRows = Normalize-Rows -Rows $apiRows
  $selectedSourceLabel = "api:$HisApiBaseUrl$HisApiPathTemplate"
}
else {
  if ($SourcePath -and (Test-Path $SourcePath)) {
    $sourceRows = Normalize-Rows -Rows (Read-RecordsFromFile -Path (Resolve-Path $SourcePath).Path)
    $sourceCoverage = Get-Coverage -Rows $sourceRows -Start $BedStart -End $BedEnd
    $normalizedRows = $sourceRows
    $selectedSourceLabel = "file:$SourcePath"
    if ((-not $sourceCoverage.full_covered) -and $HisApiBaseUrl) {
      try {
        $apiRows = Fetch-RowsFromApi -BaseUrl $HisApiBaseUrl -PathTemplate $HisApiPathTemplate -User $Username -DepCode $DepartmentCode -Start $BedStart -End $BedEnd -Token $HisApiToken -TimeoutSec $HisApiTimeoutSec
        $apiNormalized = Normalize-Rows -Rows $apiRows
        $apiCoverage = Get-Coverage -Rows $apiNormalized -Start $BedStart -End $BedEnd
        if ($apiCoverage.full_covered -or $apiNormalized.Count -gt $normalizedRows.Count) {
          $normalizedRows = $apiNormalized
          $selectedSourceLabel = "api:$HisApiBaseUrl$HisApiPathTemplate"
        }
      } catch {
        Write-Host ("[sync] API fallback failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
      }
    }
  } else {
    $sourceRoot = Join-Path $projectRoot "data\his_import"
    $best = Discover-BestSourceFile -Root $sourceRoot -Start $BedStart -End $BedEnd
    $merged = Merge-SourceFiles -Root $sourceRoot -Start $BedStart -End $BedEnd
    if ($best -and $merged) {
      if ($merged.coverage.full_covered -and -not $best.coverage.full_covered) {
        $normalizedRows = @($merged.rows)
        $selectedSourceLabel = "auto-merged-files"
      } elseif ($merged.coverage.unique_beds -gt $best.coverage.unique_beds) {
        $normalizedRows = @($merged.rows)
        $selectedSourceLabel = "auto-merged-files"
      } else {
        $normalizedRows = @($best.rows)
        $selectedSourceLabel = "auto-file:$($best.path)"
      }
    } elseif ($merged) {
      $normalizedRows = @($merged.rows)
      $selectedSourceLabel = "auto-merged-files"
    } elseif ($best) {
      $normalizedRows = @($best.rows)
      $selectedSourceLabel = "auto-file:$($best.path)"
    }

    if (($normalizedRows.Count -eq 0 -or (Get-Coverage -Rows $normalizedRows -Start $BedStart -End $BedEnd).full_covered -eq $false) -and $HisApiBaseUrl) {
      try {
        $apiRows = Fetch-RowsFromApi -BaseUrl $HisApiBaseUrl -PathTemplate $HisApiPathTemplate -User $Username -DepCode $DepartmentCode -Start $BedStart -End $BedEnd -Token $HisApiToken -TimeoutSec $HisApiTimeoutSec
        $apiNormalized = Normalize-Rows -Rows $apiRows
        if ($apiNormalized.Count -gt $normalizedRows.Count) {
          $normalizedRows = $apiNormalized
          $selectedSourceLabel = "auto-api:$HisApiBaseUrl$HisApiPathTemplate"
        }
      } catch {
        Write-Host ("[sync] API source failed: {0}" -f $_.Exception.Message) -ForegroundColor Yellow
      }
    }
  }
}

if (-not $normalizedRows -or $normalizedRows.Count -eq 0) {
  throw "No HIS rows resolved. Provide -SourcePath or set HIS_API_BASE_URL (+ optional HIS_API_TOKEN)."
}

$coverage = Get-Coverage -Rows $normalizedRows -Start $BedStart -End $BedEnd
Write-Host ("[sync] source: {0}" -f $selectedSourceLabel) -ForegroundColor Cyan
Write-Host ("[sync] rows={0} unique_beds={1} missing={2}" -f $coverage.total_rows, $coverage.unique_beds, $coverage.missing_count) -ForegroundColor Cyan
if (-not $coverage.full_covered) {
  Write-Host ("[sync] missing beds: {0}" -f ($coverage.missing -join ",")) -ForegroundColor Yellow
  throw "Source does not fully cover bed range ${BedStart}-${BedEnd}. Aborted."
}

$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$outCsv = Join-Path $OutputDir ("his_full_sync_{0}_{1}.csv" -f $Username, $stamp)
$normalizedRows | Select-Object bed_no,room_no,mrn,inpatient_no,full_name,gender,age,birth_date,chief_complaint,admission_diagnosis |
  Export-Csv -Path $outCsv -NoTypeInformation -Encoding UTF8

Write-Host ("[sync] wrote normalized source: {0}" -f $outCsv) -ForegroundColor Green

if ($DryRun) {
  Write-Host "[sync] dry-run only, import skipped." -ForegroundColor Yellow
  exit 0
}

$importScript = Join-Path $projectRoot "scripts\import_his_cases_to_postgres.ps1"
if (-not (Test-Path $importScript)) { throw "import script missing: $importScript" }

& powershell -ExecutionPolicy Bypass -File $importScript `
  -SourcePath $outCsv `
  -Username $Username `
  -DepartmentCode $DepartmentCode `
  -RequireFullBedRange `
  -BedStart $BedStart `
  -BedEnd $BedEnd `
  -ClearDepartmentBeds `
  -ContainerName $ContainerName `
  -Db $Db `
  -DbUser $DbUser

if ($LASTEXITCODE -ne 0) {
  throw "HIS import failed with exit code: $LASTEXITCODE"
}

if ($SkipRangeVerify) {
  Write-Host "[sync] import completed. range verification skipped by parameter." -ForegroundColor Yellow
  exit 0
}

$verifyScript = Join-Path $projectRoot "scripts\verify_competition_e2e.ps1"
if (-not (Test-Path $verifyScript)) { throw "verify script missing: $verifyScript" }

$requestedBy = if ($Username.StartsWith("u_")) { $Username } else { "u_$Username" }
& powershell -ExecutionPolicy Bypass -File $verifyScript `
  -ApiGatewayPort $ApiGatewayPort `
  -DeviceGatewayPort $DeviceGatewayPort `
  -PatientContextPort $PatientContextPort `
  -Username $Username `
  -RequestedBy $requestedBy `
  -BedCoverageMode "range" `
  -BedStart $BedStart `
  -BedEnd $BedEnd

if ($LASTEXITCODE -ne 0) {
  throw "Range verification failed. See docs/competition_preflight_report.md."
}

Write-Host "[sync] HIS full sync + range verification completed successfully." -ForegroundColor Green

