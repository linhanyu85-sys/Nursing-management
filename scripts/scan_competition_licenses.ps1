param(
  [string]$OutMarkdown = "docs/competition_open_source_inventory.md",
  [string]$OutJson = "data/compliance/license_scan.json",
  [switch]$FailOnRestricted
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $projectRoot

function Read-TextSample {
  param([string]$Path)
  if (-not (Test-Path $Path)) { return "" }
  try {
    return (Get-Content -Path $Path -Encoding UTF8 -TotalCount 400) -join "`n"
  } catch {
    try {
      return (Get-Content -Path $Path -TotalCount 400) -join "`n"
    } catch {
      return ""
    }
  }
}

function Infer-LicenseId {
  param([string]$Text)
  $textSafe = ""
  if ($null -ne $Text) { $textSafe = [string]$Text }
  $t = $textSafe.ToLowerInvariant()
  if (-not $t) { return "UNKNOWN" }
  if ($t -match "apache license" -or $t -match "apache-2\\.0" -or $t -match "apache 2\\.0") { return "Apache-2.0" }
  if ($t -match "mit license") { return "MIT" }
  if ($t -match "bsd license" -or $t -match "bsd-3" -or $t -match "bsd-2") { return "BSD" }
  if ($t -match "mozilla public license" -or $t -match "mpl-2\\.0") { return "MPL-2.0" }
  if ($t -match "lgpl") { return "LGPL" }
  if ($t -match "agpl") { return "AGPL" }
  if ($t -match "gpl") { return "GPL" }
  if ($t -match "sspl") { return "SSPL" }
  if ($t -match "health-ai-developer-foundations" -or $t -match "terms of use") { return "CUSTOM-TERMS" }
  return "UNKNOWN"
}

function Infer-Risk {
  param(
    [string]$LicenseId,
    [string]$Text
  )
  $textSafe = ""
  if ($null -ne $Text) { $textSafe = [string]$Text }
  $t = $textSafe.ToLowerInvariant()
  if ($t -match "non-commercial|not for commercial|research only|for research|academic use|仅供研究|不得商用|禁止商用") {
    return "restricted"
  }
  if ($LicenseId -in @("AGPL", "GPL", "SSPL", "CUSTOM-TERMS")) {
    return "restricted"
  }
  if ($LicenseId -eq "UNKNOWN") {
    return "review_required"
  }
  return "ok"
}

function To-RelPath {
  param([string]$Path)
  $full = [System.IO.Path]::GetFullPath($Path)
  $root = [System.IO.Path]::GetFullPath("$projectRoot")
  if ($full.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
    return $full.Substring($root.Length).TrimStart([char[]]@([char]92, [char]47))
  }
  return $full
}

$records = New-Object System.Collections.Generic.List[object]

# 1) Reused open-source bases
$ossRoot = Join-Path $projectRoot "open_source_bases"
if (Test-Path $ossRoot) {
  Get-ChildItem -Path $ossRoot -Directory | ForEach-Object {
    $name = $_.Name
    $dir = $_.FullName
    $licenseFile = Get-ChildItem -Path $dir -File -Recurse -Include "LICENSE*", "COPYING*", "NOTICE*" -ErrorAction SilentlyContinue |
      Sort-Object FullName |
      Select-Object -First 1
    $readmeFile = Get-ChildItem -Path $dir -File -Recurse -Include "README*" -ErrorAction SilentlyContinue |
      Sort-Object FullName |
      Select-Object -First 1
    $evidencePath = if ($licenseFile) { $licenseFile.FullName } elseif ($readmeFile) { $readmeFile.FullName } else { $dir }
    $sample = Read-TextSample -Path $evidencePath
    $licenseId = Infer-LicenseId -Text $sample
    $risk = Infer-Risk -LicenseId $licenseId -Text $sample
    $records.Add([PSCustomObject]@{
      component = $name
      type = "open_source_base"
      license = $licenseId
      risk = $risk
      evidence = (To-RelPath $evidencePath)
      notes = if ($licenseFile) { "license_file" } elseif ($readmeFile) { "readme_only" } else { "missing_license_text" }
    }) | Out-Null
  }
}

# 2) Model assets (competition risk hotspot)
$modelRoot = Join-Path $projectRoot "ai model"
if (Test-Path $modelRoot) {
  Get-ChildItem -Path $modelRoot -Directory | Where-Object { $_.Name -notmatch '^\.venv' } | ForEach-Object {
    $name = $_.Name
    $dir = $_.FullName
    $licenseFile = Get-ChildItem -Path $dir -File -Recurse -Include "LICENSE*", "COPYING*", "NOTICE*" -ErrorAction SilentlyContinue |
      Sort-Object FullName |
      Select-Object -First 1
    $readmeFile = Get-ChildItem -Path $dir -File -Recurse -Include "README*" -ErrorAction SilentlyContinue |
      Sort-Object FullName |
      Select-Object -First 1
    $evidencePath = if ($licenseFile) { $licenseFile.FullName } elseif ($readmeFile) { $readmeFile.FullName } else { $dir }
    $sample = Read-TextSample -Path $evidencePath
    $licenseId = Infer-LicenseId -Text $sample
    $risk = Infer-Risk -LicenseId $licenseId -Text $sample
    $records.Add([PSCustomObject]@{
      component = $name
      type = "model_asset"
      license = $licenseId
      risk = $risk
      evidence = (To-RelPath $evidencePath)
      notes = if ($licenseFile) { "license_file" } elseif ($readmeFile) { "readme_only" } else { "missing_license_text" }
    }) | Out-Null
  }
}

# 3) Runtime dependency manifests (manual follow-up reminder)
Get-ChildItem -Path (Join-Path $projectRoot "services") -Directory -ErrorAction SilentlyContinue | ForEach-Object {
  $req = Join-Path $_.FullName "requirements.txt"
  if (-not (Test-Path $req)) { return }
  $pkgs = Get-Content -Path $req | ForEach-Object { ($_ -split '#')[0].Trim() } | Where-Object { $_ } | Measure-Object | Select-Object -ExpandProperty Count
  $records.Add([PSCustomObject]@{
    component = $_.Name
    type = "python_manifest"
    license = "UNRESOLVED"
    risk = "review_required"
    evidence = (To-RelPath $req)
    notes = "requirements_count=$pkgs"
  }) | Out-Null
}

# 4) Mobile dependency manifest
$mobilePkg = Join-Path $projectRoot "apps/mobile/package.json"
if (Test-Path $mobilePkg) {
  $records.Add([PSCustomObject]@{
    component = "mobile-app"
    type = "node_manifest"
    license = "UNRESOLVED"
    risk = "review_required"
    evidence = (To-RelPath $mobilePkg)
    notes = "npm dependencies require separate SPDX export"
  }) | Out-Null
}

$recordsSorted = $records | Sort-Object risk, type, component
$summary = [PSCustomObject]@{
  generated_at = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss zzz")
  total = $recordsSorted.Count
  ok = @($recordsSorted | Where-Object { $_.risk -eq "ok" }).Count
  review_required = @($recordsSorted | Where-Object { $_.risk -eq "review_required" }).Count
  restricted = @($recordsSorted | Where-Object { $_.risk -eq "restricted" }).Count
}

$outJsonAbs = Join-Path $projectRoot $OutJson
$outJsonDir = Split-Path -Parent $outJsonAbs
if (-not (Test-Path $outJsonDir)) { New-Item -ItemType Directory -Path $outJsonDir | Out-Null }

$payload = [PSCustomObject]@{
  summary = $summary
  records = @($recordsSorted)
}
$payload | ConvertTo-Json -Depth 8 | Set-Content -Path $outJsonAbs -Encoding UTF8

$outMdAbs = Join-Path $projectRoot $OutMarkdown
$outMdDir = Split-Path -Parent $outMdAbs
if (-not (Test-Path $outMdDir)) { New-Item -ItemType Directory -Path $outMdDir | Out-Null }

$lines = New-Object System.Collections.Generic.List[string]
$lines.Add("# Competition Open-Source Inventory") | Out-Null
$lines.Add("") | Out-Null
$lines.Add("Generated at: $($summary.generated_at)") | Out-Null
$lines.Add("") | Out-Null
$lines.Add("- Total components: $($summary.total)") | Out-Null
$lines.Add("- OK: $($summary.ok)") | Out-Null
$lines.Add("- Review required: $($summary.review_required)") | Out-Null
$lines.Add("- Restricted: $($summary.restricted)") | Out-Null
$lines.Add("") | Out-Null
$lines.Add("| Component | Type | License | Risk | Evidence | Notes |") | Out-Null
$lines.Add("|---|---|---|---|---|---|") | Out-Null
foreach ($row in $recordsSorted) {
  $line = "| {0} | {1} | {2} | {3} | `{4}` | {5} |" -f $row.component, $row.type, $row.license, $row.risk, $row.evidence, $row.notes
  $lines.Add($line) | Out-Null
}
$lines -join "`n" | Set-Content -Path $outMdAbs -Encoding UTF8

Write-Host "[scan] wrote: $OutMarkdown" -ForegroundColor Green
Write-Host "[scan] wrote: $OutJson" -ForegroundColor Green
Write-Host ("[scan] summary: total={0}, ok={1}, review_required={2}, restricted={3}" -f $summary.total, $summary.ok, $summary.review_required, $summary.restricted) -ForegroundColor Cyan

if ($FailOnRestricted -and $summary.restricted -gt 0) {
  throw "Restricted licenses/terms detected. Resolve before competition submission."
}
