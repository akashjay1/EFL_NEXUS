<#
.SYNOPSIS
    EFL_NEXUS (.NET 9 C#) Differential Patch Script
.DESCRIPTION
    Generates a differential patch ZIP comparing dist\EFL_NEXUS against a baseline release.
.PARAMETER Build
    Patch build number (e.g. 1).
.PARAMETER Version
    Optional target version string (e.g. 1.0.8).
.PARAMETER PrevZip
    Path to previous full-release ZIP.
.PARAMETER PrevDir
    Path to extracted previous release directory.
.PARAMETER AutoFindPrev
    Directory to scan for baseline ZIP (default: 'dist').
#>
[CmdletBinding(DefaultParameterSetName = 'AutoFind')]
param(
    [Parameter(Position = 0)]
    [int]$Build = -1,

    [string]$Version,

    [Parameter(ParameterSetName = 'PrevZip')]
    [string]$PrevZip,

    [Parameter(ParameterSetName = 'PrevDir')]
    [string]$PrevDir,

    [Parameter(ParameterSetName = 'AutoFind')]
    [string]$AutoFindPrev = 'dist'
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$pyScript = Join-Path $ScriptDir "create_patch.py"
$pythonArgs = @(
    $pyScript
)

if ($Build -ge 0) {
    $pythonArgs += @("--build", $Build.ToString())
}
if (![string]::IsNullOrWhiteSpace($Version)) {
    $pythonArgs += @("--version", $Version)
}

if (![string]::IsNullOrWhiteSpace($PrevZip)) {
    $pythonArgs += @("--prev-zip", $PrevZip)
} elseif (![string]::IsNullOrWhiteSpace($PrevDir)) {
    $pythonArgs += @("--prev-dir", $PrevDir)
} else {
    $pythonArgs += @("--auto-find-prev", $AutoFindPrev)
}

python @pythonArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Patch creation failed with exit code $LASTEXITCODE"
}
