# Zero-downtime blue-green deploy on one Windows PC (Docker Desktop).
#   nginx proxy "pu-proxy" owns http://127.0.0.1:<Port>; app containers "paper-universe-blue|green" have no host port.
#   1) start the new color next to the running one  2) check it from inside Docker (status + analyze API)
#   3) graceful nginx reload to the new color        4) confirm /health version via the public URL  5) stop the old color
# Anything failing before step 3 never touches the running service; failing after it switches back.
param(
    [Parameter(Mandatory)][string]$Ref,     # image to deploy, e.g. chaniii1/paper-universe:sha-1234567
    [int]$Port = 8090,
    [string]$Events = "",                   # JSONL timeline for the monitoring summary
    [string]$Want = ""                      # version the new container must report (sha-<commit>); checked before switching
)
$ErrorActionPreference = 'Stop'
$Net = "pu-net"; $Proxy = "pu-proxy"; $ProxyImage = "nginx:1.28-alpine"; $Legacy = "paper-universe"
$CfgDir = Join-Path $env:USERPROFILE ".paper-universe"

function Event($name, $detail = "") {
    $line = @{ t = (Get-Date).ToUniversalTime().ToString("o"); event = $name; detail = $detail } | ConvertTo-Json -Compress
    Write-Host "[deploy] $name $detail"
    if ($Events) { Add-Content -Path $Events -Value $line -Encoding UTF8 }
}
function Exists($name) { [bool](docker ps -aq -f "name=^$name$") }
function Running($name) { [bool](docker ps -q -f "name=^$name$" -f "status=running") }
function Quiet($cmd) { cmd /c "$cmd >nul 2>&1"; $global:LASTEXITCODE = 0 }

function ProxyConf($upstream) {
    # lazy DNS (resolver + variable): nginx starts/reloads even if a color is briefly absent
    @"
server {
    listen 80;
    client_max_body_size 20m;
    resolver 127.0.0.11 valid=5s ipv6=off;
    set `$app http://${upstream}:8000;
    location / {
        proxy_pass `$app;
        proxy_http_version 1.1;
        proxy_set_header Host `$host;
        proxy_set_header Connection "";
        proxy_read_timeout 300s;
        proxy_next_upstream error timeout;
    }
}
"@ -replace "`r", ""
}
function WriteConf($color) {
    # file without BOM + LF (piping into docker exec from PowerShell 5.1 prepends a BOM nginx rejects)
    $f = Join-Path $env:TEMP "pu-proxy-$color.conf"
    [IO.File]::WriteAllText($f, (ProxyConf "paper-universe-$color"), (New-Object System.Text.UTF8Encoding($false)))
    docker cp $f "${Proxy}:/etc/nginx/conf.d/default.conf"
    if ($LASTEXITCODE -ne 0) { throw "docker cp proxy config failed" }
}
function SetUpstream($color) {
    WriteConf $color
    docker exec $Proxy sh -c "nginx -t -q && nginx -s reload"   # graceful: in-flight requests finish on old workers
    if ($LASTEXITCODE -ne 0) { throw "nginx reload to $color failed" }
}
function ActiveColor {
    $ErrorActionPreference = 'Continue'   # native stderr must not abort (PowerShell 5.1)
    if (-not (Exists $Proxy)) { return "" }
    $c = docker exec $Proxy cat /etc/nginx/conf.d/default.conf 2>$null
    if ("$c" -match "paper-universe-(blue|green)") { return $Matches[1] } else { return "" }
}
function AppArgs($color) {
    $a = @("-d", "--name", "paper-universe-$color", "--network", $Net, "--restart", "unless-stopped",
        "-v", "paper-universe-data:/app/data", "-v", "paper-universe-notes:/app/notes", "-v", "paper-universe-logs:/app/logs")
    if (Test-Path "$CfgDir\.env") { $a += @("--env-file", "$CfgDir\.env") }
    if (Test-Path "$CfgDir\config.yaml") { $a += @("-v", "${CfgDir}\config.yaml:/app/config.yaml:ro") }
    # GitHub Secret from the deploy job; "-e NAME" copies the value from this process, never onto the command line
    if ($env:FACTCHAT_API_KEY) { $a += @("-e", "FACTCHAT_API_KEY") }
    if ($env:LLM_BASE_URL) { $a += @("-e", "LLM_BASE_URL") }
    return $a
}
function InsideCheck($color) {
    # status + real analysis request from inside the new container (no host port needed)
    $ErrorActionPreference = 'Continue'   # failures are expected while it starts
    $py = "import json,urllib.request as u; h=json.load(u.urlopen('http://127.0.0.1:8000/health',timeout=5)); assert h['status']=='ok', h; " +
          "r=u.Request('http://127.0.0.1:8000/api/model/analyze',data=json.dumps({'title':'Depth completion from sparse time-of-flight sensors','abstract':'We densify sparse depth.'}).encode(),headers={'Content-Type':'application/json'}); " +
          "a=json.load(u.urlopen(r,timeout=30)); assert a['keywords'] and a['embedding_dim']>0; print(h['version'], a['model']['model_id'], 'llm=' + str(h['llm']['enabled']), 'papers=' + str(h.get('papers')))"
    $out = docker exec "paper-universe-$color" python -c $py 2>$null
    if ($LASTEXITCODE -eq 0) { return "$out" } else { return $null }
}
function PublicVersion {
    try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 5 "http://127.0.0.1:$Port/health").Content | ConvertFrom-Json }
    catch { $null }
}

