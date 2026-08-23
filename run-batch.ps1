#!/usr/bin/env powershell
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$AppConfigPath,
    [Parameter(Mandatory = $true)] [string]$ProfilePath,
    [Parameter(Mandatory = $true)] [string]$InputManifestPath,
    [string]$Mode = 'auto',
    [string]$SystemPromptPath = '',
    [string]$BaseUrl = '',
    [string]$OutputRoot = '',
    [string]$RunDirectory = '',
    [Parameter(Mandatory = $true)] [int]$Repeats,
    [Parameter(Mandatory = $true)] [int]$MaxTokens,
    [Nullable[int]]$SeedBase = $null,
    [Parameter(Mandatory = $true)] [string]$ModelIdsCsv,
    [switch]$RandomSeed,
    [switch]$NoRandomSeed,
    [switch]$ValidateOnly,
    [switch]$Resume,
    [switch]$RetryFailed
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

$cli = Join-Path $PSScriptRoot 'batch_cli.py'
if (-not (Test-Path -LiteralPath $cli -PathType Leaf)) {
    throw "Python batch CLI not found: $cli"
}
$python = Get-Command python.exe -ErrorAction SilentlyContinue
if (-not $python) { $python = Get-Command python -ErrorAction SilentlyContinue }
if (-not $python) { throw 'Python executable not found in PATH.' }

$arguments = @(
    '-B', $cli,
    '--app-config', $AppConfigPath,
    '--profile', $ProfilePath,
    '--input-manifest', $InputManifestPath,
    '--mode', $Mode,
    '--repeats', [string]$Repeats,
    '--max-tokens', [string]$MaxTokens
)
if ($RandomSeed -and $NoRandomSeed) { throw 'RandomSeed and NoRandomSeed are mutually exclusive.' }
if ($RandomSeed -and $null -ne $SeedBase) { throw 'SeedBase cannot be combined with RandomSeed.' }
if ($RandomSeed) {
    $arguments += '--random-seed'
} elseif ($NoRandomSeed) {
    $arguments += '--no-random-seed'
    if ($null -ne $SeedBase) { $arguments += '--seed-base', [string]$SeedBase }
} elseif ($null -ne $SeedBase) {
    $arguments += '--seed-base', [string]$SeedBase
}
foreach ($modelId in @($ModelIdsCsv -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
    $arguments += '--model', $modelId
}
foreach ($pair in @(
    @('--system-prompt', $SystemPromptPath),
    @('--base-url', $BaseUrl),
    @('--output-root', $OutputRoot),
    @('--run-directory', $RunDirectory)
)) {
    if (-not [string]::IsNullOrWhiteSpace([string]$pair[1])) { $arguments += [string]$pair[0], [string]$pair[1] }
}
if ($ValidateOnly) { $arguments += '--validate-only' }
if ($Resume -and $RetryFailed) { throw 'Resume and RetryFailed are mutually exclusive.' }
if ($Resume) { $arguments += '--resume' }
if ($RetryFailed) { $arguments += '--retry-failed' }

& $python.Source @arguments
exit $LASTEXITCODE
