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
$utf8NoBom = [Text.UTF8Encoding]::new($false)
$callerDirectory = (Get-Location).Path

function Resolve-ExternalPath {
    param([string]$Value, [string]$BaseDirectory, [switch]$AllowEmpty)
    if ([string]::IsNullOrWhiteSpace($Value)) {
        if ($AllowEmpty) { return '' }
        throw 'A required path value is empty.'
    }
    $expanded = $Value -replace '\$\{([^}]+)\}', '%$1%'
    $expanded = [Environment]::ExpandEnvironmentVariables($expanded)
    if ($expanded -eq '~') { $expanded = [Environment]::GetFolderPath('UserProfile') }
    elseif ($expanded.StartsWith('~\') -or $expanded.StartsWith('~/')) {
        $expanded = Join-Path ([Environment]::GetFolderPath('UserProfile')) $expanded.Substring(2)
    }
    if ([IO.Path]::IsPathRooted($expanded)) { return [IO.Path]::GetFullPath($expanded) }
    return [IO.Path]::GetFullPath((Join-Path $BaseDirectory $expanded))
}

function Get-PropertyValue {
    param($Object, [string]$Name, $Default = $null)
    if ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name) { return $Object.$Name }
    return $Default
}

function Get-StringArray {
    param($Object, [string]$Name)
    $value = Get-PropertyValue $Object $Name @()
    if ($null -eq $value) { return @() }
    return @($value | ForEach-Object { [string]$_ })
}

function ConvertTo-SafeId {
    param([string]$Value, [int]$FallbackIndex)
    $safe = ($Value.Trim() -replace '[^\p{L}\p{Nd}._-]+', '-') -replace '^-+|-+$', ''
    if ([string]::IsNullOrWhiteSpace($safe)) { return ('input-{0:D2}' -f $FallbackIndex) }
    return $safe
}

function Get-TextSha256 {
    param([string]$Value)
    $sha = [Security.Cryptography.SHA256]::Create()
    try {
        return (($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($Value)) | ForEach-Object { $_.ToString('x2') }) -join '').ToUpperInvariant()
    } finally { $sha.Dispose() }
}

function Join-Endpoint {
    param([string]$RootUrl, [string]$Endpoint)
    return $RootUrl.TrimEnd('/') + '/' + $Endpoint.TrimStart('/')
}

function Test-Endpoint {
    param([string]$Uri)
    try { $null = Invoke-RestMethod -Uri $Uri -Method Get -TimeoutSec 5; return $true } catch { return $false }
}

function Invoke-JsonPost {
    param([string]$Uri, [string]$Json, [int]$TimeoutSeconds)
    $bytes = [Text.Encoding]::UTF8.GetBytes($Json)
    $response = Invoke-WebRequest -UseBasicParsing -Uri $Uri -Method Post -ContentType 'application/json; charset=utf-8' -Body $bytes -TimeoutSec $TimeoutSeconds
    return [string]$response.Content
}

function Test-OutputContract {
    param([string]$Content, $ProfileValidation, $ModeValidation)
    $required = @((Get-StringArray $ProfileValidation 'required_patterns') + (Get-StringArray $ModeValidation 'required_patterns'))
    $forbidden = @((Get-StringArray $ProfileValidation 'forbidden_patterns') + (Get-StringArray $ModeValidation 'forbidden_patterns'))
    foreach ($pattern in $required) { if ($Content -notmatch $pattern) { return $false } }
    foreach ($pattern in $forbidden) { if ($Content -match $pattern) { return $false } }
    return $true
}

