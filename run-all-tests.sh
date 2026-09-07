#!/usr/bin/env bash
# Run every test suite in the eDIDIO 3rd-party integrations repo (macOS/Linux).
# On Windows, use run-all-tests.ps1 (handles the py -3 launcher + msys2 toolchain).
#
#   ./run-all-tests.sh
#
# Requires: python3, node, gcc/g++, tclsh (optional: dotnet for the C# encoder).

set -u
root="$(cd "$(dirname "$0")" && pwd)"
pass=0; fail=0
declare -a failed

record() { # name ok detail
  if [ "$2" = "1" ]; then echo "[PASS] $1  $3"; pass=$((pass+1));
  else echo "[FAIL] $1  $3"; fail=$((fail+1)); failed+=("$1"); fi
}

py_suite() { # dir [pytest-args...]
  local dir="$1"; shift
  if [ -d "$root/$dir/tests" ] || [ -d "$root/$dir/test" ]; then
    ( cd "$root/$dir" && python3 -m pytest -q "$@" >/tmp/ed_out 2>&1 )
    local ok=$([ $? -eq 0 ] && echo 1 || echo 0)
    record "py: $dir" "$ok" "$(grep -oE '[0-9]+ passed' /tmp/ed_out | tail -1)"
  fi
}

for d in "Ambient Data" "CS2 GSI" "Dota 2 GSI" "GTA5" "GenAI Moods" "HomeKit Bridge" \
         "KNX Gateway" "Kerbal Space Program" "MCP Server" "MIDI Bridge" "MQTT Bridge" \
         "Modbus TCPRTUGateway" "OSC Bridge" "Spektra AI" "Extron Driver" \
         "SmartThings Edge" "Savant Driver" "ELAN Driver"; do
  py_suite "$d"
done
py_suite "AMX Driver" muse netlinx
py_suite "Maker Kit/raspberry-pi"
[ -d "$root/../edidio_control_py/tests" ] && ( cd "$root/../edidio_control_py" && python3 -m pytest -q >/tmp/ed_out 2>&1 ) && record "py: edidio_control_py" 1 "$(grep -oE '[0-9]+ passed' /tmp/ed_out | tail -1)"

for d in "Companion Module" "RTI Driver" "Stream Deck Plugin" "Raycast Alfred" \
         "OBS Studio" "Twitch Bot" "Telegram Bot" "Slack App" "Teams App"; do
  if [ -d "$root/$d" ]; then
    ( cd "$root/$d"; [ -f package.json ] && [ ! -d node_modules ] && npm install --silent >/dev/null 2>&1; node --test >/tmp/ed_out 2>&1 )
    ok=$([ $? -eq 0 ] && echo 1 || echo 0)
    record "node: $d" "$ok" "$(grep -oE 'pass [0-9]+' /tmp/ed_out | tail -1)"
  fi
done

# C / C++ / Tcl encoders
if command -v gcc >/dev/null; then
  ( cd "$root/FPGA/edidio-c/test" && gcc -std=c99 -I.. test_frames.c ../edidio_frames.c -o _t && ./_t >/tmp/ed_out 2>&1; rm -f _t )
  record "c: FPGA edidio-c" "$([ $? -eq 0 ] && echo 1 || echo 0)" ""
fi
if command -v g++ >/dev/null; then
  ( cd "$root/Maker Kit/arduino/_test" && g++ -std=c++11 -I../EdidioLighting test_frames.cpp ../EdidioLighting/EdidioFrames.cpp -o _t && ./_t >/tmp/ed_out 2>&1; rm -f _t )
  record "cpp: Maker arduino" "$([ $? -eq 0 ] && echo 1 || echo 0)" ""
fi
if command -v tclsh >/dev/null; then
  ( cd "$root/Tcl Bridge" && tclsh test/test_frames.tcl >/tmp/ed_out 2>&1 )
  record "tcl: Tcl Bridge" "$([ $? -eq 0 ] && echo 1 || echo 0)" ""
fi
if command -v dotnet >/dev/null; then
  ( cd "$root/Unity Package/_test" && dotnet test >/tmp/ed_out 2>&1 )
  record "csharp: Unity" "$([ $? -eq 0 ] && echo 1 || echo 0)" ""
fi

echo ""
echo "================= SUMMARY ================="
echo "$((pass+fail)) suites, $fail failed"
[ "$fail" -gt 0 ] && { printf 'failed: %s\n' "${failed[@]}"; exit 1; }
exit 0
