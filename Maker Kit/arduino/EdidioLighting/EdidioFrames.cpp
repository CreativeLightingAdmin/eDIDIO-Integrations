// eDIDIO frame encoder implementation (Arduino / host portable).

#include "EdidioFrames.h"

namespace edidio {

const uint8_t KEEP_ALIVE[2] = {0xFF, 0xF6};

namespace {

// A tiny append-only byte writer over a caller buffer. `ok` goes false on
// overflow so builders can bail without writing past the end.
struct Writer {
  uint8_t* buf;
  size_t cap;
  size_t len;
  bool ok;
  Writer(uint8_t* b, size_t c) : buf(b), cap(c), len(0), ok(true) {}

  void put(uint8_t v) {
    if (len < cap) buf[len++] = v;
    else ok = false;
  }

  void varint(uint32_t v) {
    while (v >= 128) {
      put((uint8_t)((v & 0x7F) | 0x80));
      v >>= 7;
    }
    put((uint8_t)v);
  }

  void tag(int field, int wire) { varint((uint32_t)((field << 3) | wire)); }

  void uintField(int field, uint32_t value, bool always) {
    if (value == 0 && !always) return;
    tag(field, 0);
    varint(value);
  }
};

int clampInt(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }

// Compute the varint length of a value (to size embedded-message length prefixes).
size_t varintLen(uint32_t v) {
  size_t n = 1;
  while (v >= 128) { v >>= 7; n++; }
  return n;
}

// Frame a DALI message body directly into `out`. We build the inner DALIMessage
// twice conceptually: once to measure, then emit — but since sizes are tiny we
// build the inner body into a small scratch buffer and copy.
size_t frameDali(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int address,
                 int command, int customCommand, int arg) {
  // Build DALIMessage body.
  uint8_t body[32];
  Writer b(body, sizeof(body));
  b.uintField(1, (uint32_t)lineMask, false);
  b.uintField(2, (uint32_t)address, false);
  if (command >= 0) b.uintField(5, (uint32_t)command, true);
  if (customCommand >= 0) b.uintField(6, (uint32_t)customCommand, true);
  if (arg >= 0) b.uintField(9, (uint32_t)arg, true);
  if (!b.ok) return 0;

  // Build EdidioMessage: message_id (field 1) + dali_message (field 18, embedded).
  uint8_t edidio[48];
  Writer e(edidio, sizeof(edidio));
  e.uintField(1, (uint32_t)messageId, false);
  e.tag(18, 2);
  e.varint((uint32_t)b.len);
  for (size_t i = 0; i < b.len; i++) e.put(body[i]);
  if (!e.ok) return 0;

  // Frame: 0xCD + 2-byte length + edidio body.
  size_t total = e.len + 3;
  if (total > cap) return 0;
  out[0] = 0xCD;
  out[1] = (uint8_t)((e.len >> 8) & 0xFF);
  out[2] = (uint8_t)(e.len & 0xFF);
  for (size_t i = 0; i < e.len; i++) out[3 + i] = edidio[i];
  return total;
}

}  // namespace

size_t daliArcLevel(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int address, int level) {
  return frameDali(out, cap, messageId, lineMask, address, -1, DALI_ARC_LEVEL, clampInt(level, 0, DALI_ARC_LEVEL_MAX));
}

size_t daliGroupArcLevel(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int group, int level) {
  // DALI_ARC_LEVEL to the group address (64 + group).
  return frameDali(out, cap, messageId, lineMask, DALI_GROUP_ADDRESS_BASE + group, -1, DALI_ARC_LEVEL, clampInt(level, 0, DALI_ARC_LEVEL_MAX));
}

size_t daliCommand(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int address, int command, int arg) {
  return frameDali(out, cap, messageId, lineMask, address, command, -1, arg);
}

size_t daliBroadcastScene(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int scene) {
  // Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80.
  return frameDali(out, cap, messageId, lineMask, DALI_BROADCAST_ADDRESS, DALI_GO_TO_SCENE_BASE + scene, -1, -1);
}

size_t daliSceneOnGroup(uint8_t* out, size_t cap, int32_t messageId, int lineMask, int group, int scene) {
  // Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group).
  return frameDali(out, cap, messageId, lineMask, DALI_GROUP_ADDRESS_BASE + group, DALI_GO_TO_SCENE_BASE + scene, -1, -1);
}

size_t dmxLevel(uint8_t* out, size_t cap, int32_t messageId, int zone, int universeMask,
                int channel, int repeat, const uint8_t* levels, size_t levelCount, int fadeBy10ms) {
  // packed levels body.
  uint8_t packed[80];
  Writer p(packed, sizeof(packed));
  for (size_t i = 0; i < levelCount; i++) p.varint(clampInt(levels[i], 0, 255));
  if (!p.ok) return 0;

  // DMXMessage body.
  uint8_t body[128];
  Writer b(body, sizeof(body));
  b.uintField(1, (uint32_t)zone, false);
  b.uintField(2, (uint32_t)universeMask, false);
  b.uintField(3, (uint32_t)channel, false);
  b.uintField(4, (uint32_t)repeat, false);
  b.tag(5, 2);
  b.varint((uint32_t)p.len);
  for (size_t i = 0; i < p.len; i++) b.put(packed[i]);
  b.uintField(6, (uint32_t)fadeBy10ms, false);
  if (!b.ok) return 0;

  uint8_t edidio[160];
  Writer e(edidio, sizeof(edidio));
  e.uintField(1, (uint32_t)messageId, false);
  e.tag(20, 2);
  e.varint((uint32_t)b.len);
  for (size_t i = 0; i < b.len; i++) e.put(body[i]);
  if (!e.ok) return 0;

  size_t total = e.len + 3;
  if (total > cap) return 0;
  out[0] = 0xCD;
  out[1] = (uint8_t)((e.len >> 8) & 0xFF);
  out[2] = (uint8_t)(e.len & 0xFF);
  for (size_t i = 0; i < e.len; i++) out[3 + i] = edidio[i];
  return total;
}

size_t spektraControl(uint8_t* out, size_t cap, int32_t messageId, int spektraType, int zone, int index, int action) {
  uint8_t body[24];
  Writer b(body, sizeof(body));
  b.uintField(1, (uint32_t)spektraType, false);
  b.uintField(2, (uint32_t)zone, false);
  b.uintField(3, (uint32_t)index, false);
  b.uintField(4, (uint32_t)action, false);
  if (!b.ok) return 0;

  uint8_t edidio[40];
  Writer e(edidio, sizeof(edidio));
  e.uintField(1, (uint32_t)messageId, false);
  e.tag(27, 2);
  e.varint((uint32_t)b.len);
  for (size_t i = 0; i < b.len; i++) e.put(body[i]);
  if (!e.ok) return 0;

  size_t total = e.len + 3;
  if (total > cap) return 0;
  out[0] = 0xCD;
  out[1] = (uint8_t)((e.len >> 8) & 0xFF);
  out[2] = (uint8_t)(e.len & 0xFF);
  for (size_t i = 0; i < e.len; i++) out[3 + i] = edidio[i];
  return total;
}

size_t spektraStop(uint8_t* out, size_t cap, int32_t messageId, int zone, int lineMask) {
  // TriggerMessage body.
  uint8_t trigger[24];
  Writer t(trigger, sizeof(trigger));
  t.uintField(1, (uint32_t)TRIGGER_SPEKTRA_STOP_SEQ, false);
  t.uintField(2, (uint32_t)zone, false);
  t.uintField(3, (uint32_t)lineMask, false);
  if (!t.ok) return 0;

  // ExternalTriggerMessage: trigger (field 1, embedded).
  uint8_t external[32];
  Writer x(external, sizeof(external));
  x.tag(1, 2);
  x.varint((uint32_t)t.len);
  for (size_t i = 0; i < t.len; i++) x.put(trigger[i]);
  if (!x.ok) return 0;

  // EdidioMessage: message_id + external_trigger (field 21, embedded).
  uint8_t edidio[48];
  Writer e(edidio, sizeof(edidio));
  e.uintField(1, (uint32_t)messageId, false);
  e.tag(21, 2);
  e.varint((uint32_t)x.len);
  for (size_t i = 0; i < x.len; i++) e.put(external[i]);
  if (!e.ok) return 0;

  size_t total = e.len + 3;
  if (total > cap) return 0;
  out[0] = 0xCD;
  out[1] = (uint8_t)((e.len >> 8) & 0xFF);
  out[2] = (uint8_t)(e.len & 0xFF);
  for (size_t i = 0; i < e.len; i++) out[3 + i] = edidio[i];
  return total;
}

}  // namespace edidio