foreach ($parameterName in @('AppConfigPath','ProfilePath','InputManifestPath')) {
    $value = Get-Variable -Name $parameterName -ValueOnly
    Set-Variable -Name $parameterName -Value (Resolve-ExternalPath $value $callerDirectory)
}
foreach ($requiredFile in @($AppConfigPath,$ProfilePath,$InputManifestPath)) {
    if (-not (Test-Path -LiteralPath $requiredFile -PathType Leaf)) { throw "Required file not found: $requiredFile" }
}
if ($Repeats -lt 1 -or $MaxTokens -lt 1) { throw 'Repeats and MaxTokens must be positive integers.' }
$modelIds = @($ModelIdsCsv -split ',' | ForEach-Object { $_.Trim() } | Where-Object { $_ } | Select-Object -Unique)
if ($modelIds.Count -lt 1) { throw 'At least one model must be selected.' }

$appConfigDirectory = Split-Path -Parent $AppConfigPath
$profileDirectory = Split-Path -Parent $ProfilePath
$manifestDirectory = Split-Path -Parent $InputManifestPath
$appConfig = Get-Content -Raw -Encoding UTF8 -LiteralPath $AppConfigPath | ConvertFrom-Json
$profile = Get-Content -Raw -Encoding UTF8 -LiteralPath $ProfilePath | ConvertFrom-Json
$inputManifest = Get-Content -Raw -Encoding UTF8 -LiteralPath $InputManifestPath | ConvertFrom-Json
if (-not $profile.id -or -not $profile.modes) { throw "Invalid profile: $ProfilePath" }
if ([string]$appConfig.backend.type -ne 'openai-chat-completions') { throw "Unsupported backend type: $($appConfig.backend.type)" }
$inputEntries = @($inputManifest.inputs)
if ($inputEntries.Count -lt 1) { throw 'Input manifest contains no inputs.' }

$paths = $appConfig.paths
$routerExecutable = Resolve-ExternalPath ([string]$paths.router_executable) $appConfigDirectory
$routerWorkingDirectory = Resolve-ExternalPath ([string]$paths.router_working_directory) $appConfigDirectory
$runtimeExecutable = Resolve-ExternalPath ([string]$paths.runtime_executable) $appConfigDirectory
$modelConfigPath = Resolve-ExternalPath ([string]$paths.model_config) $appConfigDirectory
if ([string]::IsNullOrWhiteSpace($OutputRoot)) { $OutputRoot = Resolve-ExternalPath ([string]$paths.default_output_root) $appConfigDirectory }
else { $OutputRoot = Resolve-ExternalPath $OutputRoot $callerDirectory }
if (-not [string]::IsNullOrWhiteSpace($RunDirectory)) { $RunDirectory = Resolve-ExternalPath $RunDirectory $callerDirectory }
if (-not [string]::IsNullOrWhiteSpace($SystemPromptPath)) { $SystemPromptPath = Resolve-ExternalPath $SystemPromptPath $callerDirectory }
$configuredBaseUrl = [string]$appConfig.backend.base_url
if ([string]::IsNullOrWhiteSpace($BaseUrl)) { $BaseUrl = $configuredBaseUrl }
$mayStartConfiguredRouter = ($BaseUrl.TrimEnd('/') -eq $configuredBaseUrl.TrimEnd('/'))

$profileSystemRoot = $profileDirectory
if ($profile.system_prompt_root) { $profileSystemRoot = Resolve-ExternalPath ([string]$profile.system_prompt_root) $profileDirectory }
$availableModes = @($profile.modes.PSObject.Properties.Name)
$requestedMode = $Mode.Trim()
if ($requestedMode -ne 'auto' -and $requestedMode -notin $availableModes) {
    throw "Mode '$requestedMode' is not defined by profile '$($profile.id)'."
}
if ($requestedMode -eq 'auto' -and -not [bool](Get-PropertyValue $profile 'allow_auto_mode' $false)) {
    $requestedMode = [string]$profile.default_mode
}

