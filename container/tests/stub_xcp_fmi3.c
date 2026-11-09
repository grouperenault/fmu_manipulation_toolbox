#include <stdlib.h>
#include <string.h>

#include "fmi3Functions.h"
#include "stub_xcp.h"

/*
 * FMI 3.0 Co-Simulation FMU of FMI-LS-XCP used by the native tests (descriptor:
 * tests/data/ls-xcp/stub_xcp_fmi3/modelDescription.xml). The XCP configuration variables are fixed structural
 * parameters: they can only be set in Configuration Mode, any other set is refused (fmi3Error) and journaled. The
 * service starts in fmi3ExitConfigurationMode, or in fmi3EnterInitializationMode at the latest.
 */

typedef enum {
    STUB_INSTANTIATED,
    STUB_CONFIGURATION,
    STUB_INITIALIZATION,
    STUB_STEP,
} stub_state_t;

static const char *const STUB_STATE_NAMES[] = {"Instantiated", "Configuration Mode", "Initialization Mode",
                                               "Step Mode"};

typedef struct {
    stub_xcp_t      xcp;
    stub_state_t    state;
    fmi3Float64     time;
    fmi3Int32       counter;
} stub_t;


/* Whether the XCP configuration variable `name` can be set: only in Configuration Mode. */
static int stub_can_configure(const stub_t *stub, const char *name) {
    if (stub->state != STUB_CONFIGURATION) {
        stub_xcp_refuse(&stub->xcp, name, STUB_STATE_NAMES[stub->state]);
        return 0;
    }
    return 1;
}


const char* fmi3GetVersion(void) {
    return fmi3Version;
}


fmi3Status fmi3SetDebugLogging(fmi3Instance instance, fmi3Boolean loggingOn, size_t nCategories,
                               const fmi3String categories[]) {
    (void)instance; (void)loggingOn; (void)nCategories; (void)categories;
    return fmi3OK;
}


fmi3Instance fmi3InstantiateCoSimulation(fmi3String instanceName, fmi3String instantiationToken,
                                         fmi3String resourcePath, fmi3Boolean visible, fmi3Boolean loggingOn,
                                         fmi3Boolean eventModeUsed, fmi3Boolean earlyReturnAllowed,
                                         const fmi3ValueReference requiredIntermediateVariables[],
                                         size_t nRequiredIntermediateVariables,
                                         fmi3InstanceEnvironment instanceEnvironment,
                                         fmi3LogMessageCallback logMessage,
                                         fmi3IntermediateUpdateCallback intermediateUpdate) {
    (void)instanceName; (void)instantiationToken; (void)visible; (void)loggingOn; (void)eventModeUsed;
    (void)earlyReturnAllowed; (void)requiredIntermediateVariables; (void)nRequiredIntermediateVariables;
    (void)instanceEnvironment; (void)logMessage; (void)intermediateUpdate;

    stub_t *stub = calloc(1, sizeof(*stub));
    if (stub) {
        stub_xcp_init(&stub->xcp, resourcePath);
        stub->state = STUB_INSTANTIATED;
    }
    return stub;
}


void fmi3FreeInstance(fmi3Instance instance) {
    free(instance);
}


fmi3Status fmi3EnterConfigurationMode(fmi3Instance instance) {
    stub_t *stub = instance;

    if (stub->state != STUB_INSTANTIATED)
        return fmi3Error;
    stub->state = STUB_CONFIGURATION;
    return fmi3OK;
}


fmi3Status fmi3ExitConfigurationMode(fmi3Instance instance) {
    stub_t *stub = instance;

    if (stub->state != STUB_CONFIGURATION)
        return fmi3Error;
    stub->state = STUB_INSTANTIATED;
    stub_xcp_start(&stub->xcp, "fmi3ExitConfigurationMode");
    return fmi3OK;
}


