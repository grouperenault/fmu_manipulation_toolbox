#include <stdlib.h>
#include <string.h>

#include "fmi2Functions.h"
#include "stub_xcp.h"

/*
 * FMI 2.0 Co-Simulation FMU of FMI-LS-XCP used by the native tests (descriptor:
 * tests/data/ls-xcp/stub_xcp_fmi2/modelDescription.xml). The XCP configuration variables are fixed parameters: they
 * can be set until the service starts, in fmi2SetupExperiment; a later set is refused (fmi2Error) and journaled.
 */

typedef struct {
    stub_xcp_t      xcp;
    fmi2Real        time;
    fmi2Integer     counter;
} stub_t;


const char* fmi2GetTypesPlatform(void) {
    return fmi2TypesPlatform;
}


const char* fmi2GetVersion(void) {
    return fmi2Version;
}


fmi2Status fmi2SetDebugLogging(fmi2Component c, fmi2Boolean loggingOn, size_t nCategories,
                               const fmi2String categories[]) {
    (void)c; (void)loggingOn; (void)nCategories; (void)categories;
    return fmi2OK;
}


fmi2Component fmi2Instantiate(fmi2String instanceName, fmi2Type fmuType, fmi2String fmuGUID,
                              fmi2String fmuResourceLocation, const fmi2CallbackFunctions* functions,
                              fmi2Boolean visible, fmi2Boolean loggingOn) {
    (void)instanceName; (void)fmuType; (void)fmuGUID; (void)functions; (void)visible; (void)loggingOn;

    stub_t *stub = calloc(1, sizeof(*stub));
    if (stub)
        stub_xcp_init(&stub->xcp, fmuResourceLocation);
    return stub;
}


void fmi2FreeInstance(fmi2Component c) {
    free(c);
}


fmi2Status fmi2SetupExperiment(fmi2Component c, fmi2Boolean toleranceDefined, fmi2Real tolerance,
                               fmi2Real startTime, fmi2Boolean stopTimeDefined, fmi2Real stopTime) {
    stub_t *stub = c;
    (void)toleranceDefined; (void)tolerance; (void)stopTimeDefined; (void)stopTime;

    stub->time = startTime;
    stub_xcp_start(&stub->xcp, "fmi2SetupExperiment");
    return fmi2OK;
}


fmi2Status fmi2EnterInitializationMode(fmi2Component c) {
    (void)c;
    return fmi2OK;
}


fmi2Status fmi2ExitInitializationMode(fmi2Component c) {
    (void)c;
    return fmi2OK;
}


fmi2Status fmi2Terminate(fmi2Component c) {
    stub_t *stub = c;

    stub_xcp_stop(&stub->xcp, "fmi2Terminate");
    return fmi2OK;
}


fmi2Status fmi2Reset(fmi2Component c) {
    stub_t *stub = c;

    stub_xcp_stop(&stub->xcp, "fmi2Reset");
    return fmi2OK;
}


/* Whether the XCP configuration variable `name` can be set: only before the start of the service. */
static int stub_can_configure(const stub_t *stub, const char *name) {
    if (stub->xcp.started) {
        stub_xcp_refuse(&stub->xcp, name, "started service");
        return 0;
    }
    return 1;
}


fmi2Status fmi2GetReal(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2Real value[]) {
    (void)c; (void)vr; (void)value;
    return nvr == 0 ? fmi2OK : fmi2Error;
}


fmi2Status fmi2SetReal(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2Real value[]) {
    (void)c; (void)vr; (void)value;
    return nvr == 0 ? fmi2OK : fmi2Error;
}


fmi2Status fmi2GetInteger(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2Integer value[]) {
    const stub_t *stub = c;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] == STUB_XCP_VR_PORT)
            value[i] = (fmi2Integer)stub->xcp.port;
        else if (vr[i] == STUB_XCP_VR_COUNTER)
            value[i] = stub->counter;
        else
            return fmi2Error;
    }
    return fmi2OK;
}


fmi2Status fmi2SetInteger(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2Integer value[]) {
    stub_t *stub = c;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_PORT || value[i] < 0 || !stub_can_configure(stub, "port"))
            return fmi2Error;
        stub_xcp_set_port(&stub->xcp, (unsigned)value[i]);
    }
    return fmi2OK;
}


fmi2Status fmi2GetBoolean(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2Boolean value[]) {
    const stub_t *stub = c;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ENABLE)
            return fmi2Error;
        value[i] = stub->xcp.enable ? fmi2True : fmi2False;
    }
    return fmi2OK;
}


fmi2Status fmi2SetBoolean(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2Boolean value[]) {
    stub_t *stub = c;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ENABLE || !stub_can_configure(stub, "enable"))
            return fmi2Error;
        stub_xcp_set_enable(&stub->xcp, value[i] != fmi2False);
    }
    return fmi2OK;
}


fmi2Status fmi2GetString(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2String value[]) {
    const stub_t *stub = c;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ADDRESS)
            return fmi2Error;
        value[i] = stub->xcp.address;
    }
    return fmi2OK;
}


fmi2Status fmi2SetString(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2String value[]) {
    stub_t *stub = c;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ADDRESS || !stub_can_configure(stub, "address"))
            return fmi2Error;
        stub_xcp_set_address(&stub->xcp, value[i]);
    }
    return fmi2OK;
}


fmi2Status fmi2DoStep(fmi2Component c, fmi2Real currentCommunicationPoint, fmi2Real communicationStepSize,
                      fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    stub_t *stub = c;
    (void)noSetFMUStatePriorToCurrentPoint;

    stub->time = currentCommunicationPoint + communicationStepSize;
    stub->counter += 1;
    return fmi2OK;
}


fmi2Status fmi2GetRealStatus(fmi2Component c, const fmi2StatusKind s, fmi2Real* value) {
    const stub_t *stub = c;
    (void)s;

    *value = stub->time;
    return fmi2OK;
}


fmi2Status fmi2GetBooleanStatus(fmi2Component c, const fmi2StatusKind s, fmi2Boolean* value) {
    (void)c; (void)s;
    *value = fmi2False;
    return fmi2OK;
}
