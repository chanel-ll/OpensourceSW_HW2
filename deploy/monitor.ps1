# Independent deployment monitor: one fixed analysis request per second, every result as a JSONL line.
# Runs as its own process; keeps going until <StopFile> exists, then <AfterSeconds> more, then exits.
param(
    [string]$Url = "http://127.0.0.1:8090",
    [Parameter(Mandatory)][string]$OutFile,
    [Parameter(Mandatory)][string]$StopFile,
    [int]$AfterSeconds = 30,
    [int]$MaxMinutes = 30
)
$ErrorActionPreference = 'Continue'
Add-Type -AssemblyName System.Net.Http
$http = New-Object System.Net.Http.HttpClient
$http.Timeout = [TimeSpan]::FromSeconds(5)
$body = '{"title":"Dense Metric Depth Completion from Sparse Direct Time-of-Flight Sensors","abstract":"Consumer-grade direct time-of-flight (dToF) sensors provide sparse but accurate depth. We propose a transformer encoder that completes dense metric depth maps from sparse dToF points and an RGB image."}'
$utf8 = New-Object System.Text.UTF8Encoding($false)
$t0 = Get-Date; $seq = 0; $stopAt = $null

while ($true) {
    $tick = $t0.AddSeconds($seq)                    # fixed 1 s schedule (no drift)
    $wait = ($tick - (Get-Date)).TotalMilliseconds
    if ($wait -gt 0) { Start-Sleep -Milliseconds ([int]$wait) }
    $seq++
    $start = Get-Date
    $rec = [ordered]@{ seq = $seq; start = $start.ToUniversalTime().ToString("o") }
    try {
        $content = New-Object System.Net.Http.StringContent($body, [Text.Encoding]::UTF8, "application/json")
        $resp = $http.PostAsync("$Url/api/model/analyze", $content).GetAwaiter().GetResult()
        $text = $resp.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $rec.status = [int]$resp.StatusCode
        if ($resp.IsSuccessStatusCode) {
            $j = $text | ConvertFrom-Json
            $rec.version = $j.model.app_version
            $rec.model = $j.model.model_id
            $rec.keywords = @($j.keywords)
            $rec.valid = ($j.keywords.Count -gt 0) -and ($j.embedding_dim -gt 0)
        } else { $rec.valid = $false; $rec.error = $text.Substring(0, [Math]::Min(120, $text.Length)) }
    } catch {
        $rec.status = 0; $rec.valid = $false
        $msg = $_.Exception.InnerException; if (-not $msg) { $msg = $_.Exception }
        $rec.error = "$($msg.Message)".Substring(0, [Math]::Min(120, "$($msg.Message)".Length))
    }
    $end = Get-Date
    $rec.end = $end.ToUniversalTime().ToString("o")
    $rec.ms = [Math]::Round(($end - $start).TotalMilliseconds, 1)
    [IO.File]::AppendAllText($OutFile, (($rec | ConvertTo-Json -Compress) + "`n"), $utf8)

    if (-not $stopAt -and (Test-Path $StopFile)) { $stopAt = (Get-Date).AddSeconds($AfterSeconds) }
    if ($stopAt -and (Get-Date) -ge $stopAt) { break }
    if (((Get-Date) - $t0).TotalMinutes -ge $MaxMinutes) { break }
    # if a request ran long, catch up the schedule instead of bursting
    if (((Get-Date) - $t0).TotalSeconds -gt $seq + 1) { $seq = [int][Math]::Floor(((Get-Date) - $t0).TotalSeconds) }
}
