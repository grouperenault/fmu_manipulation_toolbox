#include <stdlib.h>
#include <string.h>

#include "fmi2Functions.h"

/*
 * FMI 2.0 Co-Simulation FMU used by the native tests. Its behaviour is chosen by the GUID given to fmi2Instantiate:
 *   - "{stub}":                    every call succeeds;
 *   - "{stub-fail-instantiate}":   fmi2Instantiate returns NULL.
 * Each type has STUB_NB_VARIABLES variables (VR 0 to STUB_NB_VARIABLES-1); any other VR is an error.
 */

#define STUB_NB_VARIABLES   16

typedef struct {
    fmi2Real                reals[STUB_NB_VARIABLES];
    fmi2Integer             integers[STUB_NB_VARIABLES];
    fmi2Boolean             booleans[STUB_NB_VARIABLES];
    char                    *strings[STUB_NB_VARIABLES];
} stub_t;


static fmi2Status stub_check_vr(const fmi2ValueReference vr[], size_t nvr) {
    for (size_t i = 0; i < nvr; i += 1)
        if (vr[i] >= STUB_NB_VARIABLES)
            return fmi2Error;
    return fmi2OK;
}


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
    (void)instanceName; (void)fmuType; (void)fmuResourceLocation; (void)functions; (void)visible; (void)loggingOn;

    if (strcmp(fmuGUID, "{stub-fail-instantiate}") == 0)
        return NULL;

    stub_t *stub = calloc(1, sizeof(*stub));
    return stub;
}


void fmi2FreeInstance(fmi2Component c) {
    stub_t *stub = c;

    if (stub) {
        for (int i = 0; i < STUB_NB_VARIABLES; i += 1)
            free(stub->strings[i]);
        free(stub);
    }
}


fmi2Status fmi2SetupExperiment(fmi2Component c, fmi2Boolean toleranceDefined, fmi2Real tolerance,
                               fmi2Real startTime, fmi2Boolean stopTimeDefined, fmi2Real stopTime) {
    (void)c; (void)toleranceDefined; (void)tolerance; (void)startTime; (void)stopTimeDefined; (void)stopTime;
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
    (void)c;
    return fmi2OK;
}


fmi2Status fmi2Reset(fmi2Component c) {
    (void)c;
    return fmi2OK;
}


#define STUB_GETTER(fmi_type, c_type, field)                                                    \
fmi2Status fmi2Get ## fmi_type(fmi2Component c, const fmi2ValueReference vr[], size_t nvr,      \
                               c_type value[]) {                                                \
    const stub_t *stub = c;                                                                     \
    if (stub_check_vr(vr, nvr) != fmi2OK)                                                       \
        return fmi2Error;                                                                       \
    for (size_t i = 0; i < nvr; i += 1)                                                         \
        value[i] = stub->field[vr[i]];                                                          \
    return fmi2OK;                                                                              \
}

#define STUB_SETTER(fmi_type, c_type, field)                                                    \
fmi2Status fmi2Set ## fmi_type(fmi2Component c, const fmi2ValueReference vr[], size_t nvr,      \
                               const c_type value[]) {                                          \
    stub_t *stub = c;                                                                           \
    if (stub_check_vr(vr, nvr) != fmi2OK)                                                       \
        return fmi2Error;                                                                       \
    for (size_t i = 0; i < nvr; i += 1)                                                         \
        stub->field[vr[i]] = value[i];                                                          \
    return fmi2OK;                                                                              \
}

STUB_GETTER(Real,       fmi2Real,       reals)
STUB_GETTER(Integer,    fmi2Integer,    integers)
STUB_GETTER(Boolean,    fmi2Boolean,    booleans)
STUB_SETTER(Real,       fmi2Real,       reals)
STUB_SETTER(Integer,    fmi2Integer,    integers)
STUB_SETTER(Boolean,    fmi2Boolean,    booleans)
#undef STUB_GETTER
#undef STUB_SETTER


fmi2Status fmi2GetString(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2String value[]) {
    const stub_t *stub = c;

    if (stub_check_vr(vr, nvr) != fmi2OK)
        return fmi2Error;
    for (size_t i = 0; i < nvr; i += 1)
        value[i] = stub->strings[vr[i]] ? stub->strings[vr[i]] : "";
    return fmi2OK;
}


fmi2Status fmi2SetString(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2String value[]) {
    stub_t *stub = c;

    if (stub_check_vr(vr, nvr) != fmi2OK)
        return fmi2Error;
    for (size_t i = 0; i < nvr; i += 1) {
        char *copy = strdup(value[i]);
        if (!copy)
            return fmi2Error;
        free(stub->strings[vr[i]]);
        stub->strings[vr[i]] = copy;
    }
    return fmi2OK;
}


fmi2Status fmi2DoStep(fmi2Component c, fmi2Real currentCommunicationPoint, fmi2Real communicationStepSize,
                      fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    (void)c; (void)currentCommunicationPoint; (void)communicationStepSize; (void)noSetFMUStatePriorToCurrentPoint;
    return fmi2OK;
}


fmi2Status fmi2GetRealStatus(fmi2Component c, const fmi2StatusKind s, fmi2Real* value) {
    (void)c; (void)s;
    *value = 0.0;
    return fmi2OK;
}


fmi2Status fmi2GetBooleanStatus(fmi2Component c, const fmi2StatusKind s, fmi2Boolean* value) {
    (void)c; (void)s;
    *value = fmi2False;
    return fmi2OK;
}
