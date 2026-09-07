/*
 * edidio_frames.h - Pure-C eDIDIO protocol frame encoder (dependency-free).
 *
 * For embedded / soft-processor targets: MicroBlaze, Nios V, RISC-V, or any
 * bare-metal / RTOS C environment (Xilinx Vitis, Intel Quartus, etc.). No libc
 * beyond <stdint.h>/<stddef.h>, no dynamic allocation, no protobuf runtime -
 * frames are built into a caller-owned uint8_t buffer.
 *
 * Produces byte-identical output to the reference implementation
 * (edidio_control_py) and every other eDIDIO encoder, verified by a host gcc
 * build against the shared reference frames (test/test_frames.c).
 *
 * Wire format: 0xCD + 2-byte big-endian length + a serialized EdidioMessage.
 * Send the returned bytes over your TCP stack (e.g. lwIP tcp_write / send()).
 */
#ifndef EDIDIO_FRAMES_H
#define EDIDIO_FRAMES_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* Custom DALI command enums */
#define EDIDIO_DALI_ARC_LEVEL        0
#define EDIDIO_DALI_GROUP_ARC_LEVEL  2
#define EDIDIO_DALI_BROADCAST_SCENE  3
#define EDIDIO_DALI_SCENE_ON_GROUP   4

/* DALI addressing: 0-63 individual, 64-79 group (address = 64 + group), 80
 * broadcast. Scenes use the standard DALI "GO TO SCENE X" command (0x10 + scene)
 * sent to the target address. */
#define EDIDIO_DALI_GROUP_ADDRESS_BASE  64
#define EDIDIO_DALI_BROADCAST_ADDRESS   80
#define EDIDIO_DALI_GO_TO_SCENE_BASE    0x10

/* Standard DALI commands (subset) */
#define EDIDIO_DALI_OFF        0
#define EDIDIO_DALI_MAX_LEVEL  5
#define EDIDIO_DALI_MIN_LEVEL  6

/* Spektra enums */
#define EDIDIO_SPEKTRA_SEQUENCE  1
#define EDIDIO_SPEKTRA_THEME     2
#define EDIDIO_SPEKTRA_STATIC    3
#define EDIDIO_SPEKTRA_START     0
#define EDIDIO_SPEKTRA_STOP      1
#define EDIDIO_SPEKTRA_PAUSE     2
#define EDIDIO_TRIGGER_SPEKTRA_STOP_SEQ  13

#define EDIDIO_ARC_LEVEL_MAX 254

/* Keep-alive / "Are You There" heartbeat frame (2 bytes). */
extern const uint8_t edidio_keep_alive[2];

/* 1-based physical line (1-4) -> single-bit line mask. */
static inline int edidio_line_mask(int line) { return 1 << (line - 1); }

/*
 * Each builder writes a framed message into `out` (capacity `cap`) and returns
 * the number of bytes written, or 0 if the buffer is too small. 64 bytes is
 * ample for the DALI/Spektra builders; DMX needs room for the level payload.
 */
size_t edidio_dali_arc_level(uint8_t *out, size_t cap, uint32_t message_id,
                             int line_mask, int address, int level);
size_t edidio_dali_group_arc_level(uint8_t *out, size_t cap, uint32_t message_id,
                                   int line_mask, int group, int level);
size_t edidio_dali_command(uint8_t *out, size_t cap, uint32_t message_id,
                           int line_mask, int address, int command, int arg);
size_t edidio_dali_broadcast_scene(uint8_t *out, size_t cap, uint32_t message_id,
                                   int line_mask, int scene);
size_t edidio_dali_scene_on_group(uint8_t *out, size_t cap, uint32_t message_id,
                                  int line_mask, int group, int scene);
size_t edidio_dmx_level(uint8_t *out, size_t cap, uint32_t message_id, int zone,
                        int universe_mask, int channel, int repeat,
                        const uint8_t *levels, size_t level_count, int fade_by_10ms);
size_t edidio_spektra_control(uint8_t *out, size_t cap, uint32_t message_id,
                              int spektra_type, int zone, int index, int action);
size_t edidio_spektra_stop(uint8_t *out, size_t cap, uint32_t message_id,
                           int zone, int line_mask);

#ifdef __cplusplus
}
#endif

#endif /* EDIDIO_FRAMES_H */
