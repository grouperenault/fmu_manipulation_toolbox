/*
 * FMU of the tests of the clocks scheduled by a container. It has an input clock for each intervalVariability of
 * FMI-3.0 and as many triggered input clocks, and it counts their ticks and sums their times. It refuses what FMI-3.0
 * forbids to an importer: reading an interval or a shift that the modelDescription.xml declares or that is not
 * available at this time, and activating a clock outside of the Event Mode.
 */
#include <stdlib.h>

#include "fmi3Functions.h"

#define NB_CLOCKS           10
#define VR_CLOCK            1   /* constant, fixed, tunable, changing, countdown, repeated, forgetful, silent,
                                   unwritten, invalid */
#define VR_RX_CLOCK         11
#define VR_COUNT            21
#define VR_SUM              31
#define VR_RX_COUNT         41
#define VR_RX_SUM           51

enum { CONSTANT, FIXED, TUNABLE, CHANGING, COUNTDOWN, REPEATED, FORGETFUL, SILENT, UNWRITTEN, INVALID };
enum { MODE_INSTANTIATED, MODE_INITIALIZATION, MODE_EVENT, MODE_STEP };

typedef struct {
    int                     mode;
    fmi3Float64             time;
    fmi3Boolean             event_mode_used;
    fmi3Float64             interval[NB_CLOCKS];
    fmi3IntervalQualifier   qualifier[NB_CLOCKS];
    fmi3Boolean             active[2 * NB_CLOCKS];
    fmi3Float64             count[2 * NB_CLOCKS];
    fmi3Float64             sum[2 * NB_CLOCKS];
    fmi3Boolean             tuned;
    fmi3Boolean             countdown_started;
    fmi3Float64             repeated_at;
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
    (void)toleranceDefined; (void)tolerance; (void)stopTimeDefined; (void)stopTime;

    MODEL->mode = MODE_INITIALIZATION;
    MODEL->time = startTime;
    MODEL->interval[FIXED] = 0.25;
    MODEL->interval[TUNABLE] = 0.2;
    MODEL->interval[CHANGING] = 0.1;
    MODEL->qualifier[FIXED] = fmi3IntervalChanged;
    MODEL->qualifier[TUNABLE] = fmi3IntervalChanged;
    MODEL->qualifier[CHANGING] = fmi3IntervalChanged;
    MODEL->qualifier[COUNTDOWN] = fmi3IntervalNotYetKnown;
    MODEL->interval[REPEATED] = 0.25;
    MODEL->qualifier[REPEATED] = fmi3IntervalChanged;
    MODEL->interval[FORGETFUL] = 0.25;
    MODEL->qualifier[FORGETFUL] = fmi3IntervalChanged;
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
    MODEL->time = currentCommunicationPoint + communicationStepSize;
    *eventHandlingNeeded = fmi3False;
    *terminateSimulation = fmi3False;
    *earlyReturn = fmi3False;
    *lastSuccessfulTime = MODEL->time;
    return fmi3OK;
}


static void set_interval(fmi3Instance instance, int clock, fmi3Float64 interval) {
    MODEL->interval[clock] = interval;
    MODEL->qualifier[clock] = fmi3IntervalChanged;
}


fmi3Status fmi3UpdateDiscreteStates(fmi3Instance instance, fmi3Boolean *discreteStatesNeedUpdate,
                                    fmi3Boolean *terminateSimulation, fmi3Boolean *nominalsOfContinuousStatesChanged,
                                    fmi3Boolean *valuesOfContinuousStatesChanged, fmi3Boolean *nextEventTimeDefined,
                                    fmi3Float64 *nextEventTime) {
    if (MODEL->mode != MODE_EVENT)
        return fmi3Error;

    for (int i = 0; i < 2 * NB_CLOCKS; i += 1) {
        if (MODEL->active[i]) {
            MODEL->active[i] = fmi3False;
            MODEL->count[i] += 1.0;
            MODEL->sum[i] += MODEL->time;
            if (i == CHANGING)
                set_interval(instance, CHANGING, MODEL->interval[CHANGING] + 0.1);
            else if (i == COUNTDOWN)
                set_interval(instance, COUNTDOWN, 0.35);
            else if (i == REPEATED) {
                /* Once more right now, until a step has gone by: ticking it again without a step would never end. */
                if (MODEL->count[i] == 1.0)
                    MODEL->repeated_at = MODEL->time;
                if (MODEL->time == MODEL->repeated_at)
                    set_interval(instance, REPEATED, 0.0);
                else
                    MODEL->qualifier[REPEATED] = fmi3IntervalNotYetKnown;
            }
        }
    }

    /* The interval of the tunable clock changes between two of its ticks, relatively to the current time. */
    if (!MODEL->tuned && (MODEL->time >= 1.0 - 1e-9)) {
        MODEL->tuned = fmi3True;
        set_interval(instance, TUNABLE, 0.4);
    }

    /* The first tick of the countdown clock is not known until t=0.5. */
    if (!MODEL->countdown_started && (MODEL->time >= 0.5 - 1e-9)) {
        MODEL->countdown_started = fmi3True;
        set_interval(instance, COUNTDOWN, 0.15);
    }

    *discreteStatesNeedUpdate = fmi3False;
    *terminateSimulation = fmi3False;
    *nominalsOfContinuousStatesChanged = fmi3False;
    *valuesOfContinuousStatesChanged = fmi3False;
    *nextEventTimeDefined = fmi3False;
    *nextEventTime = 0.0;
    return fmi3OK;
}


