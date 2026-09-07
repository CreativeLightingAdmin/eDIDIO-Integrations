/* edidio_frames.c - pure-C eDIDIO frame encoder implementation. */

#include "edidio_frames.h"

const uint8_t edidio_keep_alive[2] = { 0xFF, 0xF6 };

/*
 * A tiny append-only byte writer over a caller buffer. `ok` goes false on
 * overflow so builders can bail without writing past the end.
 */
typedef struct {
    uint8_t *buf;
    size_t   cap;
    size_t   len;
    int      ok;
} ed_writer;

static void ed_put(ed_writer *w, uint8_t v) {
    if (w->len < w->cap) {
        w->buf[w->len++] = v;
    } else {
        w->ok = 0;
    }
}

static void ed_varint(ed_writer *w, uint32_t v) {
    while (v >= 128u) {
        ed_put(w, (uint8_t)((v & 0x7Fu) | 0x80u));
        v >>= 7;
    }
    ed_put(w, (uint8_t)v);
}

static void ed_tag(ed_writer *w, int field, int wire) {
    ed_varint(w, (uint32_t)((field << 3) | wire));
}

/* A varint (uint32/enum) field. Omitted when 0 unless `always`. */
static void ed_uint(ed_writer *w, int field, uint32_t value, int always) {
    if (value == 0u && !always) return;
    ed_tag(w, field, 0);
    ed_varint(w, value);
}

static int ed_clamp(int v, int lo, int hi) {
    if (v < lo) return lo;
    if (v > hi) return hi;
    return v;
}

/* Frame a message body (built into scratch) into out with the 0xCD header. */
static size_t ed_frame(uint8_t *out, size_t cap, const uint8_t *body, size_t body_len) {
    size_t total = body_len + 3u;
    size_t i;
    if (total > cap) return 0;
    out[0] = 0xCD;
    out[1] = (uint8_t)((body_len >> 8) & 0xFF);
    out[2] = (uint8_t)(body_len & 0xFF);
    for (i = 0; i < body_len; i++) out[3 + i] = body[i];
    return total;
}

static size_t ed_frame_dali(uint8_t *out, size_t cap, uint32_t message_id, int line_mask,
                            int address, int command, int custom_command, int arg) {
    uint8_t dali[32];
    uint8_t edidio[48];
    ed_writer b, e;
    b.buf = dali; b.cap = sizeof(dali); b.len = 0; b.ok = 1;

    ed_uint(&b, 1, (uint32_t)line_mask, 0);
    ed_uint(&b, 2, (uint32_t)address, 0);
    if (command >= 0)         ed_uint(&b, 5, (uint32_t)command, 1);
    if (custom_command >= 0)  ed_uint(&b, 6, (uint32_t)custom_command, 1);
    if (arg >= 0)             ed_uint(&b, 9, (uint32_t)arg, 1);
    if (!b.ok) return 0;

    e.buf = edidio; e.cap = sizeof(edidio); e.len = 0; e.ok = 1;
    ed_uint(&e, 1, message_id, 0);
    ed_tag(&e, 18, 2);
    ed_varint(&e, (uint32_t)b.len);
    { size_t i; for (i = 0; i < b.len; i++) ed_put(&e, dali[i]); }
    if (!e.ok) return 0;

    return ed_frame(out, cap, edidio, e.len);
}

size_t edidio_dali_arc_level(uint8_t *out, size_t cap, uint32_t message_id,
                             int line_mask, int address, int level) {
    return ed_frame_dali(out, cap, message_id, line_mask, address, -1,
                         EDIDIO_DALI_ARC_LEVEL, ed_clamp(level, 0, EDIDIO_ARC_LEVEL_MAX));
}

size_t edidio_dali_group_arc_level(uint8_t *out, size_t cap, uint32_t message_id,
                                   int line_mask, int group, int level) {
    /* DALI_ARC_LEVEL to the group address (64 + group). */
    return ed_frame_dali(out, cap, message_id, line_mask, EDIDIO_DALI_GROUP_ADDRESS_BASE + group, -1,
                         EDIDIO_DALI_ARC_LEVEL, ed_clamp(level, 0, EDIDIO_ARC_LEVEL_MAX));
}

size_t edidio_dali_command(uint8_t *out, size_t cap, uint32_t message_id,
                           int line_mask, int address, int command, int arg) {
    return ed_frame_dali(out, cap, message_id, line_mask, address, command, -1, arg);
}

size_t edidio_dali_broadcast_scene(uint8_t *out, size_t cap, uint32_t message_id,
                                   int line_mask, int scene) {
    /* Raw "GO TO SCENE X" command (0x10 + scene) to broadcast address 80. */
    return ed_frame_dali(out, cap, message_id, line_mask, EDIDIO_DALI_BROADCAST_ADDRESS,
                         EDIDIO_DALI_GO_TO_SCENE_BASE + scene, -1, -1);
}

