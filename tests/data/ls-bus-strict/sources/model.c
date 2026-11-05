/*
 * FMU of the tests of the exchange of LS-BUS operations between FMUs of a container. Like the FMUs of SystemDesk, it evaluates
 * its discrete states when its Tx_Data is read, and refuses any input until fmi3UpdateDiscreteStates() closes the super-dense
 * time instant. It also refuses an Rx_Data without its active Rx_Clock. It has a terminal per type of Tx_Clock: constant,
 * countdown (a first tick at the start time) and triggered (a frame is pending when it leaves the initialization and after each
 * step), and it counts the frames that it sends and those that it receives.
 */
#include <stdlib.h>
#include <string.h>

#include "fmi3Functions.h"

#define NB_TERMINALS        3
#define VR_TX_CLOCK         1
#define VR_RX_CLOCK         11
#define VR_TX_DATA          21
#define VR_RX_DATA          31
#define VR_SENT             41
#define VR_RECEIVED         51
#define COUNTDOWN_INTERVAL  0.1

enum { CONSTANT, COUNTDOWN, TRIGGERED };
enum { MODE_INSTANTIATED, MODE_INITIALIZATION, MODE_EVENT, MODE_STEP };

static const fmi3Byte FRAME[] = { 0x10, 0, 0, 0, 16, 0, 0, 0, 20, 0, 0, 0, 0, 0, 2, 0 };

typedef struct {
    int                     mode;
    fmi3Boolean             event_mode_used;
    fmi3Boolean             evaluated;
    fmi3Boolean             tx_active[NB_TERMINALS];
    fmi3Boolean             rx_active[NB_TERMINALS];
    fmi3Float64             sent[NB_TERMINALS];
    fmi3Float64             received[NB_TERMINALS];
    fmi3Float64             countdown;
    fmi3IntervalQualifier   qualifier;
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


fmi3Instance fmi3InstantiateCoSimulation(fmi3String instanceName, fmi3String instantiationToken, fmi3String resourcePath,
                                         fmi3Boolean visible, fmi3Boolean loggingOn, fmi3Boolean eventModeUsed,
                                         fmi3Boolean earlyReturnAllowed, const fmi3ValueReference requiredIntermediateVariables[],
                                         size_t nRequiredIntermediateVariables, fmi3InstanceEnvironment instanceEnvironment,
                                         fmi3LogMessageCallback logMessage, fmi3IntermediateUpdateCallback intermediateUpdate) {
    (void)instanceName; (void)instantiationToken; (void)resourcePath; (void)visible; (void)loggingOn;
    (void)earlyReturnAllowed; (void)requiredIntermediateVariables; (void)nRequiredIntermediateVariables;
    (void)instanceEnvironment; (void)logMessage; (void)intermediateUpdate;

    model_t *model = calloc(1, sizeof(*model));
    if (model)
        model->event_mode_used = eventModeUsed;
    return model;
}


void fmi3FreeInstance(fmi3Instance instance) {
    free(instance);
}


fmi3Status fmi3EnterInitializationMode(fmi3Instance instance, fmi3Boolean toleranceDefined, fmi3Float64 tolerance,
                                       fmi3Float64 startTime, fmi3Boolean stopTimeDefined, fmi3Float64 stopTime) {
    (void)toleranceDefined; (void)tolerance; (void)startTime; (void)stopTimeDefined; (void)stopTime;

    MODEL->mode = MODE_INITIALIZATION;
    MODEL->countdown = 0.0;
    MODEL->qualifier = fmi3IntervalChanged;
    return fmi3OK;
}


fmi3Status fmi3ExitInitializationMode(fmi3Instance instance) {
    MODEL->mode = MODEL->event_mode_used ? MODE_EVENT : MODE_STEP;
    MODEL->tx_active[TRIGGERED] = fmi3True;
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
    const fmi3Boolean event_mode_used = MODEL->event_mode_used;
    model_t cleared = { 0 };
    *MODEL = cleared;
    MODEL->event_mode_used = event_mode_used;
    return fmi3OK;
}


fmi3Status fmi3DoStep(fmi3Instance instance, fmi3Float64 currentCommunicationPoint, fmi3Float64 communicationStepSize,
                      fmi3Boolean noSetFMUStatePriorToCurrentPoint, fmi3Boolean *eventHandlingNeeded,
                      fmi3Boolean *terminateSimulation, fmi3Boolean *earlyReturn, fmi3Float64 *lastSuccessfulTime) {
    (void)noSetFMUStatePriorToCurrentPoint;

    if (MODEL->mode != MODE_STEP)
        return fmi3Error;
    MODEL->tx_active[TRIGGERED] = fmi3True;
    *eventHandlingNeeded = fmi3True;
    *terminateSimulation = fmi3False;
    *earlyReturn = fmi3False;
    *lastSuccessfulTime = currentCommunicationPoint + communicationStepSize;
    return fmi3OK;
}


fmi3Status fmi3UpdateDiscreteStates(fmi3Instance instance, fmi3Boolean *discreteStatesNeedUpdate,
                                    fmi3Boolean *terminateSimulation, fmi3Boolean *nominalsOfContinuousStatesChanged,
                                    fmi3Boolean *valuesOfContinuousStatesChanged, fmi3Boolean *nextEventTimeDefined,
                                    fmi3Float64 *nextEventTime) {
    if (MODEL->mode != MODE_EVENT)
        return fmi3Error;

    if (MODEL->tx_active[COUNTDOWN]) {
        MODEL->countdown = COUNTDOWN_INTERVAL;
        MODEL->qualifier = fmi3IntervalChanged;
    }
    for (int i = 0; i < NB_TERMINALS; i += 1) {
        MODEL->tx_active[i] = fmi3False;
        MODEL->rx_active[i] = fmi3False;
    }
    MODEL->evaluated = fmi3False;

    *discreteStatesNeedUpdate = fmi3False;
    *terminateSimulation = fmi3False;
    *nominalsOfContinuousStatesChanged = fmi3False;
    *valuesOfContinuousStatesChanged = fmi3False;
    *nextEventTimeDefined = fmi3False;
    *nextEventTime = 0.0;
    return fmi3OK;
}


fmi3Status fmi3SetClock(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                        const fmi3Clock values[]) {
    if ((MODEL->mode != MODE_EVENT) || MODEL->evaluated)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const fmi3ValueReference vr = valueReferences[i];

        if ((vr >= VR_TX_CLOCK) && (vr < VR_TX_CLOCK + TRIGGERED))
            MODEL->tx_active[vr - VR_TX_CLOCK] = values[i];
        else if ((vr >= VR_RX_CLOCK) && (vr < VR_RX_CLOCK + NB_TERMINALS))
            MODEL->rx_active[vr - VR_RX_CLOCK] = values[i];
        else
            return fmi3Error;
    }
    return fmi3OK;
}