$usedIds = @{}
$cases = @()
$caseIndex = 0
foreach ($entry in $inputEntries) {
    $caseIndex++
    if ($entry.path) {
        $sourcePath = Resolve-ExternalPath ([string]$entry.path) $manifestDirectory
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Input file not found: $sourcePath" }
        $content = Get-Content -Raw -Encoding UTF8 -LiteralPath $sourcePath
        $sourceKind = 'file'
    } elseif ($null -ne $entry.content) {
        $sourcePath = $null; $content = [string]$entry.content; $sourceKind = 'inline'
    } else { throw "Input entry $caseIndex must contain path or content." }
    if ([string]::IsNullOrWhiteSpace($content)) { throw "Input entry $caseIndex is empty." }

    $baseId = ConvertTo-SafeId $(if ($entry.id) { [string]$entry.id } elseif ($sourcePath) { [IO.Path]::GetFileNameWithoutExtension($sourcePath) } else { '' }) $caseIndex
    $caseId = $baseId; $suffix = 2
    while ($usedIds.ContainsKey($caseId)) { $caseId = "$baseId-$suffix"; $suffix++ }
    $usedIds[$caseId] = $true

    if ($requestedMode -eq 'auto') {
        $detectionType = [string](Get-PropertyValue $profile.mode_detection 'type' 'none')
        if ($detectionType -eq 'first_nonempty_line') {
            $detected = (($content -split '\r?\n' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) } | Select-Object -First 1).Trim())
            $caseSensitive = [bool](Get-PropertyValue $profile.mode_detection 'case_sensitive' $false)
            $caseMode = if ($caseSensitive) { $detected } else { @($availableModes | Where-Object { $_.ToLowerInvariant() -eq $detected.ToLowerInvariant() })[0] }
            if (-not $caseMode) { throw "Cannot detect a configured mode from input '$caseId': $detected" }
        } else { $caseMode = [string]$profile.default_mode }
    } else { $caseMode = $requestedMode }
    $modeConfig = $profile.modes.$caseMode
    if ($null -eq $modeConfig) { throw "Mode configuration missing: $caseMode" }

    if ($SystemPromptPath) {
        $caseSystemPath = $SystemPromptPath
        $systemPrompt = Get-Content -Raw -Encoding UTF8 -LiteralPath $caseSystemPath
        $systemSource = 'explicit-override'
    } elseif ($modeConfig.system_prompt) {
        $caseSystemPath = Resolve-ExternalPath ([string]$modeConfig.system_prompt) $profileSystemRoot
        if (-not (Test-Path -LiteralPath $caseSystemPath -PathType Leaf)) { throw "System prompt not found: $caseSystemPath" }
        $systemPrompt = Get-Content -Raw -Encoding UTF8 -LiteralPath $caseSystemPath
        $systemSource = 'profile-file'
    } else {
        $caseSystemPath = $null
        $systemPrompt = [string](Get-PropertyValue $modeConfig 'system_prompt_text' '')
        $systemSource = 'profile-inline'
    }

    $observationItems = @()
    foreach ($observation in @($profile.observations)) {
        $matches = [regex]::Matches($content, [string]$observation.input_pattern)
        foreach ($match in $matches) {
            $textGroup = [int](Get-PropertyValue $observation 'text_group' 0)
            $markerGroup = [int](Get-PropertyValue $observation 'marker_group' 0)
            $observationItems += [pscustomobject]@{
                id = [string]$observation.id; text = $match.Groups[$textGroup].Value; marker = $match.Groups[$markerGroup].Value
                remove_marker_in_final = [bool](Get-PropertyValue $observation 'remove_marker_in_final' $false)
            }
        }
    }
    $cases += [pscustomobject]@{
        id=$caseId; mode=$caseMode; mode_config=$modeConfig; source_kind=$sourceKind; source_path=$sourcePath; content=$content
        input_sha256=(Get-TextSha256 $content); system_prompt_path=$caseSystemPath; system_prompt=$systemPrompt
        system_prompt_source=$systemSource; system_prompt_sha256=(Get-TextSha256 $systemPrompt); observations=$observationItems
    }
}

