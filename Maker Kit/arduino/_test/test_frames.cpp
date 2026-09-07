// Host byte-equality test for the Arduino C++ encoder.
//   g++ -std=c++11 -I../EdidioLighting test_frames.cpp ../EdidioLighting/EdidioFrames.cpp -o test && ./test
//
// Reference hexes captured from edidio_control_py 0.3.0 (message_id=7), the same
// oracle used by every eDIDIO encoder.

#include <cstdio>
#include <cstring>
#include <string>
#include "EdidioFrames.h"

static std::string hex(const uint8_t* b, size_t n) {
  static const char* d = "0123456789abcdef";
  std::string s;
  for (size_t i = 0; i < n; i++) {
    s += d[(b[i] >> 4) & 0xF];
    s += d[b[i] & 0xF];
  }
  return s;
}

static int failures = 0;
static void check(const char* name, const std::string& got, const std::string& want) {
  if (got == want) {
    printf("[ok]   %s\n", name);
  } else {
    printf("[FAIL] %s\n  got:  %s\n  want: %s\n", name, got.c_str(), want.c_str());
    failures++;
  }
}

int main() {
  const int MID = 7;
  uint8_t buf[128];
  size_t n;

  n = edidio::daliArcLevel(buf, sizeof(buf), MID, edidio::lineMask(1), 5, 200);
  check("arc", hex(buf, n), "cd000e080792010908011005300048c801");

  n = edidio::daliGroupArcLevel(buf, sizeof(buf), MID, edidio::lineMask(1), 3, 128);
  check("group", hex(buf, n), "cd000e0807920109080110433000488001");

  n = edidio::daliCommand(buf, sizeof(buf), MID, edidio::lineMask(2), 10, edidio::DALI_MAX_LEVEL);
  check("cmd", hex(buf, n), "cd000d08079201080802100a28054800");

  n = edidio::daliCommand(buf, sizeof(buf), MID, edidio::lineMask(1), 0, edidio::DALI_OFF);
  check("cmd_off", hex(buf, n), "cd000b0807920106080128004800");

  n = edidio::daliBroadcastScene(buf, sizeof(buf), MID, edidio::lineMask(1), 3);
  check("bscene", hex(buf, n), "cd000b0807920106080110502813");

  n = edidio::daliSceneOnGroup(buf, sizeof(buf), MID, edidio::lineMask(1), 4, 3);
  check("gscene", hex(buf, n), "cd000b0807920106080110442813");

  uint8_t rgb[3] = {255, 0, 0};
  n = edidio::dmxLevel(buf, sizeof(buf), MID, 255, 2, 1, 10, rgb, 3);
  check("dmx", hex(buf, n), "cd00140807a2010f08ff0110021801200a2a04ff010000");

  uint8_t lv[3] = {10, 20, 30};
  n = edidio::dmxLevel(buf, sizeof(buf), MID, 0, 1, 1, 1, lv, 3, 50);
  check("dmx_fade", hex(buf, n), "cd00120807a2010d1001180120012a030a141e3032");

  n = edidio::spektraControl(buf, sizeof(buf), MID, edidio::SPEKTRA_SEQUENCE, 1, 2, edidio::SPEKTRA_START);
  check("spektra", hex(buf, n), "cd000b0807da0106080110011802");

  n = edidio::spektraStop(buf, sizeof(buf), MID, 1, 0xFF);
  check("spektra_stop", hex(buf, n), "cd000e0807aa01090a07080d100118ff01");

  // clamp
  size_t a = edidio::daliArcLevel(buf, sizeof(buf), MID, edidio::lineMask(1), 5, 999);
  std::string clamped = hex(buf, a);
  size_t b = edidio::daliArcLevel(buf, sizeof(buf), MID, edidio::lineMask(1), 5, 254);
  check("arc_clamps", clamped, hex(buf, b));

  printf("\n%s\n", failures == 0 ? "ALL PASSED" : "FAILURES PRESENT");
  return failures == 0 ? 0 : 1;
}
