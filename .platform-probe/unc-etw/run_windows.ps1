param(
    [Parameter(Mandatory=$true)][string]$Candidate,
    [Parameter(Mandatory=$true)][string]$RunDirectory
)
$ErrorActionPreference = 'Stop'
# Invoke only on the parent's fresh disposable Windows2022 runner.
if ($env:RUNNER_OS -ne 'Windows' -or $env:ImageOS -ne 'win22' -or $env:GITHUB_ACTIONS -ne 'true') {
    throw 'This recipe is restricted to the disposable GitHub Windows2022 job.'
}
$root = $PSScriptRoot
$candidatePath = (Resolve-Path -LiteralPath $Candidate).Path
if (Test-Path -LiteralPath $RunDirectory) { throw 'RunDirectory must be new.' }
$run = New-Item -ItemType Directory -Path $RunDirectory
$scratch = New-Item -ItemType Directory -Path (Join-Path $run.FullName 'scratch')
$build = New-Item -ItemType Directory -Path (Join-Path $run.FullName 'build')
$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
$vs = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ($LASTEXITCODE -ne 0 -or -not $vs) { throw 'Native x64 MSVC tools not found.' }
Import-Module (Join-Path $vs 'Common7\Tools\Microsoft.VisualStudio.DevShell.dll')
Enter-VsDevShell -VsInstallPath $vs -SkipAutomaticLocation -DevCmdArguments '-arch=x64 -host_arch=x64'
Push-Location $build.FullName
try {
    & cl.exe /nologo /EHsc /W4 /std:c++17 /D_CRT_SECURE_NO_WARNINGS `
        (Join-Path $root 'tcp_observer.cpp') /Fetcp_observer.exe /link advapi32.lib `
        2>&1 | Set-Content -LiteralPath (Join-Path $run.FullName 'build.log')
    if ($LASTEXITCODE -ne 0) { throw 'Native observer compile failed; see build.log.' }
} finally { Pop-Location }
$python = (Get-Command python.exe).Source
# Start-Process joins Arguments into a Windows command line; quote all path args.
function Quote-Path([string]$value) {
    if ($value.Contains('"') -or $value.EndsWith('\')) { throw 'Unsupported argument path.' }
    return '"' + $value + '"'
}
$arguments = @('-B', (Quote-Path (Join-Path $root 'unc_probe.py')),
    '--candidate', (Quote-Path $candidatePath),
    '--observer', (Quote-Path (Join-Path $build.FullName 'tcp_observer.exe')),
    '--work-dir', (Quote-Path $scratch.FullName),
    '--output', (Quote-Path (Join-Path $run.FullName 'evidence')))
$process = Start-Process -FilePath $python -ArgumentList $arguments -PassThru -NoNewWindow `
    -RedirectStandardOutput (Join-Path $run.FullName 'run.jsonl') `
    -RedirectStandardError (Join-Path $run.FullName 'run.stderr.log')
$ownedProcessHandle = $process.Handle # retain access to the exit status after termination
if (-not $process.WaitForExit(180000)) {
    $process.Kill() # only this owned orchestrator; helpers have independent timers
    $process.WaitForExit()
    '{"event":"summary","status":"INCOMPLETE","reason":"orchestrator deadline; cleanup unconfirmed; discard runner"}' |
        Add-Content -LiteralPath (Join-Path $run.FullName 'run.jsonl')
    exit 3
}
$process.WaitForExit()
Get-Content -LiteralPath (Join-Path $run.FullName 'run.jsonl')
if ($null -eq $process.ExitCode) { throw 'Owned process exit status unavailable; not a PASS.' }
exit $process.ExitCode
