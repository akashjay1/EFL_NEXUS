<#
.SYNOPSIS
    EFL_NEXUS (.NET 9 C#) Release Packaging Script
.DESCRIPTION
    Builds, stages, sanitizes, verifies, and packages EFL_NEXUS into a full release ZIP.
.PARAMETER Action
    Action to perform: 'build' (default), 'preflight', 'verify', 'sanitize', 'full-zip'.
.PARAMETER Version
    Optional version override (e.g. 1.0.8).
.PARAMETER Build
    Optional build number override (e.g. 0).
.PARAMETER IncludePdbs
    Include .pdb symbol files in release package.
#>
[CmdletBinding()]
param(
    [ValidateSet('build', 'preflight', 'verify', 'sanitize', 'full-zip')]
    [string]$Action = 'build',
    [string]$Version,
    [int]$Build = -1,
    [switch]$IncludePdbs,
    [switch]$SelfContained
)

$ErrorActionPreference = 'Stop'
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$pyScript = Join-Path $ScriptDir "build_release.py"
$pythonArgs = @(
    $pyScript,
    $Action
)

if (![string]::IsNullOrWhiteSpace($Version)) {
    $pythonArgs += @("--version", $Version)
}
if ($Build -ge 0) {
    $pythonArgs += @("--build", $Build.ToString())
}
if ($IncludePdbs) {
    $pythonArgs += "--include-pdbs"
}
if ($SelfContained) {
    $pythonArgs += "--self-contained"
}

python @pythonArgs
if ($LASTEXITCODE -ne 0) {
    Write-Error "Release packaging failed with exit code $LASTEXITCODE"
}
