<#
  Export the local demo data (portfolio, trades, alerts, chats, reviews, research notes)
  so the AWS server can show it - including in inspect mode.

  Export only (creates .\finsight_demo.dump):
      powershell -ExecutionPolicy Bypass -File .\deploy\export_demo_data.ps1

  Export, upload and import on the server in one go:
      powershell -ExecutionPolicy Bypass -File .\deploy\export_demo_data.ps1 -Upload `
          -Server 3.94.163.86 -KeyFile $HOME\Downloads\finsight.pem

  Needs the local database running (start_app.ps1 starts it). The server keeps a backup of
  its previous data in ~/finance_agent/backups/ (see deploy/import_demo_data.sh).
#>
param(
    [switch]$Upload,
    [string]$Server = "",
    [string]$KeyFile = "$HOME\Downloads\finsight.pem",
    [string]$User = "ubuntu",
    [string]$RemoteDir = "~/finance_agent",
    [string]$Container = "finsight_db",
    [string]$DbUser = "postgres",
    [string]$Database = "finsight",
    [string]$Out = "finsight_demo.dump"
)

$ErrorActionPreference = "Continue"   # native tools write progress to stderr; check $LASTEXITCODE instead
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Step($m) { Write-Host "`n==> $m" -ForegroundColor Cyan }
function Fail($m) { Write-Host "ERROR: $m" -ForegroundColor Red; exit 1 }

$tables = Get-Content (Join-Path $PSScriptRoot "demo_tables.txt") | Where-Object { $_ -and -not $_.Trim().StartsWith("#") } | ForEach-Object { $_.Trim() }

Step "Checking the local database ($Container)"
$running = docker inspect -f "{{.State.Running}}" $Container 2>$null
if ($LASTEXITCODE -ne 0 -or $running -ne "true") { Fail "Container '$Container' is not running. Start the app with start_app.ps1 first." }

Step "Rows that will be exported"
$countSql = ($tables | ForEach-Object { "SELECT '$_' AS table_name, count(*) AS rows FROM $_" }) -join " UNION ALL "
docker exec $Container psql -U $DbUser -d $Database -c "$countSql;"
if ($LASTEXITCODE -ne 0) { Fail "Could not read the tables. Has the API started at least once (it creates them)?" }

Step "Exporting to $Out"
$tArgs = @(); foreach ($t in $tables) { $tArgs += @("-t", $t) }
# Dump inside the container, then copy out: PowerShell's '>' would corrupt a binary file.
docker exec $Container pg_dump -U $DbUser -d $Database --data-only --format=custom --file=/tmp/finsight_demo.dump @tArgs
if ($LASTEXITCODE -ne 0) { Fail "pg_dump failed." }
docker cp "${Container}:/tmp/finsight_demo.dump" $Out
if ($LASTEXITCODE -ne 0) { Fail "Could not copy the dump out of the container." }
docker exec $Container rm -f /tmp/finsight_demo.dump | Out-Null
$size = [math]::Round((Get-Item $Out).Length / 1KB, 1)
Write-Host "Saved $Out ($size KB)" -ForegroundColor Green

if (-not $Upload) {
    Write-Host "`nNext: upload it and import on the server, e.g."
    Write-Host "  scp -i `"$KeyFile`" $Out ${User}@<server-ip>:$RemoteDir/"
    Write-Host "  ssh -i `"$KeyFile`" ${User}@<server-ip> `"cd $RemoteDir && bash deploy/import_demo_data.sh $Out`""
    Write-Host "or re-run this script with -Upload -Server <server-ip>."
    exit 0
}

if (-not $Server) { Fail "-Upload needs -Server <ip or hostname>." }
if (-not (Test-Path $KeyFile)) { Fail "Key file not found: $KeyFile" }

Step "Uploading to $Server"
scp -i "$KeyFile" $Out "${User}@${Server}:$RemoteDir/"
if ($LASTEXITCODE -ne 0) { Fail "scp failed. Check the IP, key file, and that port 22 is open to your current IP in the security group." }

Step "Importing on the server (it backs up its current data first)"
ssh -i "$KeyFile" "${User}@${Server}" "cd $RemoteDir && git pull --ff-only -q || true; bash deploy/import_demo_data.sh $Out"
if ($LASTEXITCODE -ne 0) { Fail "Import failed on the server - see the messages above. Its previous data is in $RemoteDir/backups/." }

Write-Host "`nDone. Open https://$Server.sslip.io to check." -ForegroundColor Green
