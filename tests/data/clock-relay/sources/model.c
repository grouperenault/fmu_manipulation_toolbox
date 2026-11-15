/*
 * FMU of the tests of the output clocks of FMI-3.0 activated in Event Mode. Its behaviour depends on its
 * instantiationToken:
 *   - "{clock-relay-source}": its output clock `tx` ticks once, at the first communication point at or after t=0.5:
 *     fmi3DoStep asks for an Event Mode, and the clock is active when the Event Mode starts;
 *   - "{clock-relay}": a relay, its output clock `tx` ticks in fmi3UpdateDiscreteStates() when its input clock `rx`
 *     has ticked, without asking for another update of the discrete states;
 *   - "{clock-relay-needs-update}": the same relay, which asks for another update when `tx` ticks.
 * It counts the ticks of `rx` (`rx_count`) and of `tx` (`tx_count`).
 */
#include <stdlib.h>
#include <string.h>

#include "fmi3Functions.h"

#define VR_TX               1
#define VR_RX               2
#define VR_RX_COUNT         3
#define VR_TX_COUNT         4
#define SOURCE_TIME         0.5

enum { MODE_INSTANTIATED, MODE_INITIALIZATION, MODE_EVENT, MODE_STEP };

typedef struct {
    int                     mode;
    fmi3Float64             time;
    fmi3Boolean             event_mode_used;
    fmi3Boolean             source;
    fmi3Boolean             needs_update;
    fmi3Boolean             emitted;            /* source: its tick is done */
    fmi3Boolean             rx_active;
    fmi3Boolean             tx_active;
    fmi3Float64             rx_count;
    fmi3Float64             tx_count;
} model_t;

#define MODEL ((model_t *)instance)


const char *fmi3GetVersion(void) {
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
    (void)instanceName; (void)resourcePath; (void)visible; (void)loggingOn; (void)earlyReturnAllowed;
    (void)requiredIntermediateVariables; (void)nRequiredIntermediateVariables; (void)instanceEnvironment;
    (void)logMessage; (void)intermediateUpdate;

    model_t *model = calloc(1, sizeof(*model));
    if (model) {
        model->event_mode_used = eventModeUsed;
        model->source = strcmp(instantiationToken, "{clock-relay-source}") == 0;
        model->needs_update = strcmp(instantiationToken, "{clock-relay-needs-update}") == 0;
    }
    return model;
}


void fmi3FreeInstance(fmi3Instance instance) {
    free(instance);
}


fmi3Status fmi3EnterInitializationMode(fmi3Instance instance, fmi3Boolean toleranceDefined, fmi3Float64 tolerance,
                                       fmi3Float64 startTime, fmi3Boolean stopTimeDefined, fmi3Float64 stopTime) {
    (void)toleranceDefined; (void)tolerance; (void)stopTimeDefined; (void)stopTime;

    MODEL->mode = MODE_INITIALIZATION;
    MODEL->time = startTime;
    return fmi3OK;
}


fmi3Status fmi3ExitInitializationMode(fmi3Instance instance) {
    MODEL->mode = MODEL->event_mode_used ? MODE_EVENT : MODE_STEP;
    return fmi3OK;
}


fmi3Status fmi3EnterEventMode(fmi3Instance instance) {
    MODEL->mode = MODE_EVENT;
    return fmi3OK;
}


fmi3Status fmi3EnterStepMode(fmi3Instance instance) {
    MODEL->mode = MODE_STEP;
    return fmi3OK;
}


fmi3Status fmi3Terminate(fmi3Instance instance) {
    (void)instance;
    return fmi3OK;
}


fmi3Status fmi3Reset(fmi3Instance instance) {
    (void)instance;
    return fmi3Error;
}


