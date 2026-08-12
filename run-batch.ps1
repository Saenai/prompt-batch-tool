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
    [Parameter(Mandatory = $true)] [int]$SeedBase,
    [Parameter(Mandatory = $true)] [string]$ModelIdsCsv,
    [switch]$ValidateOnly
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
    '--max-tokens', [string]$MaxTokens,
    '--seed-base', [string]$SeedBase
)
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

& $python.Source @arguments
exit $LASTEXITCODE