if ($ValidateOnly) {
    Write-Host "Validation OK: profile=$($profile.id), inputs=$($cases.Count), models=$($modelIds.Count)."
    foreach ($case in $cases) { Write-Host "  $($case.id): mode=$($case.mode), source=$($case.source_kind), system=$($case.system_prompt_source)" }
    return
}

$outputConfig = $profile.output
$runPrefix = [string](Get-PropertyValue $outputConfig 'run_prefix' $profile.id)
if (-not $RunDirectory) {
    $runId = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + $runPrefix + '-' + $cases.Count + 'inputs'
    $runDir = Join-Path $OutputRoot $runId
} else { $runDir = $RunDirectory; $runId = Split-Path -Leaf $runDir }
$inputDir = Join-Path $runDir 'input'; $systemDir = Join-Path $inputDir 'system-prompts'
$resultDir = Join-Path $runDir 'results'; $finalDir = Join-Path $runDir 'final-results'; $rawDir = Join-Path $runDir 'raw'; $logDir = Join-Path $runDir 'router-logs'
New-Item -ItemType Directory -Force -Path $inputDir,$systemDir,$resultDir,$finalDir,$rawDir,$logDir | Out-Null
Copy-Item -LiteralPath $AppConfigPath -Destination (Join-Path $inputDir 'app-config.json') -Force
Copy-Item -LiteralPath $ProfilePath -Destination (Join-Path $inputDir 'profile.json') -Force
Copy-Item -LiteralPath $InputManifestPath -Destination (Join-Path $inputDir 'input-manifest.json') -Force
foreach ($case in $cases) {
    [IO.File]::WriteAllText((Join-Path $inputDir ($case.id + '.txt')), $case.content, $utf8NoBom)
    [IO.File]::WriteAllText((Join-Path $systemDir ($case.id + '.txt')), $case.system_prompt, $utf8NoBom)
}

$modelsUri = Join-Endpoint $BaseUrl ([string]$appConfig.backend.models_endpoint)
$chatUri = Join-Endpoint $BaseUrl ([string]$appConfig.backend.chat_endpoint)
$requestTimeout = [int](Get-PropertyValue $appConfig.backend 'request_timeout_seconds' 3600)
$readinessTimeout = [int](Get-PropertyValue $appConfig.backend 'readiness_timeout_seconds' 60)
$managedNames = @($appConfig.router.managed_process_names | ForEach-Object { [string]$_ })
$preexistingPids = @(Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.ProcessName -in $managedNames } | ForEach-Object Id)
$startedRouter = $false
$records = [Collections.Generic.List[object]]::new(); $failures = [Collections.Generic.List[object]]::new()

