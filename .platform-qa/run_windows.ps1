$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows' -or $env:GITHUB_REF -ne 'refs/heads/probe/windows-artifact-http-1aff') {
    throw 'This recipe is only for its disposable hosted Windows qualification branch.'
}
$Python = Join-Path $PWD '.venv\Scripts\python.exe'
$Evidence = Join-Path $env:RUNNER_TEMP 'artifact-http-evidence'
$Scratch = Join-Path $env:RUNNER_TEMP 'artifact-http-scratch'
New-Item -ItemType Directory -Force -Path $Evidence, $Scratch | Out-Null
$Head = git rev-parse HEAD
$Tree = git rev-parse 'HEAD^{tree}'
@{ sha=$Head; tree=$Tree; os=$env:RUNNER_OS; runner=$env:RUNNER_NAME; purpose='real HTTP consumer qualification; no release or installation' } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Evidence 'identity.json')
& $Python -I -c 'import sys,platform,sqlite3; print(sys.executable); print(sys.version); print(platform.platform()); print("SQLite",sqlite3.sqlite_version)' *> (Join-Path $Evidence 'interpreter.txt')
$Suite = @(
    'tests/test_task_file_serving.py', 'tests/test_task_download_confinement.py',
    'tests/test_task_source_confined_qa.py', 'tests/test_task_write_authority_qa.py',
    'tests/test_headless_task_artifacts.py', 'tests/test_review_source_handles.py',
    'tests/test_delegated_activity_source.py', 'tests/test_chat_attachments.py', 'tests/test_chat_upload.py',
    'tests/test_evidence_pack_fixes.py', 'tests/test_evidence_packs.py',
    'tests/test_materialize_artifacts_contract.py', 'tests/test_source_retention_links.py', 'tests/test_platform_guard.py',
    'tests/test_task_summary.py',
    'tests/test_headless_task_api.py::test_task_api_enqueue_workspace_creates_child_drive',
    'tests/test_tool_access_matrix_closure.py::test_the_closure_added_no_write_like_operation_anywhere'
)
& $Python -I -S scripts/safe_test.py --temp-parent $Scratch --evidence-dir (Join-Path $Evidence 'safe-test') --timeout 600 -- $Python -m pytest @Suite -q --tb=short -o junit_family=xunit1 "--junitxml=$Evidence/focused.xml" *> (Join-Path $Evidence 'launcher-full.log')
$Result = $LASTEXITCODE
@{ exit_code=$Result; finished_utc=[DateTime]::UtcNow.ToString('o') } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $Evidence 'exit.json')
Get-Content (Join-Path $Evidence 'launcher-full.log')
exit $Result