fmi3Status fmi3GetClock(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                        fmi3Clock values[]) {
    for (size_t i = 0; i < nValueReferences; i += 1) {
        if (valueReferences[i] != VR_TX_CLOCK + TRIGGERED)
            return fmi3Error;
        values[i] = MODEL->tx_active[TRIGGERED];
    }
    return fmi3OK;
}


fmi3Status fmi3GetIntervalDecimal(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                                  fmi3Float64 intervals[], fmi3IntervalQualifier qualifiers[]) {
    for (size_t i = 0; i < nValueReferences; i += 1) {
        if (valueReferences[i] != VR_TX_CLOCK + COUNTDOWN)
            return fmi3Error;   /* The constant clock has its interval in the modelDescription.xml. */
        intervals[i] = MODEL->countdown;
        qualifiers[i] = MODEL->qualifier;
        MODEL->qualifier = fmi3IntervalNotYetKnown;
    }
    return fmi3OK;
}


fmi3Status fmi3GetBinary(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                         size_t valueSizes[], fmi3Binary values[], size_t nValues) {
    if (nValues != nValueReferences)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const fmi3ValueReference vr = valueReferences[i];

        if ((vr < VR_TX_DATA) || (vr >= VR_TX_DATA + NB_TERMINALS))
            return fmi3Error;
        MODEL->evaluated = fmi3True;
        if (MODEL->tx_active[vr - VR_TX_DATA]) {
            MODEL->sent[vr - VR_TX_DATA] += 1.0;
            valueSizes[i] = sizeof(FRAME);
            values[i] = FRAME;
        } else {
            valueSizes[i] = 0;
            values[i] = FRAME;
        }
    }
    return fmi3OK;
}


fmi3Status fmi3SetBinary(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                         const size_t valueSizes[], const fmi3Binary values[], size_t nValues) {
    if ((nValues != nValueReferences) || MODEL->evaluated)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const fmi3ValueReference vr = valueReferences[i];

        if ((vr < VR_RX_DATA) || (vr >= VR_RX_DATA + NB_TERMINALS) || !MODEL->rx_active[vr - VR_RX_DATA])
            return fmi3Error;
        if ((valueSizes[i] != sizeof(FRAME)) || memcmp(values[i], FRAME, sizeof(FRAME)))
            return fmi3Error;
        MODEL->received[vr - VR_RX_DATA] += 1.0;
    }
    return fmi3OK;
}


fmi3Status fmi3GetFloat64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                          fmi3Float64 values[], size_t nValues) {
    if (nValues != nValueReferences)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const fmi3ValueReference vr = valueReferences[i];

        if ((vr >= VR_SENT) && (vr < VR_SENT + NB_TERMINALS))
            values[i] = MODEL->sent[vr - VR_SENT];
        else if ((vr >= VR_RECEIVED) && (vr < VR_RECEIVED + NB_TERMINALS))
            values[i] = MODEL->received[vr - VR_RECEIVED];
        else
            return fmi3Error;
    }
    return fmi3OK;
}
