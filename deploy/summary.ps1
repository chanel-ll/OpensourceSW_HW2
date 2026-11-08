# Builds the deployment report (Korean) from the monitor log, deploy timeline and eval/results.json.
# Writes <OutDir>\summary.md and, inside GitHub Actions, the job Summary.
param(
    [Parameter(Mandatory)][string]$OutDir,
    [string]$Url = "http://127.0.0.1:8090",
    [string]$Results = "eval/results.json",
    [string]$Image = ""
)
$ErrorActionPreference = 'Continue'
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Lines($f) { if (Test-Path $f) { [IO.File]::ReadAllLines($f, $utf8) | Where-Object { $_.Trim() } | ForEach-Object { $_ | ConvertFrom-Json } } else { @() } }
function Kst($iso) { if (-not $iso) { return "-" }; ([DateTimeOffset]::Parse($iso)).ToOffset([TimeSpan]::FromHours(9)).ToString("HH:mm:ss.fff") }
function Dt($iso) { [DateTimeOffset]::Parse($iso) }
function Cell($s) { "$s" -replace '\|', '\|' }   # a raw | inside a cell would split the Markdown table

$recs = @(Lines "$OutDir\monitor.jsonl")
$events = @(Lines "$OutDir\events.jsonl")
$md = New-Object System.Collections.Generic.List[string]
$md.Add("## 🚀 배포 모니터링 결과 — Research Tracker")
if (-not $recs.Count) { $md.Add("> ⚠️ 모니터링 기록이 없습니다 (모니터 프로세스가 시작되지 않았거나 즉시 종료됨).") }
else {
    $ok = @($recs | Where-Object { $_.status -eq 200 -and $_.valid })
    $fail = @($recs | Where-Object { -not ($_.status -eq 200 -and $_.valid) })
    $starts = $recs | ForEach-Object { Dt $_.start }
    $gaps = @(); for ($i = 1; $i -lt $starts.Count; $i++) { $gaps += [Math]::Round(($starts[$i] - $starts[$i - 1]).TotalSeconds, 2) }
    $maxGap = if ($gaps.Count) { ($gaps | Measure-Object -Maximum).Maximum } else { 0 }
    $avgGap = if ($gaps.Count) { [Math]::Round(($gaps | Measure-Object -Average).Average, 2) } else { 0 }
    $ms = $recs | ForEach-Object { $_.ms }
    $ev = @{}; foreach ($e in $events) { if (-not $ev.ContainsKey($e.event)) { $ev[$e.event] = $e } }
    $versions = @(); $prev = $null
    foreach ($r in $ok) { if ($r.version -ne $prev) { $versions += $r; $prev = $r.version } }
    $unverified = @(); for ($i = 1; $i -lt $starts.Count; $i++) { if ($gaps[$i - 1] -gt 2) { $unverified += "$(Kst $recs[$i-1].start) ~ $(Kst $recs[$i].start) ($($gaps[$i-1])s)" } }
    $verdict = if (-not $fail.Count -and $maxGap -le 2) { "✅ **무중단 확인** — 관측한 $($recs.Count)회 요청이 모두 정상 응답했고, 요청 간 최대 공백은 $($maxGap)초입니다." }
               elseif (-not $fail.Count) { "⚠️ 실패 응답은 없지만 기록 공백($($maxGap)초)이 있어 그 구간은 검증되지 않았습니다." }
               else { "❌ 실패 응답 $($fail.Count)건 — 아래 표의 시각에 서비스가 중단되었거나 비정상 응답했습니다." }

    $md.Add("")
    $md.Add($verdict)
    $md.Add("")
    $md.Add("| 항목 | 값 |")
    $md.Add("|---|---|")
    $md.Add("| 검증 주소 | ``$Url/api/model/analyze`` (고정 논문, 1초 간격) |")
    $md.Add("| 모니터링 시간 (KST) | $(Kst $recs[0].start) ~ $(Kst $recs[-1].end) |")
    if ($Image) { $md.Add("| 배포 이미지 | ``$Image`` |") }
    $md.Add("| 전체 요청 | **$($recs.Count)회** — 성공 **$($ok.Count)** / 실패 **$($fail.Count)** |")
    $md.Add("| 응답 시간 | 평균 $([Math]::Round(($ms | Measure-Object -Average).Average,1))ms · 최대 $([Math]::Round(($ms | Measure-Object -Maximum).Maximum,1))ms |")
    $md.Add("| 실제 요청 간격 | 평균 $($avgGap)초 · **최대 기록 공백 $($maxGap)초** |")
    $md.Add("| 검증되지 않은 구간 (공백 > 2초) | $(if ($unverified.Count) { $unverified -join '<br>' } else { '없음' }) |")

    $md.Add("")
    $md.Add("### 🔁 모델·버전 전환")
    $md.Add("| 시각 (KST) | 내용 |")
    $md.Add("|---|---|")
    $rows = @()   # deploy events and observed version changes on one time-ordered timeline
    foreach ($e in $events) { if ($e.event -in "deploy-start", "new-ready", "legacy-stop", "switched", "verified", "rollback", "old-stopped", "deploy-done") { $rows += [pscustomobject]@{ t = (Dt $e.t); text = "**$($e.event)** $(Cell $e.detail)" } } }
    foreach ($v in $versions) { $rows += [pscustomobject]@{ t = (Dt $v.start); text = "📡 응답 버전 → ``$($v.version)`` · ``$(Cell $v.model)``" } }
    foreach ($r in $rows | Sort-Object t) { $md.Add("| $($r.t.ToOffset([TimeSpan]::FromHours(9)).ToString('HH:mm:ss.fff')) | $($r.text) |") }

    $md.Add("")
    $md.Add("### 📨 대표 응답 (배포 전·중·후)")
    $md.Add("| 구간 | 시각 (KST) | 상태 | 응답 시간 | 버전 | 키워드 |")
    $md.Add("|---|---|---|---|---|---|")
    $dStart = if ($ev["deploy-start"]) { Dt $ev["deploy-start"].t } else { $null }
    $dSwitch = if ($ev["switched"]) { Dt $ev["switched"].t } else { $null }
    $dDone = if ($ev["deploy-done"]) { Dt $ev["deploy-done"].t } else { $null }
    $pick = @(
        @("배포 전", ($recs | Where-Object { $dStart -and (Dt $_.start) -lt $dStart } | Select-Object -Last 1)),
        @("배포 중 (전환 직후)", ($recs | Where-Object { $dSwitch -and (Dt $_.start) -ge $dSwitch } | Select-Object -First 1)),
        @("배포 후", ($recs | Select-Object -Last 1)))
    foreach ($p in $pick) { $r = $p[1]; if ($r) { $md.Add("| $($p[0]) | $(Kst $r.start) | $($r.status) | $($r.ms)ms | ``$($r.version)`` | $(Cell (@($r.keywords) -join ', ')) |") } }
    if ($fail.Count) {
        $md.Add("")
        $md.Add("<details><summary>실패 응답 $($fail.Count)건</summary>")
        $md.Add("")
        foreach ($f in $fail | Select-Object -First 20) { $md.Add("- $(Kst $f.start) status=$($f.status) $(Cell $f.error)") }
        $md.Add("</details>")
    }
}