fmi3Status fmi3EnterInitializationMode(fmi3Instance instance, fmi3Boolean toleranceDefined, fmi3Float64 tolerance,
                                       fmi3Float64 startTime, fmi3Boolean stopTimeDefined, fmi3Float64 stopTime) {
    stub_t *stub = instance;
    (void)toleranceDefined; (void)tolerance; (void)stopTimeDefined; (void)stopTime;

    if (stub->state != STUB_INSTANTIATED)
        return fmi3Error;
    stub->state = STUB_INITIALIZATION;
    stub->time = startTime;
    stub_xcp_start(&stub->xcp, "fmi3EnterInitializationMode");
    return fmi3OK;
}


fmi3Status fmi3ExitInitializationMode(fmi3Instance instance) {
    stub_t *stub = instance;

    stub->state = STUB_STEP;
    return fmi3OK;
}


fmi3Status fmi3EnterEventMode(fmi3Instance instance) {
    (void)instance;
    return fmi3OK;
}


fmi3Status fmi3EnterStepMode(fmi3Instance instance) {
    (void)instance;
    return fmi3OK;
}


fmi3Status fmi3Terminate(fmi3Instance instance) {
    stub_t *stub = instance;

    stub_xcp_stop(&stub->xcp, "fmi3Terminate");
    return fmi3OK;
}


fmi3Status fmi3Reset(fmi3Instance instance) {
    stub_t *stub = instance;

    stub_xcp_stop(&stub->xcp, "fmi3Reset");
    stub->state = STUB_INSTANTIATED;
    return fmi3OK;
}


/* Getters and setters of the types without variable: only an empty call succeeds. */
#define STUB_NO_VARIABLE(fmi_type, c_type)                                                              \
fmi3Status fmi3Get ## fmi_type(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,       \
                               c_type values[], size_t nValues) {                                       \
    (void)instance; (void)vr; (void)values; (void)nValues;                                              \
    return nvr == 0 ? fmi3OK : fmi3Error;                                                               \
}                                                                                                       \
fmi3Status fmi3Set ## fmi_type(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,       \
                               const c_type values[], size_t nValues) {                                 \
    (void)instance; (void)vr; (void)values; (void)nValues;                                              \
    return nvr == 0 ? fmi3OK : fmi3Error;                                                               \
}

STUB_NO_VARIABLE(Float32,   fmi3Float32)
STUB_NO_VARIABLE(Int8,      fmi3Int8)
STUB_NO_VARIABLE(UInt8,     fmi3UInt8)
STUB_NO_VARIABLE(Int16,     fmi3Int16)
STUB_NO_VARIABLE(UInt32,    fmi3UInt32)
STUB_NO_VARIABLE(Int64,     fmi3Int64)
STUB_NO_VARIABLE(UInt64,    fmi3UInt64)
#undef STUB_NO_VARIABLE


fmi3Status fmi3GetFloat64(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, fmi3Float64 values[],
                          size_t nValues) {
    const stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_TIME)
            return fmi3Error;
        values[i] = stub->time;
    }
    return fmi3OK;
}


fmi3Status fmi3SetFloat64(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,
                          const fmi3Float64 values[], size_t nValues) {
    (void)instance; (void)vr; (void)values; (void)nValues;
    return nvr == 0 ? fmi3OK : fmi3Error;
}


fmi3Status fmi3GetInt32(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, fmi3Int32 values[],
                        size_t nValues) {
    const stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_COUNTER)
            return fmi3Error;
        values[i] = stub->counter;
    }
    return fmi3OK;
}


fmi3Status fmi3SetInt32(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, const fmi3Int32 values[],
                        size_t nValues) {
    (void)instance; (void)vr; (void)values; (void)nValues;
    return nvr == 0 ? fmi3OK : fmi3Error;
}


fmi3Status fmi3GetUInt16(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, fmi3UInt16 values[],
                         size_t nValues) {
    const stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_PORT)
            return fmi3Error;
        values[i] = (fmi3UInt16)stub->xcp.port;
    }
    return fmi3OK;
}


fmi3Status fmi3SetUInt16(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,
                         const fmi3UInt16 values[], size_t nValues) {
    stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_PORT || !stub_can_configure(stub, "port"))
            return fmi3Error;
        stub_xcp_set_port(&stub->xcp, values[i]);
    }
    return fmi3OK;
}