static int clock_index(fmi3ValueReference vr) {
    if ((vr >= VR_CLOCK) && (vr < VR_CLOCK + NB_CLOCKS))
        return (int)(vr - VR_CLOCK);
    if ((vr >= VR_RX_CLOCK) && (vr < VR_RX_CLOCK + NB_CLOCKS))
        return (int)(vr - VR_RX_CLOCK) + NB_CLOCKS;
    return -1;
}


fmi3Status fmi3SetClock(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                        const fmi3Clock values[]) {
    if (MODEL->mode != MODE_EVENT)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const int index = clock_index(valueReferences[i]);
        if (index < 0)
            return fmi3Error;
        if (values[i])
            MODEL->active[index] = fmi3True;
    }
    return fmi3OK;
}


fmi3Status fmi3GetClock(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                        fmi3Clock values[]) {
    (void)instance; (void)valueReferences;

    for (size_t i = 0; i < nValueReferences; i += 1)
        values[i] = fmi3ClockInactive;
    return fmi3OK;
}


fmi3Status fmi3GetIntervalDecimal(fmi3Instance instance, const fmi3ValueReference valueReferences[],
                                  size_t nValueReferences, fmi3Float64 intervals[],
                                  fmi3IntervalQualifier qualifiers[]) {
    for (size_t i = 0; i < nValueReferences; i += 1) {
        const int clock = (int)valueReferences[i] - VR_CLOCK;

        if ((clock < 0) || (clock >= NB_CLOCKS) || (clock == CONSTANT))
            return fmi3Error;   /* Its interval is in the modelDescription.xml. */
        if ((clock == FIXED) && (MODEL->mode != MODE_INITIALIZATION))
            return fmi3Error;
        if ((clock == CHANGING) && (MODEL->mode != MODE_INITIALIZATION) &&
            (MODEL->qualifier[CHANGING] != fmi3IntervalChanged))
            return fmi3Error;   /* Only if it has just ticked. */

        /* Answers that FMI 3.0 does not allow. */
        if (clock == SILENT)
            continue;           /* neither an interval nor a qualifier */
        if (clock == UNWRITTEN) {
            qualifiers[i] = fmi3IntervalChanged;
            continue;           /* a new interval, without its value */
        }
        if (clock == INVALID) {
            intervals[i] = 0.25;
            qualifiers[i] = (fmi3IntervalQualifier)99;
            continue;
        }

        intervals[i] = MODEL->interval[clock];
        qualifiers[i] = MODEL->qualifier[clock];
        if (MODEL->qualifier[clock] == fmi3IntervalChanged)
            /* Not allowed for FORGETFUL, which has announced a tick: the demos of fmi-ls-bus-examples did it. */
            MODEL->qualifier[clock] = (clock == FORGETFUL) ? fmi3IntervalNotYetKnown : fmi3IntervalUnchanged;
    }
    return fmi3OK;
}


fmi3Status fmi3GetShiftDecimal(fmi3Instance instance, const fmi3ValueReference valueReferences[],
                               size_t nValueReferences, fmi3Float64 shifts[]) {
    if (MODEL->mode != MODE_INITIALIZATION)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const int clock = (int)valueReferences[i] - VR_CLOCK;

        if (clock == FIXED)
            shifts[i] = 0.05;
        else if (clock == TUNABLE)
            shifts[i] = 0.0;
        else
            return fmi3Error;   /* In the modelDescription.xml, or an aperiodic clock. */
    }
    return fmi3OK;
}


fmi3Status fmi3GetFloat64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences,
                          fmi3Float64 values[], size_t nValues) {
    if (nValues != nValueReferences)
        return fmi3Error;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const fmi3ValueReference vr = valueReferences[i];

        if ((vr >= VR_COUNT) && (vr < VR_COUNT + NB_CLOCKS))
            values[i] = MODEL->count[vr - VR_COUNT];
        else if ((vr >= VR_SUM) && (vr < VR_SUM + NB_CLOCKS))
            values[i] = MODEL->sum[vr - VR_SUM];
        else if ((vr >= VR_RX_COUNT) && (vr < VR_RX_COUNT + NB_CLOCKS))
            values[i] = MODEL->count[vr - VR_RX_COUNT + NB_CLOCKS];
        else if ((vr >= VR_RX_SUM) && (vr < VR_RX_SUM + NB_CLOCKS))
            values[i] = MODEL->sum[vr - VR_RX_SUM + NB_CLOCKS];
        else
            return fmi3Error;
    }
    return fmi3OK;
}