size_t edidio_dali_scene_on_group(uint8_t *out, size_t cap, uint32_t message_id,
                                  int line_mask, int group, int scene) {
    /* Raw "GO TO SCENE X" command (0x10 + scene) to the group address (64 + group). */
    return ed_frame_dali(out, cap, message_id, line_mask, EDIDIO_DALI_GROUP_ADDRESS_BASE + group,
                         EDIDIO_DALI_GO_TO_SCENE_BASE + scene, -1, -1);
}

size_t edidio_dmx_level(uint8_t *out, size_t cap, uint32_t message_id, int zone,
                        int universe_mask, int channel, int repeat,
                        const uint8_t *levels, size_t level_count, int fade_by_10ms) {
    uint8_t packed[128];
    uint8_t body[160];
    uint8_t edidio[176];
    ed_writer p, b, e;
    size_t i;

    p.buf = packed; p.cap = sizeof(packed); p.len = 0; p.ok = 1;
    for (i = 0; i < level_count; i++) ed_varint(&p, (uint32_t)ed_clamp(levels[i], 0, 255));
    if (!p.ok) return 0;

    b.buf = body; b.cap = sizeof(body); b.len = 0; b.ok = 1;
    ed_uint(&b, 1, (uint32_t)zone, 0);
    ed_uint(&b, 2, (uint32_t)universe_mask, 0);
    ed_uint(&b, 3, (uint32_t)channel, 0);
    ed_uint(&b, 4, (uint32_t)repeat, 0);
    ed_tag(&b, 5, 2);
    ed_varint(&b, (uint32_t)p.len);
    for (i = 0; i < p.len; i++) ed_put(&b, packed[i]);
    ed_uint(&b, 6, (uint32_t)fade_by_10ms, 0);
    if (!b.ok) return 0;

    e.buf = edidio; e.cap = sizeof(edidio); e.len = 0; e.ok = 1;
    ed_uint(&e, 1, message_id, 0);
    ed_tag(&e, 20, 2);
    ed_varint(&e, (uint32_t)b.len);
    for (i = 0; i < b.len; i++) ed_put(&e, body[i]);
    if (!e.ok) return 0;

    return ed_frame(out, cap, edidio, e.len);
}

size_t edidio_spektra_control(uint8_t *out, size_t cap, uint32_t message_id,
                              int spektra_type, int zone, int index, int action) {
    uint8_t body[24];
    uint8_t edidio[40];
    ed_writer b, e;
    size_t i;

    b.buf = body; b.cap = sizeof(body); b.len = 0; b.ok = 1;
    ed_uint(&b, 1, (uint32_t)spektra_type, 0);
    ed_uint(&b, 2, (uint32_t)zone, 0);
    ed_uint(&b, 3, (uint32_t)index, 0);
    ed_uint(&b, 4, (uint32_t)action, 0);
    if (!b.ok) return 0;

    e.buf = edidio; e.cap = sizeof(edidio); e.len = 0; e.ok = 1;
    ed_uint(&e, 1, message_id, 0);
    ed_tag(&e, 27, 2);
    ed_varint(&e, (uint32_t)b.len);
    for (i = 0; i < b.len; i++) ed_put(&e, body[i]);
    if (!e.ok) return 0;

    return ed_frame(out, cap, edidio, e.len);
}

size_t edidio_spektra_stop(uint8_t *out, size_t cap, uint32_t message_id,
                           int zone, int line_mask) {
    uint8_t trigger[24];
    uint8_t external[32];
    uint8_t edidio[48];
    ed_writer t, x, e;
    size_t i;

    t.buf = trigger; t.cap = sizeof(trigger); t.len = 0; t.ok = 1;
    ed_uint(&t, 1, (uint32_t)EDIDIO_TRIGGER_SPEKTRA_STOP_SEQ, 0);
    ed_uint(&t, 2, (uint32_t)zone, 0);
    ed_uint(&t, 3, (uint32_t)line_mask, 0);
    if (!t.ok) return 0;

    x.buf = external; x.cap = sizeof(external); x.len = 0; x.ok = 1;
    ed_tag(&x, 1, 2);
    ed_varint(&x, (uint32_t)t.len);
    for (i = 0; i < t.len; i++) ed_put(&x, trigger[i]);
    if (!x.ok) return 0;

    e.buf = edidio; e.cap = sizeof(edidio); e.len = 0; e.ok = 1;
    ed_uint(&e, 1, message_id, 0);
    ed_tag(&e, 21, 2);
    ed_varint(&e, (uint32_t)x.len);
    for (i = 0; i < x.len; i++) ed_put(&e, external[i]);
    if (!e.ok) return 0;

    return ed_frame(out, cap, edidio, e.len);
}