fmi3Status fmi3DoStep(fmi3Instance instance, fmi3Float64 currentCommunicationPoint, fmi3Float64 communicationStepSize,
                      fmi3Boolean noSetFMUStatePriorToCurrentPoint, fmi3Boolean *eventHandlingNeeded,
                      fmi3Boolean *terminateSimulation, fmi3Boolean *earlyReturn, fmi3Float64 *lastSuccessfulTime) {
    (void)noSetFMUStatePriorToCurrentPoint;

    if (MODEL->mode != MODE_STEP)
        return fmi3Error;
    MODEL->time = currentCommunicationPoint + communicationStepSize;
    *eventHandlingNeeded = fmi3False;
    if (MODEL->source && !MODEL->emitted && (MODEL->time >= SOURCE_TIME - 1e-9)) {
        MODEL->emitted = fmi3True;
        MODEL->tx_active = fmi3True;
        MODEL->tx_count += 1.0;
        *eventHandlingNeeded = fmi3True;
    }
    *terminateSimulation = fmi3False;
    *earlyReturn = fmi3False;
    *lastSuccessfulTime = MODEL->time;
    return fmi3OK;
}


fmi3Status fmi3UpdateDiscreteStates(fmi3Instance instance, fmi3Boolean *discreteStatesNeedUpdate,
                                    fmi3Boolean *terminateSimulation, fmi3Boolean *nominalsOfContinuousStatesChanged,
                                    fmi3Boolean *valuesOfContinuousStatesChanged, fmi3Boolean *nextEventTimeDefined,
                                    fmi3Float64 *nextEventTime) {
    if (MODEL->mode != MODE_EVENT)
        return fmi3Error;

    *discreteStatesNeedUpdate = fmi3False;
    if (MODEL->rx_active) {
        MODEL->rx_active = fmi3False;
        MODEL->rx_count += 1.0;
        if (!MODEL->source) {
            MODEL->tx_active = fmi3True;
            MODEL->tx_count += 1.0;
            *discreteStatesNeedUpdate = MODEL->needs_update;
        }
    }
    *terminateSimulation = fmi3False;
    *nominalsOfContinuousStatesChanged = fmi3False;
    *valuesOfContinuousStatesChanged = fmi3False;
    *nextEventTimeDefined = fmi3False;
    *nextEventTime = 0.0;
    return fmi3OK;
}


fmi3Status fmi3SetClock(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                        const fmi3Clock values[]) {
    if (MODEL->mode != MODE_EVENT)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        if (valueReferences[i] != VR_RX)
            return fmi3Error;
        if (values[i])
            MODEL->rx_active = fmi3True;
    }
    return fmi3OK;
}


/* An output clock is active until it is read. */
fmi3Status fmi3GetClock(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                        fmi3Clock values[]) {
    if (MODEL->mode != MODE_EVENT)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        if (valueReferences[i] != VR_TX)
            return fmi3Error;
        values[i] = MODEL->tx_active;
        MODEL->tx_active = fmi3False;
    }
    return fmi3OK;
}


fmi3Status fmi3GetIntervalDecimal(fmi3Instance instance, const fmi3ValueReference valueReferences[],
                                  size_t nValueReferences, fmi3Float64 intervals[],
                                  fmi3IntervalQualifier qualifiers[]) {
    (void)instance; (void)valueReferences; (void)nValueReferences; (void)intervals; (void)qualifiers;
    return fmi3Error;   /* Triggered clocks only. */
}


fmi3Status fmi3GetShiftDecimal(fmi3Instance instance, const fmi3ValueReference valueReferences[],
                               size_t nValueReferences, fmi3Float64 shifts[]) {
    (void)instance; (void)valueReferences; (void)nValueReferences; (void)shifts;
    return fmi3Error;
}


fmi3Status fmi3GetFloat64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                          fmi3Float64 values[], size_t nValues) {
    if (nValues != nValueReferences)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        if (valueReferences[i] == VR_RX_COUNT)
            values[i] = MODEL->rx_count;
        else if (valueReferences[i] == VR_TX_COUNT)
            values[i] = MODEL->tx_count;
        else if (valueReferences[i] == 0)
            values[i] = MODEL->time;
        else
            return fmi3Error;
    }
    return fmi3OK;
}
