# Parent-dispatched disposable Windows 2022 runner only. Never run on an owner PC.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceRoot,
    [Parameter(Mandatory)][string]$Python,
    [Parameter(Mandatory)][string]$Uv,
    [string]$ExpectedRef = 'refs/heads/probe/windows-cli-1677-1aff',
    [string]$WorkRoot = '',
    [string]$EngineVersion = '4.4.0',
    [string]$EngineBuild = 'df0f5c03d9f9d5d18736662fd98e6a79368feecb',
    [string]$NodeVersion = '24.16.0',
    [string]$SourceLock = (Join-Path $PSScriptRoot 'source-lock.json')
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or $env:ImageOS -ne 'win22' -or $env:GITHUB_REF -ne $ExpectedRef) {
    throw 'Refused: use the explicitly selected secretless hosted Windows 2022 branch, not a local/owner machine.'
}
$SourceRoot = (Resolve-Path -LiteralPath $SourceRoot).Path
$Python = (Resolve-Path -LiteralPath $Python).Path
$Uv = (Resolve-Path -LiteralPath $Uv).Path
$SourceLock = (Resolve-Path -LiteralPath $SourceLock).Path
$Probe = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot 'qualify_windows_1677.py')).Path
if (-not $WorkRoot) { $WorkRoot = Join-Path $env:SystemDrive ('\o1677-' + [guid]::NewGuid().ToString('N').Substring(0,8)) }
if (-not [IO.Path]::IsPathRooted($WorkRoot) -or (Test-Path -LiteralPath $WorkRoot)) { throw 'WorkRoot must be a NEW absolute disposable prefix.' }
# Source and execution roots must not overlap. The Python probe/safe_test also check Git ancestry.
$FullRoot = [IO.Path]::GetFullPath($WorkRoot).TrimEnd('\')
if ($FullRoot.StartsWith($SourceRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or $FullRoot -eq $SourceRoot) { throw 'WorkRoot is in source.' }
New-Item -ItemType Directory -Path $FullRoot | Out-Null
$Upload = Join-Path $FullRoot 'upload'
$Private = Join-Path $FullRoot 'private'
$Scratch = Join-Path $FullRoot 'scratch'
New-Item -ItemType Directory -Path $Upload,$Private,$Scratch | Out-Null
$GitHubOutput = $env:GITHUB_OUTPUT
# Only this allowlisted directory is ever uploaded; raw stdout, daemon homes,
# descriptors, databases, archives, npm logs and safe_test exports are NOT uploaded.
if ($GitHubOutput) { "evidence=$Upload" | Out-File -FilePath $GitHubOutput -Encoding utf8 -Append }
@{ purpose='native Windows 2022 #1677 qualification, not release'; ref=$env:GITHUB_REF; sha=$env:GITHUB_SHA; image=$env:ImageOS; source=$SourceRoot; work=$FullRoot; native_execution='NOT_RUN' } |
    ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Upload 'runner.json')
$Original = @{}
Get-ChildItem Env: | ForEach-Object { $Original[$_.Name] = $_.Value }
$Exit = 2
$SafeStarted = $false
try {
    # Full replacement, rather than a blacklist over an owner's credential set.
    Get-ChildItem Env: | ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name,$null,'Process') }
    $Clean = @{
        'SystemRoot'=$Original['SystemRoot']; 'WINDIR'=$Original['WINDIR'];
        'ComSpec'=(Join-Path $Original['SystemRoot'] 'System32\cmd.exe');
        'PATH'=(Join-Path $Original['SystemRoot'] 'System32'); 'PATHEXT'='.COM;.EXE;.BAT;.CMD';
        'HOME'=(Join-Path $FullRoot 'setup-home'); 'USERPROFILE'=(Join-Path $FullRoot 'setup-home');
        'APPDATA'=(Join-Path $FullRoot 'setup-home\appdata'); 'LOCALAPPDATA'=(Join-Path $FullRoot 'setup-home\localappdata');
        'XDG_CONFIG_HOME'=(Join-Path $FullRoot 'setup-home\config'); 'XDG_CACHE_HOME'=(Join-Path $FullRoot 'setup-home\cache');
        'XDG_DATA_HOME'=(Join-Path $FullRoot 'setup-home\data'); 'XDG_STATE_HOME'=(Join-Path $FullRoot 'setup-home\state');
        'CLAUDEXOR_CONFIG_DIR'=(Join-Path $FullRoot 'setup-home\claudexor'); 'CLAUDE_CONFIG_DIR'=(Join-Path $FullRoot 'setup-home\claude');
        'CODEX_HOME'=(Join-Path $FullRoot 'setup-home\codex'); 'COPILOT_HOME'=(Join-Path $FullRoot 'setup-home\copilot');
        'TMP'=(Join-Path $FullRoot 'tmp'); 'TEMP'=(Join-Path $FullRoot 'tmp'); 'TMPDIR'=(Join-Path $FullRoot 'tmp');
        'UV_CACHE_DIR'=(Join-Path $FullRoot 'uv-cache'); 'UV_PROJECT_ENVIRONMENT'=(Join-Path $FullRoot 'venv');
        'UV_PYTHON_DOWNLOADS'='never'; 'PYTHONNOUSERSITE'='1'; 'PYTHONDONTWRITEBYTECODE'='1';
        'PIP_CONFIG_FILE'='NUL'; 'GIT_CONFIG_NOSYSTEM'='1'; 'GIT_CONFIG_GLOBAL'='NUL'
    }
    foreach ($Key in $Original.Keys) {
        if ($Key -match '^(OURO_(INSTALL|TASK|RUN)_SCOPE_[0-9a-fA-F]+|OURO_PROC_CONTAINER_[A-Za-z0-9_]+)$' -and $Original[$Key] -eq '1') { $Clean[$Key] = $Original[$Key] }
    }
    foreach ($Key in $Clean.Keys) { [Environment]::SetEnvironmentVariable($Key,$Clean[$Key],'Process') }
    foreach ($Name in @('HOME','APPDATA','LOCALAPPDATA','XDG_CONFIG_HOME','XDG_CACHE_HOME','XDG_DATA_HOME','XDG_STATE_HOME','CLAUDEXOR_CONFIG_DIR','CLAUDE_CONFIG_DIR','CODEX_HOME','COPILOT_HOME','TMP')) {
        New-Item -ItemType Directory -Force -Path $Clean[$Name] | Out-Null
    }
    & $Uv --version *> (Join-Path $Private 'uv-version.log')
    if ($LASTEXITCODE -ne 0 -or (Get-Content -Raw (Join-Path $Private 'uv-version.log')) -notmatch '^uv 0\.12\.1\b') { throw 'uv 0.12.1 is required.' }
    # Dependency-only environment outside the product tree; never editable install.
    & $Uv sync --locked --group dev --no-install-project --project $SourceRoot --python $Python *> (Join-Path $Private 'dependency-sync.log')
    if ($LASTEXITCODE -ne 0) { throw 'Locked dependency sync failed; see retained private runner log.' }
    $VenvPython = Join-Path $FullRoot 'venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $VenvPython)) { throw 'Dependency-only Python is missing.' }
    $SafeStarted = $true
    # Native probe's 900s cooperative work budget leaves 600s before safe_test's
    # 1500s hard tree deadline for native cancellation, stop and result export.
    & $VenvPython -I -S (Join-Path $SourceRoot 'scripts\safe_test.py') --temp-parent $Scratch --evidence-dir (Join-Path $Private 'safe-test') --timeout 1500 -- $VenvPython -I $Probe --source-root $SourceRoot --source-lock $SourceLock --output (Join-Path $Upload 'probe') --engine-version $EngineVersion --engine-build $EngineBuild --node-version $NodeVersion --work-seconds 900 --operation-seconds 240 *> (Join-Path $Private 'launcher.log')
    $Exit = $LASTEXITCODE
}
catch {
    # Exception text can contain private process/environment data. Keep it only
    # in the disposable prefix, not workflow stdout or the upload directory.
    $_ | Out-String | Set-Content -Encoding utf8 (Join-Path $Private 'wrapper-error.log')
    $Exit = 2
}
finally {
    $SafeRows = @()
    $SafePath = Join-Path $Private 'safe-test'
    if (Test-Path -LiteralPath $SafePath) {
        foreach ($File in (Get-ChildItem -LiteralPath $SafePath -Recurse -Depth 1 -File -Filter 'result.json')) {
            try {
                $Raw = Get-Content -Raw -LiteralPath $File.FullName | ConvertFrom-Json
                if ($Raw.command -notcontains $Probe) { continue }
                $SafeRows += @{ returncode=$Raw.returncode; execution=$Raw.execution; stopped=$Raw.stopped; containment_reported_error=[bool]$Raw.containment_error; evidence_reported_error=[bool]$Raw.evidence_error; source_gap_present=[bool]$Raw.source_gap; released_count=@($Raw.cleanup.released).Count; retained_count=@($Raw.cleanup.retained).Count }
            } catch { $SafeRows += @{ result_unreadable=$true } }
        }
    }
    $ProbeState = 'missing'
    $ProbePath = Join-Path $Upload 'probe\receipt.json'
    if (Test-Path -LiteralPath $ProbePath) {
        try { $ProbeState = (Get-Content -Raw -LiteralPath $ProbePath | ConvertFrom-Json).outcome } catch { $ProbeState = 'unreadable' }
    }
    if ($Exit -eq 0 -and ($ProbeState -ne 'PASS' -or $SafeRows.Count -ne 1 -or $SafeRows[0].containment_reported_error -or $SafeRows[0].evidence_reported_error -or $SafeRows[0].returncode -ne 0)) { $Exit = 3 }
    @{ exit_code=$Exit; probe_outcome=$ProbeState; safe_test_started=$SafeStarted; safe_test_results=$SafeRows; missing_probe_receipt_means='partial/unknown, never PASS'; raw_logs_exported=$false; private_prefix_retained=$true; finished_utc=[DateTime]::UtcNow.ToString('o') } |
        ConvertTo-Json -Depth 12 | Set-Content -Encoding utf8 (Join-Path $Upload 'controller.json')
    # Nothing is recursively deleted by this recipe. safe_test alone classifies
    # its own scratch. Hosted VM disposal is not a claim of graceful cleanup.
    Get-ChildItem Env: | ForEach-Object { [Environment]::SetEnvironmentVariable($_.Name,$null,'Process') }
    foreach ($Key in $Original.Keys) { [Environment]::SetEnvironmentVariable($Key,$Original[$Key],'Process') }
    Write-Host "Qualification exit=$Exit; upload contains only runner.json, controller.json and probe/receipt.json."
}
exit $Exit
