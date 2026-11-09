#ifndef STUB_XCP_H
#define STUB_XCP_H

#include <stdbool.h>
#include <stdio.h>
#include <string.h>

/*
 * XCP service of the stub FMUs of FMI-LS-XCP (stub_xcp_fmi2.c, stub_xcp_fmi3.c), without real XCP: the service only
 * writes what it receives and does in a journal, <resources directory of the FMU>/xcp.log, read by the native tests:
 *   set enable=<0|1> | set port=<n> | set address=<text>
 *   refused <variable> in <state>
 *   start tcp <address>:<port> at <function> | disabled at <function>
 *   stop at <function>
 * The variables are those of tests/data/ls-xcp/stub_xcp_fmi<2|3>/modelDescription.xml.
 */

#define STUB_XCP_VR_TIME        0
#define STUB_XCP_VR_ENABLE      1
#define STUB_XCP_VR_PORT        2
#define STUB_XCP_VR_ADDRESS     3
#define STUB_XCP_VR_COUNTER     4

typedef struct {
    char        journal[4096];
    bool        enable;
    unsigned    port;
    char        address[64];
    bool        started;
} stub_xcp_t;


static void stub_xcp_log(const stub_xcp_t *xcp, const char *line) {
    FILE *file = fopen(xcp->journal, "a");
    if (!file)
        return;
    fprintf(file, "%s\n", line);
    fclose(file);
}


/* resource_location: a path (FMI 3.0) or a "file:" URI (FMI 2.0). */
static void stub_xcp_init(stub_xcp_t *xcp, const char *resource_location) {
    const char *path = resource_location ? resource_location : "";

    if (strncmp(path, "file:", 5) == 0)
        path += 5;
    while (path[0] == '/' && path[1] == '/')
        path += 1;
    if (path[0] == '/' && path[1] && path[2] == ':')    /* "/C:/..." */
        path += 1;
    snprintf(xcp->journal, sizeof(xcp->journal), "%s/xcp.log", path);

    xcp->enable = true;
    xcp->port = 5555;
    snprintf(xcp->address, sizeof(xcp->address), "127.0.0.1");
    xcp->started = false;
}


static void stub_xcp_set_enable(stub_xcp_t *xcp, bool enable) {
    char line[64];
    xcp->enable = enable;
    snprintf(line, sizeof(line), "set enable=%d", enable ? 1 : 0);
    stub_xcp_log(xcp, line);
}


static void stub_xcp_set_port(stub_xcp_t *xcp, unsigned port) {
    char line[64];
    xcp->port = port;
    snprintf(line, sizeof(line), "set port=%u", port);
    stub_xcp_log(xcp, line);
}


static void stub_xcp_set_address(stub_xcp_t *xcp, const char *address) {
    char line[128];
    snprintf(xcp->address, sizeof(xcp->address), "%s", address);
    snprintf(line, sizeof(line), "set address=%s", xcp->address);
    stub_xcp_log(xcp, line);
}


static void stub_xcp_refuse(const stub_xcp_t *xcp, const char *variable, const char *state) {
    char line[256];
    snprintf(line, sizeof(line), "refused %s in %s", variable, state);
    stub_xcp_log(xcp, line);
}


/* Starts the service, once, when it is enabled. */
static void stub_xcp_start(stub_xcp_t *xcp, const char *function) {
    char line[256];

    if (xcp->started)
        return;
    xcp->started = true;
    if (xcp->enable)
        snprintf(line, sizeof(line), "start tcp %s:%u at %s", xcp->address, xcp->port, function);
    else
        snprintf(line, sizeof(line), "disabled at %s", function);
    stub_xcp_log(xcp, line);
}


static void stub_xcp_stop(stub_xcp_t *xcp, const char *function) {
    char line[128];
    if (xcp->started && xcp->enable) {
        snprintf(line, sizeof(line), "stop at %s", function);
        stub_xcp_log(xcp, line);
    }
    xcp->started = false;
}

#endif