fmi3Status fmi3GetBoolean(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, fmi3Boolean values[],
                          size_t nValues) {
    const stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ENABLE)
            return fmi3Error;
        values[i] = stub->xcp.enable ? fmi3True : fmi3False;
    }
    return fmi3OK;
}


fmi3Status fmi3SetBoolean(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,
                          const fmi3Boolean values[], size_t nValues) {
    stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ENABLE || !stub_can_configure(stub, "enable"))
            return fmi3Error;
        stub_xcp_set_enable(&stub->xcp, values[i] != fmi3False);
    }
    return fmi3OK;
}


fmi3Status fmi3GetString(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, fmi3String values[],
                         size_t nValues) {
    const stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ADDRESS)
            return fmi3Error;
        values[i] = stub->xcp.address;
    }
    return fmi3OK;
}


fmi3Status fmi3SetString(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,
                         const fmi3String values[], size_t nValues) {
    stub_t *stub = instance;
    (void)nValues;

    for (size_t i = 0; i < nvr; i += 1) {
        if (vr[i] != STUB_XCP_VR_ADDRESS || !stub_can_configure(stub, "address"))
            return fmi3Error;
        stub_xcp_set_address(&stub->xcp, values[i]);
    }
    return fmi3OK;
}


fmi3Status fmi3GetBinary(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, size_t valueSizes[],
                         fmi3Binary values[], size_t nValues) {
    (void)instance; (void)vr; (void)valueSizes; (void)values; (void)nValues;
    return nvr == 0 ? fmi3OK : fmi3Error;
}


fmi3Status fmi3SetBinary(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,
                         const size_t valueSizes[], const fmi3Binary values[], size_t nValues) {
    (void)instance; (void)vr; (void)valueSizes; (void)values; (void)nValues;
    return nvr == 0 ? fmi3OK : fmi3Error;
}


fmi3Status fmi3GetClock(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr, fmi3Clock values[]) {
    (void)instance; (void)vr; (void)values;
    return nvr == 0 ? fmi3OK : fmi3Error;
}


fmi3Status fmi3SetClock(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,
                        const fmi3Clock values[]) {
    (void)instance; (void)vr; (void)values;
    return nvr == 0 ? fmi3OK : fmi3Error;
}


fmi3Status fmi3GetIntervalDecimal(fmi3Instance instance, const fmi3ValueReference vr[], size_t nvr,
                                  fmi3Float64 intervals[], fmi3IntervalQualifier qualifiers[]) {
    (void)instance; (void)vr; (void)intervals; (void)qualifiers;
    return nvr == 0 ? fmi3OK : fmi3Error;
}


fmi3Status fmi3UpdateDiscreteStates(fmi3Instance instance, fmi3Boolean* discreteStatesNeedUpdate,
                                    fmi3Boolean* terminateSimulation, fmi3Boolean* nominalsOfContinuousStatesChanged,
                                    fmi3Boolean* valuesOfContinuousStatesChanged, fmi3Boolean* nextEventTimeDefined,
                                    fmi3Float64* nextEventTime) {
    (void)instance;
    *discreteStatesNeedUpdate = fmi3False;
    *terminateSimulation = fmi3False;
    *nominalsOfContinuousStatesChanged = fmi3False;
    *valuesOfContinuousStatesChanged = fmi3False;
    *nextEventTimeDefined = fmi3False;
    *nextEventTime = 0.0;
    return fmi3OK;
}


fmi3Status fmi3DoStep(fmi3Instance instance, fmi3Float64 currentCommunicationPoint,
                      fmi3Float64 communicationStepSize, fmi3Boolean noSetFMUStatePriorToCurrentPoint,
                      fmi3Boolean* eventHandlingNeeded, fmi3Boolean* terminateSimulation, fmi3Boolean* earlyReturn,
                      fmi3Float64* lastSuccessfulTime) {
    stub_t *stub = instance;
    (void)noSetFMUStatePriorToCurrentPoint;

    stub->time = currentCommunicationPoint + communicationStepSize;
    stub->counter += 1;
    *eventHandlingNeeded = fmi3False;
    *terminateSimulation = fmi3False;
    *earlyReturn = fmi3False;
    *lastSuccessfulTime = stub->time;
    return fmi3OK;
}