if (Test-Path $Results) {
    $res = [IO.File]::ReadAllText((Resolve-Path $Results), $utf8) | ConvertFrom-Json
    $md.Add("")
    $md.Add("### 📊 모델 변경 전후 성능 (최종 평가 70+70, 튜닝 데이터로만 선택)")
    $md.Add("| 버전 | 설정 | 키워드 F1@5 | 분야 분류 정확도 | CPU/논문 | 모델 크기 |")
    $md.Add("|---|---|---|---|---|---|")
    $sel = $res.selected
    foreach ($n in "baseline", "attempt1_preprocess", "attempt2_model") {
        $f = $res.final.$n; $c = $f.cfg
        $mark = if ($c.model -eq $sel.model -and $c.preprocess -eq $sel.preprocess -and $c.diversity -eq $sel.diversity) { " ✅ 배포" } else { "" }
        $label = @{ baseline = "변경 전"; attempt1_preprocess = "시도 1 (전처리)"; attempt2_model = "시도 2 (모델 교체)" }[$n]
        $md.Add("| $label$mark | $(($c.model -split '/')[-1]) · $($c.preprocess) · div $($c.diversity) | $($f.'keyword_f1@5_present'.f1) | $($f.knn_field_accuracy) | $($f.cpu_ms_per_paper)ms | $($f.model_mb)MB |")
    }
}

$text = ($md -join "`n") + "`n"
[IO.File]::WriteAllText("$OutDir\summary.md", $text, $utf8)
if ($env:GITHUB_STEP_SUMMARY) { [IO.File]::AppendAllText($env:GITHUB_STEP_SUMMARY, $text, $utf8) }
Write-Host $text