try {
    if (-not (Test-Endpoint $modelsUri)) {
        if (-not $mayStartConfiguredRouter) { throw "Endpoint is unavailable and does not match the configured local router URL: $modelsUri" }
        if (-not (Test-Path -LiteralPath $routerExecutable -PathType Leaf)) { throw "Configured router executable not found: $routerExecutable" }
        $stdout = Join-Path $logDir 'router.stdout.log'; $stderr = Join-Path $logDir 'router.stderr.log'
        Start-Process -FilePath $routerExecutable -ArgumentList @($appConfig.router.arguments) -WorkingDirectory $routerWorkingDirectory `
            -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr | Out-Null
        $startedRouter = $true; $ready = $false
        for ($i=0; $i -lt $readinessTimeout; $i++) { if (Test-Endpoint $modelsUri) { $ready=$true; break }; Start-Sleep -Seconds 1 }
        if (-not $ready) { throw "Router did not become ready: $modelsUri" }
    }
    $available = (Invoke-RestMethod -Uri $modelsUri -Method Get -TimeoutSec 10).data | ForEach-Object { $_.id }
    $missing = @($modelIds | Where-Object { $_ -notin $available })
    if ($missing.Count) { throw "Models are not visible: $($missing -join ', ')" }

    $runtimeVersion = $null
    if (Test-Path -LiteralPath $runtimeExecutable -PathType Leaf) {
        $oldPreference=$ErrorActionPreference; $ErrorActionPreference='Continue'
        $runtimeVersion=(& $runtimeExecutable @($appConfig.runtime.version_arguments) 2>&1 | Out-String).Trim(); $ErrorActionPreference=$oldPreference
    }
    $manifest = [ordered]@{
        run_id=$runId; created_at=(Get-Date).ToString('o'); profile_id=[string]$profile.id; profile_path=$ProfilePath
        app_config_path=$AppConfigPath; endpoint=$BaseUrl; inputs=@($cases | ForEach-Object {
            [ordered]@{ id=$_.id; mode=$_.mode; source_kind=$_.source_kind; source_path=$_.source_path; input_sha256=$_.input_sha256
                system_prompt_path=$_.system_prompt_path; system_prompt_source=$_.system_prompt_source; system_prompt_sha256=$_.system_prompt_sha256 }
        }); models=$modelIds; repeats_per_input=$Repeats; input_count=$cases.Count; outputs_per_model=$Repeats*$cases.Count
        total_requested=$modelIds.Count*$Repeats*$cases.Count; max_tokens=$MaxTokens; seed_base=$SeedBase
        request_order='model -> repeat -> input'; router_started_by_script=$startedRouter; runtime_version=$runtimeVersion
    }
    [IO.File]::WriteAllText((Join-Path $runDir 'manifest.json'), ($manifest | ConvertTo-Json -Depth 12), $utf8NoBom)

    $modelIndex=0
    foreach ($modelId in $modelIds) {
        $modelIndex++; Write-Host "[$modelIndex/$($modelIds.Count)] $modelId"
        foreach ($repeat in 1..$Repeats) {
            $seed=$SeedBase+$repeat
            foreach ($case in $cases) {
                $caseResult=Join-Path (Join-Path $resultDir $modelId) $case.id
                $caseFinal=Join-Path (Join-Path $finalDir $modelId) $case.id
                $caseRaw=Join-Path (Join-Path $rawDir $modelId) $case.id
                New-Item -ItemType Directory -Force -Path $caseResult,$caseFinal,$caseRaw | Out-Null
                $stem='run-{0:D2}' -f $repeat
                $messages=@()
                if (-not [string]::IsNullOrEmpty($case.system_prompt)) { $messages += [ordered]@{role='system';content=$case.system_prompt} }
                $messages += [ordered]@{role='user';content=$case.content}
                $body=[ordered]@{}
                foreach($source in @($appConfig.backend.request_body,$profile.request_body,$case.mode_config.request_body)){
                    if($null -ne $source){foreach($property in $source.PSObject.Properties){$body[$property.Name]=$property.Value}}
                }
                $body['model']=$modelId; $body['messages']=$messages; $body['max_tokens']=$MaxTokens; $body['seed']=$seed; $body['stream']=$false
                $json=$body | ConvertTo-Json -Depth 10 -Compress
                $watch=[Diagnostics.Stopwatch]::StartNew()
                try {
                    $responseJson=Invoke-JsonPost $chatUri $json $requestTimeout; $watch.Stop()
                    [IO.File]::WriteAllText((Join-Path $caseRaw "$stem.json"),$responseJson,$utf8NoBom)
                    $response=$responseJson | ConvertFrom-Json; $message=$response.choices[0].message; $content=[string]$message.content
                    [IO.File]::WriteAllText((Join-Path $caseResult "$stem.md"),$content,$utf8NoBom)
                    if ($message.reasoning_content) { [IO.File]::WriteAllText((Join-Path $caseResult "$stem.reasoning.txt"),[string]$message.reasoning_content,$utf8NoBom) }
                    $finalContent=$content; $missing=@(); $retained=@()
                    foreach ($observation in $case.observations) {
                        if (-not $content.Contains($observation.text)) { $missing += "$($observation.id):$($observation.text)" }
                        if ($content.Contains($observation.marker)) {
                            $retained += "$($observation.id):$($observation.marker)"
                            if ($observation.remove_marker_in_final) { $finalContent=$finalContent.Replace($observation.marker,$observation.text) }
                        }
                    }
                    [IO.File]::WriteAllText((Join-Path $caseFinal "$stem.md"),$finalContent,$utf8NoBom)
                    $valid=Test-OutputContract $content $profile.validation $case.mode_config.validation
                    $records.Add([pscustomobject]@{
                        model=$modelId; input=$case.id; mode=$case.mode; repeat=$repeat; seed=$seed; success=$true; valid_output=$valid
                        observation_count=$case.observations.Count; observations_preserved=($missing.Count -eq 0); missing_observations=($missing -join ' | ')
                        markers_retained=($retained.Count -gt 0); retained_markers=($retained -join ' | '); finish_reason=[string]$response.choices[0].finish_reason
                        api_elapsed_seconds=[Math]::Round($watch.Elapsed.TotalSeconds,3)
                        generation_seconds=if($response.timings.predicted_ms){[Math]::Round([double]$response.timings.predicted_ms/1000,3)}else{$null}
                        generation_tokens_per_second=if($response.timings.predicted_per_second){[Math]::Round([double]$response.timings.predicted_per_second,3)}else{$null}
                        prompt_tokens=if($response.usage.prompt_tokens){[int]$response.usage.prompt_tokens}else{$null}
                        completion_tokens=if($response.usage.completion_tokens){[int]$response.usage.completion_tokens}else{$null}; output_characters=$content.Length
                    })
                    Write-Host "  $($case.id) $stem seed=$seed"
                } catch {
                    $watch.Stop(); [IO.File]::WriteAllText((Join-Path $caseRaw "$stem.error.txt"),$_.Exception.ToString(),$utf8NoBom)
                    $failures.Add([pscustomobject]@{model=$modelId;input=$case.id;repeat=$repeat;error=$_.Exception.Message})
                    $records.Add([pscustomobject]@{model=$modelId;input=$case.id;mode=$case.mode;repeat=$repeat;seed=$seed;success=$false;valid_output=$false
                        observation_count=$case.observations.Count;observations_preserved=$false;missing_observations='request_error';markers_retained=$false
                        retained_markers='';finish_reason='request_error';api_elapsed_seconds=[Math]::Round($watch.Elapsed.TotalSeconds,3)
                        generation_seconds=$null;generation_tokens_per_second=$null;prompt_tokens=$null;completion_tokens=$null;output_characters=$null})
                    Write-Warning "$modelId/$($case.id)/$stem failed: $($_.Exception.Message)"
                }
            }
        }
    }

    $recordsFile=[string](Get-PropertyValue $outputConfig 'records_file' 'BATCH-RECORDS.csv')
    $observationsFile=[string](Get-PropertyValue $outputConfig 'observations_file' 'OBSERVATIONS.csv')
    $allFile=[string](Get-PropertyValue $outputConfig 'all_outputs_file' 'ALL-OUTPUTS.md')
    $rawFile=[string](Get-PropertyValue $outputConfig 'raw_outputs_file' 'ALL-OUTPUTS-RAW.md')
    $summaryFile=[string](Get-PropertyValue $outputConfig 'summary_file' 'BATCH-SUMMARY.md')
    $records | Export-Csv -LiteralPath (Join-Path $runDir $recordsFile) -NoTypeInformation -Encoding UTF8
    $records | Select-Object model,input,mode,repeat,seed,success,valid_output,observation_count,observations_preserved,missing_observations,markers_retained,retained_markers |
        Export-Csv -LiteralPath (Join-Path $runDir $observationsFile) -NoTypeInformation -Encoding UTF8

    $title=[string](Get-PropertyValue $outputConfig 'aggregate_title' 'Prompt Batch Outputs')
    $finalLines=@("# $title",'',"- Profile: $($profile.display_name)","- Run directory: $runDir",'')
    $rawLines=@("# $title - Raw",'',"- Profile: $($profile.display_name)","- Run directory: $runDir",'')
    foreach($modelId in $modelIds){
        $finalLines += "# Model: $modelId",''; $rawLines += "# Model: $modelId",''
        foreach($case in $cases){
            $finalLines += "## Input: $($case.id) [$($case.mode)]",''; $rawLines += "## Input: $($case.id) [$($case.mode)]",''
            foreach($repeat in 1..$Repeats){
                $name='run-{0:D2}.md' -f $repeat
                $fp=Join-Path (Join-Path (Join-Path $finalDir $modelId) $case.id) $name
                $rp=Join-Path (Join-Path (Join-Path $resultDir $modelId) $case.id) $name
                $fc=if(Test-Path -LiteralPath $fp){(Get-Content -Raw -Encoding UTF8 -LiteralPath $fp).Trim()}else{'[MISSING RESULT]'}
                $rc=if(Test-Path -LiteralPath $rp){(Get-Content -Raw -Encoding UTF8 -LiteralPath $rp).Trim()}else{'[MISSING RESULT]'}
                $finalLines += ('### Result {0:D2}' -f $repeat),'','```text',$fc,'```',''
                $rawLines += ('### Result {0:D2}' -f $repeat),'','```text',$rc,'```',''
            }
        }
    }
    [IO.File]::WriteAllText((Join-Path $runDir $allFile),($finalLines -join [Environment]::NewLine),$utf8NoBom)
    [IO.File]::WriteAllText((Join-Path $runDir $rawFile),($rawLines -join [Environment]::NewLine),$utf8NoBom)

    $summaryTitle=[string](Get-PropertyValue $outputConfig 'summary_title' 'Prompt Batch Summary')
    $summary=@("# $summaryTitle",'',"- Profile: $($profile.display_name)","- Models: $($modelIds.Count)","- Inputs: $($cases.Count)",
        "- Repeats per input: $Repeats","- Total requested: $($modelIds.Count*$cases.Count*$Repeats)",'- Request order: model -> repeat -> input','',
        '| Model | HTTP | Valid | Gen avg (s) | Avg tok/s | Avg completion tokens |','|---|---:|---:|---:|---:|---:|')
    foreach($modelId in $modelIds){
        $rows=@($records|Where-Object model -eq $modelId); $ok=@($rows|Where-Object success); $valid=@($rows|Where-Object valid_output).Count; $den=$cases.Count*$Repeats
        if(-not $ok.Count){$summary += "| $modelId | 0/$den | 0/$den | - | - | - |"}else{
            $summary += ('| {0} | {1}/{2} | {3}/{2} | {4:F2} | {5:F2} | {6:F0} |' -f $modelId,$ok.Count,$den,$valid,
                (($ok|Measure-Object generation_seconds -Average).Average),(($ok|Measure-Object generation_tokens_per_second -Average).Average),
                (($ok|Measure-Object completion_tokens -Average).Average))
        }
    }
    [IO.File]::WriteAllText((Join-Path $runDir $summaryFile),($summary -join [Environment]::NewLine),$utf8NoBom)
    $manifest['failures']=@($failures); $manifest['output_files']=[ordered]@{all=$allFile;raw=$rawFile;records=$recordsFile;observations=$observationsFile;summary=$summaryFile}
    [IO.File]::WriteAllText((Join-Path $runDir 'manifest.json'),($manifest|ConvertTo-Json -Depth 12),$utf8NoBom)
} finally {
    if($startedRouter){
        Start-Sleep -Milliseconds 500
        Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Id -notin $preexistingPids -and $_.ProcessName -in $managedNames } |
            Stop-Process -Force -ErrorAction SilentlyContinue
    }
}

Write-Host "Completed: $runDir"
if($failures.Count){Write-Warning "Failures: $($failures.Count)";exit 2}
