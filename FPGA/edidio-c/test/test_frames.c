/*
 * Host byte-equality test for the pure-C eDIDIO encoder.
 *   gcc -std=c99 -I.. test_frames.c ../edidio_frames.c -o test_frames && ./test_frames
 *
 * Reference hexes captured from edidio_control_py 0.3.0 (message_id=7) - the same
 * oracle used by every eDIDIO encoder.
 */
#include <stdio.h>
#include <string.h>
#include "edidio_frames.h"

static int failures = 0;

static void hex(const uint8_t *b, size_t n, char *out) {
    static const char *d = "0123456789abcdef";
    size_t i;
    for (i = 0; i < n; i++) {
        out[i * 2]     = d[(b[i] >> 4) & 0xF];
        out[i * 2 + 1] = d[b[i] & 0xF];
    }
    out[n * 2] = '\0';
}

static void check(const char *name, const uint8_t *frame, size_t n, const char *want) {
    char got[256];
    hex(frame, n, got);
    if (strcmp(got, want) == 0) {
        printf("[ok]   %s\n", name);
    } else {
        printf("[FAIL] %s\n  got:  %s\n  want: %s\n", name, got, want);
        failures++;
    }
}

int main(void) {
    const uint32_t MID = 7;
    uint8_t buf[128];
    uint8_t rgb[3];
    uint8_t lv[3];
    size_t n;

    n = edidio_dali_arc_level(buf, sizeof(buf), MID, edidio_line_mask(1), 5, 200);
    check("arc", buf, n, "cd000e080792010908011005300048c801");

    n = edidio_dali_group_arc_level(buf, sizeof(buf), MID, edidio_line_mask(1), 3, 128);
    check("group", buf, n, "cd000e0807920109080110433000488001");

    n = edidio_dali_command(buf, sizeof(buf), MID, edidio_line_mask(2), 10, EDIDIO_DALI_MAX_LEVEL, 0);
    check("cmd", buf, n, "cd000d08079201080802100a28054800");

    n = edidio_dali_command(buf, sizeof(buf), MID, edidio_line_mask(1), 0, EDIDIO_DALI_OFF, 0);
    check("cmd_off", buf, n, "cd000b0807920106080128004800");

    n = edidio_dali_broadcast_scene(buf, sizeof(buf), MID, edidio_line_mask(1), 3);
    check("bscene", buf, n, "cd000b0807920106080110502813");

    n = edidio_dali_scene_on_group(buf, sizeof(buf), MID, edidio_line_mask(1), 4, 3);
    check("gscene", buf, n, "cd000b0807920106080110442813");

    rgb[0] = 255; rgb[1] = 0; rgb[2] = 0;
    n = edidio_dmx_level(buf, sizeof(buf), MID, 255, 2, 1, 10, rgb, 3, 0);
    check("dmx", buf, n, "cd00140807a2010f08ff0110021801200a2a04ff010000");

    lv[0] = 10; lv[1] = 20; lv[2] = 30;
    n = edidio_dmx_level(buf, sizeof(buf), MID, 0, 1, 1, 1, lv, 3, 50);
    check("dmx_fade", buf, n, "cd00120807a2010d1001180120012a030a141e3032");

    n = edidio_spektra_control(buf, sizeof(buf), MID, EDIDIO_SPEKTRA_SEQUENCE, 1, 2, EDIDIO_SPEKTRA_START);
    check("spektra", buf, n, "cd000b0807da0106080110011802");

    n = edidio_spektra_stop(buf, sizeof(buf), MID, 1, 0xFF);
    check("spektra_stop", buf, n, "cd000e0807aa01090a07080d100118ff01");

    printf("\n%s\n", failures == 0 ? "ALL PASSED" : "FAILURES PRESENT");
    return failures == 0 ? 0 : 1;
}
