# Standalone experiment recipe. Native-unrun. Never merge into product CI.
# Invoke only in a dedicated, disposable GitHub-hosted windows-2022 job.
[CmdletBinding()]
param(
    [switch]$AcknowledgeDisposableRunner,
    [switch]$StopServerForSinks
)
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if (-not $AcknowledgeDisposableRunner -or -not $IsWindows -or
    $env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_ENVIRONMENT -ne 'github-hosted' -or
    $env:RUNNER_OS -ne 'Windows' -or -not $env:RUNNER_TEMP) {
    throw 'Requires explicit acknowledgement in a disposable GitHub-hosted Windows job; never run on a desktop or self-hosted runner.'
}
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = [Security.Principal.WindowsPrincipal]::new($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'This recipe requires the hosted runner administrator token.'
}
$probe = Join-Path $PSScriptRoot 'windows_relative_probe.py'
$evidence = Join-Path $env:RUNNER_TEMP ('probe1297-rerun-' + [guid]::NewGuid().ToString('N'))
$scratch = Join-Path $evidence 'scratch'
New-Item -ItemType Directory -Path $scratch | Out-Null
# Makes the evidence path available to a subsequent always() artifact step.
"probe1297_evidence=$evidence" | Out-File -FilePath $env:GITHUB_ENV -Append -Encoding utf8
Write-Output "evidence=$evidence"
Start-Transcript -Path (Join-Path $evidence 'recipe-transcript.txt') | Out-Null
$probeExit = 1
try {
    python -c "import sys, platform, struct; print(sys.version); print(platform.platform()); assert sys.platform == 'win32' and sys.version_info >= (3, 11) and struct.calcsize('P') == 8" 1> "$evidence/platform.txt" 2> "$evidence/platform-stderr.txt"
    if ($LASTEXITCODE -ne 0) { throw 'Requires native Windows Python 3.11+ x64.' }
    Copy-Item -LiteralPath $probe -Destination "$evidence/source.py"
    Get-FileHash -LiteralPath $probe -Algorithm SHA256 | Format-List | Out-File "$evidence/source-sha256.txt"
    Get-Service -Name LanmanServer,LanmanWorkstation | Format-List Name,Status,DependentServices,ServicesDependedOn | Out-File "$evidence/services-before.txt"
    & netstat.exe -ano -p tcp > "$evidence/tcp-before.txt"
    & sc.exe query srvnet > "$evidence/srvnet-before.txt"
    & netsh.exe interface ipv4 show excludedportrange protocol=tcp > "$evidence/excluded-ports.txt"
    if ($StopServerForSinks) {
        # Only the SMB server is eligible. No -Force, dependent service stops,
        # driver changes, client/redirector changes, registry edits, or reboot.
        try {
            Stop-Service -Name LanmanServer -ErrorAction Stop
            Write-Output 'LanmanServer stopped; port release still requires successful exclusive binds.'
        } catch {
            Write-Output "LanmanServer stop failed; keep the diagnostic probe outcome: $_"
        }
    }
    Get-Service -Name LanmanServer,LanmanWorkstation | Format-List Name,Status | Out-File "$evidence/services-after.txt"
    & netstat.exe -ano -p tcp > "$evidence/tcp-after.txt"
    & sc.exe query srvnet > "$evidence/srvnet-after.txt"
    python -B $probe --work-dir $scratch --timeout 90 1> "$evidence/result.jsonl" 2> "$evidence/stderr.txt"
    $probeExit = $LASTEXITCODE
    $probeExit | Out-File "$evidence/exit-code.txt"
    Get-Content "$evidence/result.jsonl"
    Get-Content "$evidence/stderr.txt"
} finally {
    Stop-Transcript | Out-Null
}
# Dispose of the VM after artifact collection. Service restoration is deliberately
# not a desktop workflow. SKIP=3 remains nonzero; no 'allow skip' conversion.
exit $probeExit
