$ErrorActionPreference = "Stop"

$repository = "manojfor4u/auto-apply"
$workflow = "update-naukri.yml"
$gh = "C:\Program Files\GitHub CLI\gh.exe"
$logDirectory = Join-Path $env:LOCALAPPDATA "NaukriProfileAutomation"
$logPath = Join-Path $logDirectory "dispatch.log"

New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null

function Write-DispatchLog {
    param([string]$Message)

    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss zzz"), $Message
    Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
}

try {
    if ((Get-TimeZone).Id -ne "India Standard Time") {
        throw "Windows timezone must be India Standard Time for hourly dispatch."
    }

    $now = Get-Date
    if ($now.Hour -lt 8 -or $now.Hour -gt 20) {
        Write-DispatchLog "Outside the 08:00-20:59 IST dispatch window; no action."
        exit 0
    }

    if (-not (Test-Path -LiteralPath $gh)) {
        throw "GitHub CLI was not found at $gh."
    }

    $authOutput = & $gh auth status 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub CLI is not authenticated: $($authOutput -join ' ')"
    }

    $runsJson = & $gh api `
        "repos/$repository/actions/workflows/$workflow/runs?branch=main&per_page=100"
    if ($LASTEXITCODE -ne 0) {
        throw "Could not read the profile workflow run history."
    }

    $runHistory = $runsJson | ConvertFrom-Json
    $runs = @($runHistory.workflow_runs)
    $hourStart = (Get-Date).Date.AddHours($now.Hour)
    $hasUpdateThisHour = $false
    foreach ($run in $runs) {
        if ($run.head_branch -ne "main") {
            continue
        }

        $runTime = [DateTimeOffset]::Parse($run.created_at).LocalDateTime
        if ($runTime -lt $hourStart -or $runTime -ge $hourStart.AddHours(1)) {
            continue
        }

        if (
            $run.status -in @("queued", "in_progress") -or
            $run.conclusion -eq "success"
        ) {
            $hasUpdateThisHour = $true
            break
        }
    }

    if ($hasUpdateThisHour) {
        Write-DispatchLog "An active or successful workflow run already exists this IST hour; skipping."
        exit 0
    }

    $dispatchOutput = & $gh workflow run $workflow `
        --repo $repository --ref main -f dry_run=false 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub workflow dispatch failed: $($dispatchOutput -join ' ')"
    }

    Write-DispatchLog "Dispatched profile workflow: $($dispatchOutput -join ' ')"
    exit 0
}
catch {
    Write-DispatchLog "ERROR: $($_.Exception.Message)"
    exit 1
}
