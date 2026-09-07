// Pure-C++ eDIDIO protocol frame encoder for Arduino / ESP32 / ESP8266.
//
// Zero dependencies, no STL, no dynamic allocation — builds into a caller-owned
// uint8_t buffer and returns the length. Produces byte-identical output to the
// reference implementation (edidio_control_py) and every other eDIDIO encoder,
// validated by a host g++ test against the same reference frames.
//
// Wire format: 0xCD + 2-byte big-endian length + a serialized EdidioMessage.
//
// Usage:
//   uint8_t buf[64];
//   size_t n = edidio::daliArcLevel(buf, sizeof(buf), messageId, edidio::lineMask(1), 5, 254);
//   client.write(buf, n);   // send over your TCP client (Ethernet/WiFi)

#ifndef EDIDIO_FRAMES_H
#define EDIDIO_FRAMES_H

#include <stddef.h>
#include <stdint.h>

namespace edidio {

// Custom DALI command enums
enum {
  DALI_ARC_LEVEL = 0,
  DALI_GROUP_ARC_LEVEL = 2,
  DALI_BROADCAST_SCENE = 3,
  DALI_SCENE_ON_GROUP = 4
};

// DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
// broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
// sent to the target address.
enum {
  DALI_GROUP_ADDRESS_BASE = 64,
  DALI_BROADCAST_ADDRESS = 80,
  DALI_GO_TO_SCENE_BASE = 0x10
};

// Standard DALI commands (subset)
enum {
  DALI_OFF = 0,
  DALI_FADE_UP = 1,
  DALI_FADE_DOWN = 2,
  DALI_STEP_UP = 3,
  DALI_STEP_DOWN = 4,
  DALI_MAX_LEVEL = 5,
  DALI_MIN_LEVEL = 6
};

// Spektra enums
enum {
  SPEKTRA_SEQUENCE = 1,
  SPEKTRA_THEME = 2,
  SPEKTRA_STATIC = 3,
  SPEKTRA_START = 0,
  SPEKTRA_STOP = 1,
  SPEKTRA_PAUSE = 2,
  TRIGGER_SPEKTRA_STOP_SEQ = 13
};

static const int DALI_ARC_LEVEL_MAX = 254;

// Keep-alive / "Are You There" heartbeat frame (2 bytes: 0xFF 0xF6).
extern const uint8_t KEEP_ALIVE[2];

// 1-based physical line (1-4) -> single-bit line mask.
inline int lineMask(int line) { return 1 << (line - 1); }

// Each builder writes a framed message into `out` (capacity `cap`) and returns
// the number of bytes written, or 0 if the buffer is too small. 64 bytes is
// ample for all of these.

size_t daliArcLevel(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int address, int level);
size_t daliGroupArcLevel(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int group, int level);
size_t daliCommand(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int address, int command, int arg = 0);
size_t daliBroadcastScene(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int scene);
size_t daliSceneOnGroup(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int group, int scene);
size_t dmxLevel(uint8_t* out, size_t cap, int32_t messageId, int zone, int universeMask,
                int channel, int repeat, const uint8_t* levels, size_t levelCount, int fadeBy10ms = 0);
size_t spektraControl(uint8_t* out, size_t cap, int32_t messageId, int spektraType, int zone, int index, int action);
size_t spektraStop(uint8_t* out, size_t cap, int32_t messageId, int zone, int lineMask = 0xFF);

}  // namespace edidio

#endif  // EDIDIO_FRAMES_H