# ---------- 0) one-time infrastructure ----------
if (-not (docker network ls -q -f "name=^$Net$")) { docker network create $Net | Out-Null; Event "network-created" $Net }
# a proxy left stopped (e.g. Docker Desktop was closed) would hide the active color and refuse "nginx -s reload"
if ((Exists $Proxy) -and -not (Running $Proxy)) {
    docker start $Proxy | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "stopped proxy $Proxy could not be started" }
    Start-Sleep -Seconds 2; Event "proxy-restarted" "$Proxy was stopped"
}
$active = ActiveColor
if ((Exists $Proxy) -and -not $active) {
    # never guess: "blue" could be the live color and would be deleted below
    Event "rollback" "proxy exists but its active color is unreadable (service untouched)"
    throw "cannot read the active color from $Proxy; fix the proxy config before deploying"
}
$new = if ($active -eq "blue") { "green" } else { "blue" }
Event "deploy-start" "image=$Ref active=$(if ($active) { $active } else { 'none' }) new=$new"

# ---------- 1) start the new color beside the old one ----------
Quiet "docker rm -f paper-universe-$new"
$args1 = (AppArgs $new) + @($Ref)
docker run @args1 | Out-Null
if ($LASTEXITCODE -ne 0) { Event "rollback" "docker run failed (service untouched)"; throw "docker run failed" }

# ---------- 2) health + analysis check from inside ----------
$ok = $null; $deadline = (Get-Date).AddMinutes(4)   # first start may recompute embeddings (model migration)
while (-not $ok -and (Get-Date) -lt $deadline) { $ok = InsideCheck $new; if (-not $ok) { Start-Sleep -Seconds 2 } }
if (-not $ok) {
    # app logs can contain lab URLs and gateway errors: keep them in the uploaded artifact, not the public job log
    $logFile = if ($Events) { Join-Path (Split-Path $Events) "new-container.log" } else { Join-Path $env:TEMP "pu-new-container.log" }
    cmd /c "docker logs --tail 200 paper-universe-$new > `"$logFile`" 2>&1"
    Write-Host "container logs saved to $logFile"
    Quiet "docker rm -f paper-universe-$new"
    Event "rollback" "new container never became healthy (service untouched)"
    throw "new container failed health/analyze check"
}
Event "new-ready" "$new $ok"
$newVersion = ($ok -split " ")[0]
if ($Want -and $newVersion -ne $Want) {
    Quiet "docker rm -f paper-universe-$new"
    Event "rollback" "new container reports $newVersion, expected $Want (service untouched)"
    throw "pulled image is $newVersion, not $Want"
}
$live = PublicVersion   # what users see now
$newPapers = if ("$ok" -match "papers=(\d+)") { [int]$Matches[1] } else { -1 }
if ($live -and $live.papers -gt 0 -and $newPapers -eq 0) {
    Quiet "docker rm -f paper-universe-$new"
    Event "rollback" "new container sees 0 papers, live service has $($live.papers): data volume missing? (service untouched)"
    throw "new container sees an empty database"
}

# ---------- 3) switch traffic ----------
if (Exists $Proxy) {
    SetUpstream $new
} else {
    # first blue-green run: hand port $Port over from the old single container (one short gap, logged).
    # The proxy is created and configured first, so only "stop old -> start proxy" happens in the gap.
    docker pull $ProxyImage | Out-Null
    docker create --name $Proxy --network $Net --restart unless-stopped -p "127.0.0.1:${Port}:80" $ProxyImage | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "proxy create failed" }
    WriteConf $new
    $legacyImage = if (Exists $Legacy) { docker inspect -f "{{.Config.Image}}" $Legacy } else { "" }
    if ($legacyImage) { Event "legacy-stop" "$Legacy ($legacyImage) releases port $Port"; Quiet "docker rm -f $Legacy" }
    docker start $Proxy | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Quiet "docker rm -f $Proxy"
        if ($legacyImage) {   # put the old single container back exactly as the previous workflow ran it
            $back = @("-d", "--name", $Legacy, "--restart", "unless-stopped", "-p", "127.0.0.1:${Port}:8000",
                "-v", "paper-universe-data:/app/data", "-v", "paper-universe-notes:/app/notes", "-v", "paper-universe-logs:/app/logs")
            if (Test-Path "$CfgDir\.env") { $back += @("--env-file", "$CfgDir\.env") }
            if (Test-Path "$CfgDir\config.yaml") { $back += @("-v", "${CfgDir}\config.yaml:/app/config.yaml:ro") }
            docker run @back $legacyImage | Out-Null
            Event "rollback" "proxy did not start; $Legacy restored"
        }
        throw "proxy start failed"
    }
}
Event "switched" "traffic -> $new"

# ---------- 4) confirm through the public URL ----------
$want = $newVersion
$seen = $null; $deadline = (Get-Date).AddSeconds(30)
while ((Get-Date) -lt $deadline) { $seen = PublicVersion; if ($seen -and $seen.version -eq $want) { break }; Start-Sleep -Milliseconds 500 }
if (-not $seen -or $seen.version -ne $want) {
    if ($active) { SetUpstream $active; Event "rollback" "public URL did not serve $want; traffic back to $active" }
    Quiet "docker rm -f paper-universe-$new"
    throw "public URL did not switch to $want"
}
Event "verified" "http://127.0.0.1:$Port/health version=$($seen.version) db=$($seen.db) llm=$($seen.llm.enabled)"

# ---------- 5) retire the old color (after in-flight requests drain) ----------
if ($active) {   # graceful stop lets in-flight requests and DB writes finish before removal
    Start-Sleep -Seconds 3; Quiet "docker stop -t 20 paper-universe-$active"; Quiet "docker rm -f paper-universe-$active"; Event "old-stopped" $active
}
Event "deploy-done" "active=$new"
