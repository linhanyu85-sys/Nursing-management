# Root bootstrap entrypoint
$ScriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $ScriptRoot 'scripts\bootstrap_local_stack.ps1')
