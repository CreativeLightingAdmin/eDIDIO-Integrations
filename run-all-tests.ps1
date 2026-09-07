# Run every test suite in the eDIDIO 3rd-party integrations repo and summarise.
#
#   pwsh ./run-all-tests.ps1            # run everything
#   pwsh ./run-all-tests.ps1 -Quick     # skip the slow Node-RED / dotnet builds
#
# Covers: Python (pytest), Node (node --test / npm test), C (gcc), Tcl (tclsh),
# C# (dotnet test), and the shared edidio_control_py library.

param([switch]$Quick)

$ErrorActionPreference = "Continue"
$root = $PSScriptRoot
$results = @()

function Record($name, $ok, $detail) {
    $script:results += [pscustomobject]@{ Suite = $name; Pass = $ok; Detail = $detail }
    $tag = if ($ok) { "PASS" } else { "FAIL" }
    Write-Host ("[{0}] {1} {2}" -f $tag, $name, $detail)
}

# --- Python (pytest) suites: any folder with a tests/ dir ---
$pyRoots = @(
    "Ambient Data", "CS2 GSI", "Dota 2 GSI", "GTA5", "GenAI Moods", "HomeKit Bridge",
    "KNX Gateway", "Kerbal Space Program", "MCP Server", "MIDI Bridge", "MQTT Bridge",
    "Modbus TCPRTUGateway", "OSC Bridge", "Spektra AI", "Extron Driver",
    "SmartThings Edge", "Savant Driver"
)
foreach ($r in $pyRoots) {
    $p = Join-Path $root $r
    if ((Test-Path (Join-Path $p "tests")) -or (Test-Path (Join-Path $p "test"))) {
        Push-Location $p
        $out = & py -3 -m pytest -q 2>&1 | Out-String
        $ok = $LASTEXITCODE -eq 0
        Pop-Location
        $m = if ($out -match "(\d+) passed") { "$($Matches[1]) passed" } else { "see output" }
        Record "py: $r" $ok $m
    }
}

# AMX (muse + netlinx), ELAN, Maker Kit/raspberry-pi, Unity(_test dotnet), Maker arduino(C), FPGA(C), Tcl
function PyPassed($o) { if ($o -match "(\d+) passed") { "$($Matches[1]) passed" } else { "see output" } }
Push-Location (Join-Path $root "AMX Driver"); $o = & py -3 -m pytest muse netlinx -q 2>&1 | Out-String; Record "py: AMX Driver" ($LASTEXITCODE -eq 0) (PyPassed $o); Pop-Location
Push-Location (Join-Path $root "ELAN Driver"); $o = & py -3 -m pytest -q 2>&1 | Out-String; Record "py: ELAN Driver" ($LASTEXITCODE -eq 0) (PyPassed $o); Pop-Location
Push-Location (Join-Path $root "Maker Kit\raspberry-pi"); $o = & py -3 -m pytest -q 2>&1 | Out-String; Record "py: Maker Pi" ($LASTEXITCODE -eq 0) (PyPassed $o); Pop-Location

# --- edidio_control_py (sibling repo) ---
$lib = Join-Path (Split-Path $root -Parent) "edidio_control_py"
if (Test-Path (Join-Path $lib "tests")) {
    Push-Location $lib; $o = & py -3 -m pytest -q 2>&1 | Out-String
    Record "py: edidio_control_py" ($LASTEXITCODE -eq 0) (PyPassed $o); Pop-Location
}

# --- Node (node --test) suites ---
$nodeRoots = @("Companion Module", "RTI Driver", "Stream Deck Plugin", "Raycast Alfred",
               "OBS Studio", "Twitch Bot", "Telegram Bot", "Slack App", "Teams App")
foreach ($r in $nodeRoots) {
    $p = Join-Path $root $r
    if (Test-Path $p) {
        Push-Location $p
        if ((Test-Path "package.json") -and -not (Test-Path "node_modules") -and ($r -in @("OBS Studio","Twitch Bot","Telegram Bot","Slack App","Teams App","Companion Module"))) {
            & npm install --silent --no-audit --no-fund 2>&1 | Out-Null
        }
        $o = & node --test 2>&1 | Out-String
        $ok = $LASTEXITCODE -eq 0
        Pop-Location
        $m = if ($o -match "pass (\d+)") { "$($Matches[1]) pass" } else { "see output" }
        Record "node: $r" $ok $m
    }
}

# --- Node-RED (mocha) ---
if (-not $Quick) {
    Push-Location (Join-Path $root "Note-RED Package")
    if (-not (Test-Path "node_modules")) { & npm install --silent --no-audit --no-fund 2>&1 | Out-Null }
    $o = & npm test 2>&1 | Out-String
    Record "node: Note-RED" ($o -match "passing") (($o | Select-String "passing") -join ""); Pop-Location
}

# --- C encoders (gcc) ---
$gcc = "C:\msys64\ucrt64\bin\gcc.exe"
if (Test-Path $gcc) {
    Push-Location (Join-Path $root "FPGA\edidio-c\test")
    & $gcc -std=c99 -I.. test_frames.c "..\edidio_frames.c" -o _t.exe 2>&1 | Out-Null
    $o = & .\_t.exe | Out-String; Record "c: FPGA edidio-c" ($o -match "ALL PASSED") ""; Remove-Item _t.exe -ErrorAction SilentlyContinue; Pop-Location

    $gpp = "C:\msys64\ucrt64\bin\g++.exe"
    Push-Location (Join-Path $root "Maker Kit\arduino\_test")
    & $gpp -std=c++11 "-I..\EdidioLighting" test_frames.cpp "..\EdidioLighting\EdidioFrames.cpp" -o _t.exe 2>&1 | Out-Null
    if (Test-Path _t.exe) { $o = & .\_t.exe | Out-String; Record "cpp: Maker arduino" ($o -match "ALL PASSED") ""; Remove-Item _t.exe -ErrorAction SilentlyContinue } else { Record "cpp: Maker arduino" $false "compile failed" }
    Pop-Location
}

# --- Tcl encoder (tclsh) ---
$tclsh = "C:\msys64\ucrt64\bin\tclsh.exe"
if (Test-Path $tclsh) {
    Push-Location (Join-Path $root "Tcl Bridge")
    $o = & $tclsh test/test_frames.tcl | Out-String; Record "tcl: Tcl Bridge" ($o -match "ALL PASSED") ""; Pop-Location
}

# --- C# encoder (dotnet) ---
if (-not $Quick -and (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Push-Location (Join-Path $root "Unity Package\_test")
    $o = & dotnet test 2>&1 | Out-String; Record "csharp: Unity" ($o -match "Passed!") (($o | Select-String "Passed:") -join ""); Pop-Location
}

# --- summary ---
Write-Host "`n================= SUMMARY ================="
$fail = @($results | Where-Object { -not $_.Pass }).Count
$total = @($results).Count
$results | Format-Table Suite, Pass, Detail -AutoSize
Write-Host ("{0} suites, {1} failed" -f $total, $fail)
if ($fail -gt 0) { exit 1 } else { exit 0 }
