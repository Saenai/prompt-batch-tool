#!/usr/bin/env powershell
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string]$Version,
    [string]$OutputDirectory = 'artifacts',
    [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$OutputEncoding = [Text.UTF8Encoding]::new($false)

$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$outputRoot = if ([IO.Path]::IsPathRooted($OutputDirectory)) {
    [IO.Path]::GetFullPath($OutputDirectory)
} else {
    [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputDirectory))
}
$safeVersion = $Version -replace '[^A-Za-z0-9._-]', '-'
if ([string]::IsNullOrWhiteSpace($safeVersion)) {
    throw 'Version does not contain a usable artifact identifier.'
}

$archiveName = "PromptBatchGenerator-$safeVersion-windows-x64"
$packagePath = Join-Path $outputRoot 'prompt-batch-tool'
$archivePath = Join-Path $outputRoot "$archiveName.zip"
$checksumPath = "$archivePath.sha256"
$temporaryRoot = Join-Path $outputRoot ".build-$PID-$([guid]::NewGuid().ToString('N'))"
$binaryDirectory = Join-Path $temporaryRoot 'bin'

New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
foreach ($target in @($packagePath, $archivePath, $checksumPath)) {
    if (Test-Path -LiteralPath $target) {
        $resolved = [IO.Path]::GetFullPath($target)
        if (-not $resolved.StartsWith($outputRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to replace output outside the selected directory: $resolved"
        }
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
New-Item -ItemType Directory -Path $binaryDirectory -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $temporaryRoot 'spec') -Force | Out-Null
New-Item -ItemType Directory -Path $packagePath -Force | Out-Null

try {
    Push-Location $projectRoot
    try {
        & $PythonExecutable -B -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
            --name PromptBatchGenerator --distpath $binaryDirectory `
            --workpath (Join-Path $temporaryRoot 'gui-work') --specpath (Join-Path $temporaryRoot 'spec') app.py
        if ($LASTEXITCODE -ne 0) { throw "GUI packaging failed with exit code $LASTEXITCODE" }

        & $PythonExecutable -B -m PyInstaller --noconfirm --clean --onefile --console --noupx `
            --name PromptBatchCLI --distpath $binaryDirectory `
            --workpath (Join-Path $temporaryRoot 'cli-work') --specpath (Join-Path $temporaryRoot 'spec') batch_cli.py
        if ($LASTEXITCODE -ne 0) { throw "CLI packaging failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }

    Copy-Item -LiteralPath (Join-Path $binaryDirectory 'PromptBatchGenerator.exe') -Destination $packagePath
    Copy-Item -LiteralPath (Join-Path $binaryDirectory 'PromptBatchCLI.exe') -Destination $packagePath
    New-Item -ItemType Directory -Path (Join-Path $packagePath 'config') -Force | Out-Null
    Copy-Item -LiteralPath (Join-Path $projectRoot 'config/app.json') -Destination (Join-Path $packagePath 'config/app.json')
    New-Item -ItemType Directory -Path (Join-Path $packagePath 'profiles') -Force | Out-Null
    foreach ($profile in @('plain.json', 'h3.json')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot "profiles/$profile") -Destination (Join-Path $packagePath "profiles/$profile")
    }
    foreach ($directory in @('schemas', 'docs', 'examples')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $directory) -Destination $packagePath -Recurse
    }
    foreach ($file in @('README.md', 'README.en.md', 'README.ja.md', 'CHANGELOG.md')) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $file) -Destination $packagePath
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'launch-gui.cmd') -Destination $packagePath

    $releaseConfigPath = Join-Path $packagePath 'config\app.json'
    $releaseConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $releaseConfigPath | ConvertFrom-Json
    $releaseConfig.paths.engine = '../PromptBatchCLI.exe'
    $releaseConfig | ConvertTo-Json -Depth 32 | Set-Content -Encoding UTF8 -LiteralPath $releaseConfigPath

    Compress-Archive -LiteralPath $packagePath -DestinationPath $archivePath -CompressionLevel Optimal
    $checksum = (Get-FileHash -Algorithm SHA256 -LiteralPath $archivePath).Hash.ToLowerInvariant()
    "$checksum  $([IO.Path]::GetFileName($archivePath))" | Set-Content -Encoding ASCII -LiteralPath $checksumPath

    [pscustomobject]@{
        PackageDirectory = $packagePath
        Archive = $archivePath
        Checksum = $checksumPath
    } | ConvertTo-Json
} finally {
    if (Test-Path -LiteralPath $temporaryRoot) {
        Remove-Item -LiteralPath $temporaryRoot -Recurse -Force
    }
}
