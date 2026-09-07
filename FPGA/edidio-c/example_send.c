/*
 * example_send.c - illustrative eDIDIO send over a soft-processor TCP stack.
 *
 * Two flavours are shown (guarded by macros): a BSD-socket send (Linux / Nios
 * with the socket layer) and an lwIP raw/netconn sketch (bare-metal MicroBlaze /
 * RISC-V with lwIP). Adapt to your platform's TCP API - the important part is
 * that the eDIDIO frame bytes from edidio_frames.* are sent verbatim.
 */

#include "edidio_frames.h"

/* ---- BSD sockets (e.g. Nios V / Linux) ---------------------------------- */
#ifdef EDIDIO_USE_BSD_SOCKETS
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>

int edidio_example_bsd(const char *ip) {
    int s = socket(AF_INET, SOCK_STREAM, 0);
    struct sockaddr_in addr;
    uint8_t buf[64];
    size_t n;
    if (s < 0) return -1;
    addr.sin_family = AF_INET;
    addr.sin_port = htons(23);              /* eDIDIO TCP */
    inet_pton(AF_INET, ip, &addr.sin_addr);
    if (connect(s, (struct sockaddr *)&addr, sizeof(addr)) != 0) { close(s); return -1; }

    /* On a hardware trigger (e.g. a machine-vision exposure pin), recall scene 3: */
    n = edidio_dali_broadcast_scene(buf, sizeof(buf), 1, edidio_line_mask(1), 3);
    send(s, buf, n, 0);

    close(s);
    return 0;
}
#endif

/* ---- lwIP netconn sketch (bare-metal MicroBlaze / RISC-V) --------------- */
#ifdef EDIDIO_USE_LWIP
#include "lwip/api.h"

int edidio_example_lwip(const ip_addr_t *server) {
    struct netconn *conn = netconn_new(NETCONN_TCP);
    uint8_t buf[64];
    size_t n;
    if (conn == NULL) return -1;
    if (netconn_connect(conn, server, 23) != ERR_OK) { netconn_delete(conn); return -1; }

    n = edidio_dali_arc_level(buf, sizeof(buf), 1, edidio_line_mask(1), 5, 254);
    netconn_write(conn, buf, n, NETCONN_COPY);

    netconn_close(conn);
    netconn_delete(conn);
    return 0;
}
#endif

/*
 * Typical FPGA use: an interrupt from a hardware pin (e.g. a camera exposure or
 * a sensor edge) calls one of the edidio_* builders and pushes the bytes to the
 * already-open TCP connection, so lighting reacts in lockstep with the hardware.
 */
