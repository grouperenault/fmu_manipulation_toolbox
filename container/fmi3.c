#include <math.h>
#include <string.h>

#include "fmi3Functions.h"

#include "container.h"
#include "logger.h"

/*
 * FMI-3.0 implementation
 */

/*----------------------------------------------------------------------------
                               U T I L I T I E S
----------------------------------------------------------------------------*/

/* unimplemented fmi3 functions */
#define __NOT_IMPLEMENTED__ \
    logger(LOGGER_ERROR, "Function '%s' is not implemented", __func__); \
    return fmi3Error;


/*----------------------------------------------------------------------------
               F M I 3   F U N C T I O N S   ( G E N E R A L )
----------------------------------------------------------------------------*/

const char* fmi3GetVersion(void) {
    return fmi3Version;
}


fmi3Status fmi3SetDebugLogging(fmi3Instance instance,
                              fmi3Boolean loggingOn,
                              size_t nCategories,
                              const fmi3String categories[]) {

    logger_set_debug(loggingOn);

    return fmi3OK;
}

fmi3Instance fmi3InstantiateCoSimulation(
    fmi3String                     instanceName,
    fmi3String                     instantiationToken,
    fmi3String                     resourcePath,
    fmi3Boolean                    visible,
    fmi3Boolean                    loggingOn,
    fmi3Boolean                    eventModeUsed,
    fmi3Boolean                    earlyReturnAllowed,
    const fmi3ValueReference       requiredIntermediateVariables[],
    size_t                         nRequiredIntermediateVariables,
    fmi3InstanceEnvironment        instanceEnvironment,
    fmi3LogMessageCallback         logMessage,
    fmi3IntermediateUpdateCallback intermediateUpdate) {
    container_t* container;
    container = container_new(instanceName, instantiationToken);

    if (container) {
        logger_function_t container_logger;
        container_logger.logger_fmi3 = logMessage;
        logger_init(FMU_3, container_logger, instanceEnvironment, container->instance_name, loggingOn); 
        /* logger() is available starting this point ! */

        logger(LOGGER_DEBUG, "Container model loading...");
        if (strncmp(resourcePath, "file://", 7) == 0)
            resourcePath += 7;
#ifdef WIN32
        if (resourcePath[0] == '/')
            resourcePath += 1;
#endif

        if (container_configure(container, resourcePath)) {
            logger(LOGGER_ERROR, "Cannot read container configuration.");
            container_free(container);
            return NULL;
        }
        logger(LOGGER_DEBUG, "Container configuration read.");
    }
    return container;
}


void fmi3FreeInstance(fmi3Instance instance) {
    container_t* container = (container_t*)instance;
    
    if (container)
        container_free(container);

    return;
}

fmi3Status fmi3EnterInitializationMode(fmi3Instance instance,
                                       fmi3Boolean toleranceDefined,
                                       fmi3Float64 tolerance,
                                       fmi3Float64 startTime,
                                       fmi3Boolean stopTimeDefined,
                                       fmi3Float64 stopTime) {
    container_t* container = (container_t*)instance;

    container->tolerance_defined = toleranceDefined;
    container->tolerance = tolerance;
    container->start_time = startTime;
    container->stop_time_defined = 0; /* stopTime can cause rounding issues. Disbale it.*/
    container->stop_time = stopTime;

    for(int i=0; i < container->nb_fmu; i += 1) {        
        if (fmuSetupExperiment(&container->fmu[i]) != FMU_STATUS_OK)
            return fmi3Error;
    }

    container_set_start_values(container, 1);
    logger(LOGGER_DEBUG, "fmuSetupExperiment -- OK");
    

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (fmuEnterInitializationMode(&container->fmu[i]) != FMU_STATUS_OK)
            return fmi3Error;
    }

    container_set_start_values(container, 0);

    return fmi3OK;
}


fmi3Status fmi3ExitInitializationMode(fmi3Instance instance){
    container_t* container = (container_t*)instance;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        if (fmuExitInitializationMode(&container->fmu[i]) != FMU_STATUS_OK)
            return fmi3Error;
    }
    
    container_init_values(container);

    if (container_update_discrete_state(container) != FMU_STATUS_OK)
        return fmi3Error;

    if (container_enter_step_mode(container) != FMU_STATUS_OK)
        return fmi3Error;

    return fmi3OK;
}


fmi3Status fmi3EnterEventMode(fmi3Instance instance) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3Terminate(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_status_t status = fmuTerminate(&container->fmu[i]);

        if (status != FMU_STATUS_OK)
            return fmi3Error;
    }
 
    return fmi3OK;
}


fmi3Status fmi3Reset(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_status_t status = fmuReset(&container->fmu[i]);

        if (status != FMU_STATUS_OK)
            return fmi3Error;
    }
 
    return fmi3OK;
}

/* Getting and setting variable values */
#define FMI_GETTER(type, fmi_type, fmu_type) \
fmi3Status fmi3Get ## fmi_type (fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3 ## fmi_type value[], size_t nValues) { \
    container_t* container = (container_t*)instance; \
    fmu_status_t status; \
\
    for (size_t i = 0; i < nValueReferences; i += 1) { \
        const uint32_t vr = valueReferences[i] & 0xFFFFFF; \
        const container_port_t *port = &container->port_ ##type [vr]; \
        const int fmu_id = port->links[0].fmu_id; \
\
        if (fmu_id < 0) { \
            value[i] = container-> type [vr]; \
        } else { \
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr; \
            const fmu_t *fmu = &container->fmu[fmu_id]; \
\
            status = fmuGet ## fmu_type (fmu, &fmu_vr, 1, &value[i]); \
            if (status != FMU_STATUS_OK) \
                return fmi3Error; \
        } \
    } \
\
    return fmi3OK; \
}


FMI_GETTER(reals64, Float64, Real64);
FMI_GETTER(reals32, Float32, Real32);
FMI_GETTER(integers8, Int8, Integer8);
FMI_GETTER(uintegers8, UInt8, UInteger8);
FMI_GETTER(integers16, Int16, Integer16);
FMI_GETTER(uintegers16, UInt16, UInteger16);
FMI_GETTER(integers32, Int32, Integer32);
FMI_GETTER(uintegers32, UInt32, UInteger32);
FMI_GETTER(integers64, Int64, Integer64);
FMI_GETTER(uintegers64, UInt64, UInteger64);
FMI_GETTER(booleans1, Boolean, Boolean1);
FMI_GETTER(strings, String, String);


fmi3Status fmi3GetBinary(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         size_t valueSizes[],
                         fmi3Binary values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;
    fmu_status_t status;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const uint32_t vr = valueReferences[i] & 0xFFFFFF;
        const container_port_t *port = &container->port_binaries[vr];
        const int fmu_id = port->links[0].fmu_id;

        if (fmu_id < 0) {
            values[i] = container->binaries[vr].data;
            valueSizes[i] = container->binaries[vr].size;
        } else {
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr;
            const fmu_t *fmu = &container->fmu[fmu_id];
            
            status = fmuGetBinary(fmu, &fmu_vr, 1, &valueSizes[i], &values[i]);

            if (status != FMU_STATUS_OK)
                return fmi3Error;
        }
    }

    return fmi3OK;
}


fmi3Status fmi3GetClock(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        fmi3Clock values[]) {
    container_t* container = (container_t*)instance;
    fmu_status_t status;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const uint32_t vr = valueReferences[i] & 0xFFFFFF;
        const container_port_t *port = &container->port_clocks[vr];
        const int fmu_id = port->links[0].fmu_id;

        if (fmu_id < 0) {
            values[i] = container->clocks[vr];
        } else {
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr;
            const fmu_t *fmu = &container->fmu[fmu_id];

            status = fmuGetClock(fmu, &fmu_vr, 1, &values[i]);
            if (status != FMU_STATUS_OK)
                return fmi3Error;
        }
    }

    return fmi3OK;
}

#undef FMI_GETTER


#define FMI_SETTER(type, fmi_type, fmu_type) \
fmi3Status fmi3Set ## fmi_type (fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3 ## fmi_type value[], size_t nValues) { \
    container_t* container = (container_t*)instance; \
    fmu_status_t status; \
\
    for (size_t i = 0; i < nValueReferences; i += 1) { \
        const uint32_t vr = valueReferences[i] & 0xFFFFFF; \
        const container_port_t *port = &container->port_ ##type [vr]; \
        const int fmu_id = port->links[0].fmu_id; \
\
        if (fmu_id < 0) { \
            container-> type [vr] = value[i]; \
        } else { \
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr; \
            const fmu_t *fmu = &container->fmu[fmu_id]; \
\
            status = fmuSet ## fmu_type (fmu, &fmu_vr, 1, &value[i]); \
            if (status != FMU_STATUS_OK) \
                return fmi3Error; \
        } \
    } \
\
    return fmi3OK; \
}
FMI_SETTER(reals64, Float64, Real64);
FMI_SETTER(reals32, Float32, Real32);
FMI_SETTER(integers8, Int8, Integer8);
FMI_SETTER(uintegers8, UInt8, UInteger8);
FMI_SETTER(integers16, Int16, Integer16);
FMI_SETTER(uintegers16, UInt16, UInteger16);
FMI_SETTER(integers32, Int32, Integer32);
FMI_SETTER(uintegers32, UInt32, UInteger32);
FMI_SETTER(integers64, Int64, Integer64);
FMI_SETTER(uintegers64, UInt64, UInteger64);
FMI_SETTER(booleans1, Boolean, Boolean1);

fmi3Status fmi3SetString(fmi3Instance instance, const fmi2ValueReference vr[], size_t nvr, const fmi2String value[], size_t nValues) {
    container_t* container = (container_t*)instance;
    fmu_status_t status;

    for (size_t i = 0; i < nvr; i += 1) {
        const uint32_t local_vr = vr[i] & 0xFFFFFF;
        const container_port_t* port = &container->port_strings[local_vr];
        for (int j = 0; j < port->nb; j += 1) {
            const int fmu_id = port->links[j].fmu_id;

            if (fmu_id < 0) {
                free(container->strings[local_vr]);
                container->strings[local_vr] = strdup(value[i]);
            }
            else {
                const fmu_t* fmu = &container->fmu[fmu_id];
                const fmi2ValueReference fmu_vr = port->links[j].fmu_vr;

                status = fmuSetString(fmu, &fmu_vr, 1, &value[i]);
                if (status != FMU_STATUS_OK)
                    return fmi3Error;
            }
        }
    }
    return fmi3OK;
}


fmi3Status fmi3SetBinary(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         const size_t valueSizes[],
                         const fmi3Binary values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;
    fmu_status_t status;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const uint32_t vr = valueReferences[i] & 0xFFFFFF;
        const container_port_t *port = &container->port_binaries[vr];
        const int fmu_id = port->links[0].fmu_id;

        if (fmu_id < 0) {
            if (container->binaries[vr].max_size < valueSizes[i]) {
                container->binaries[vr].data = realloc(container->binaries[vr].data, valueSizes[i]);
                if (! container->binaries[vr].data) {
                    logger(LOGGER_ERROR, "Cannot allocate memory for SetBinary");
                    return fmi3Error;
                }
                container->binaries[vr].max_size = valueSizes[i];
            }

            memcpy(container->binaries[vr].data, values[i], valueSizes[i]);
        } else {
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr;
            const fmu_t *fmu = &container->fmu[fmu_id];
            
            status = fmuSetBinary(fmu, &fmu_vr, 1, &valueSizes[i], &values[i]);

            if (status != FMU_STATUS_OK)
                return fmi3Error;
        }
    }

    return fmi3OK;
}


fmi3Status fmi3SetClock(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        const fmi3Clock values[]) {
    container_t* container = (container_t*)instance;
    fmu_status_t status;

    for (size_t i = 0; i < nValueReferences; i += 1) {
        const uint32_t vr = valueReferences[i] & 0xFFFFFF;
        const container_port_t *port = &container->port_clocks[vr];
        const int fmu_id = port->links[0].fmu_id;

        if (fmu_id < 0) {
            container->clocks[vr] = values[i];
        } else {
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr;
            const fmu_t *fmu = &container->fmu[fmu_id];

            status = fmuSetClock(fmu, &fmu_vr, 1, &values[i]);
            if (status != FMU_STATUS_OK)
                return fmi3Error;
        }
    }

    return fmi3OK;
}

#undef FMI_SETTER


fmi3Status fmi3GetNumberOfVariableDependencies(fmi3Instance instance,
                                               fmi3ValueReference valueReference,
                                               size_t* nDependencies) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetVariableDependencies(fmi3Instance instance,
                                       fmi3ValueReference dependent,
                                       size_t elementIndicesOfDependent[],
                                       fmi3ValueReference independents[],
                                       size_t elementIndicesOfIndependents[],
                                       fmi3DependencyKind dependencyKinds[],
                                       size_t nDependencies) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetFMUState(fmi3Instance instance, fmi3FMUState* FMUState) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetFMUState(fmi3Instance instance, fmi3FMUState  FMUState) {
    __NOT_IMPLEMENTED__
}

fmi3Status fmi3FreeFMUState(fmi3Instance instance, fmi3FMUState* FMUState) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SerializedFMUStateSize(fmi3Instance instance,
                                      fmi3FMUState FMUState,
                                      size_t* size) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SerializeFMUState(fmi3Instance instance,
                                 fmi3FMUState FMUState,
                                 fmi3Byte serializedState[],
                                 size_t size) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3DeserializeFMUState(fmi3Instance instance,
                                   const fmi3Byte serializedState[],
                                   size_t size,
                                   fmi3FMUState* FMUState) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetDirectionalDerivative(fmi3Instance instance,
                                        const fmi3ValueReference unknowns[],
                                        size_t nUnknowns,
                                        const fmi3ValueReference knowns[],
                                        size_t nKnowns,
                                        const fmi3Float64 seed[],
                                        size_t nSeed,
                                        fmi3Float64 sensitivity[],
                                        size_t nSensitivity) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetAdjointDerivative(fmi3Instance instance,
                                    const fmi3ValueReference unknowns[],
                                    size_t nUnknowns,
                                    const fmi3ValueReference knowns[],
                                    size_t nKnowns,
                                    const fmi3Float64 seed[],
                                    size_t nSeed,
                                    fmi3Float64 sensitivity[],
                                    size_t nSensitivity) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3EnterConfigurationMode(fmi3Instance instance) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3ExitConfigurationMode(fmi3Instance instance) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetIntervalDecimal(fmi3Instance instance,
                                  const fmi3ValueReference valueReferences[],
                                  size_t nValueReferences,
                                  fmi3Float64 intervals[],
                                  fmi3IntervalQualifier qualifiers[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetIntervalFraction(fmi3Instance instance,
                                   const fmi3ValueReference valueReferences[],
                                   size_t nValueReferences,
                                   fmi3UInt64 counters[],
                                   fmi3UInt64 resolutions[],
                                   fmi3IntervalQualifier qualifiers[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetShiftDecimal(fmi3Instance instance,
                               const fmi3ValueReference valueReferences[],
                               size_t nValueReferences,
                               fmi3Float64 shifts[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetShiftFraction(fmi3Instance instance,
                                const fmi3ValueReference valueReferences[],
                                size_t nValueReferences,
                                fmi3UInt64 counters[],
                                fmi3UInt64 resolutions[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetIntervalDecimal(fmi3Instance instance,
                                  const fmi3ValueReference valueReferences[],
                                  size_t nValueReferences,
                                  const fmi3Float64 intervals[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetIntervalFraction(fmi3Instance instance,
                                   const fmi3ValueReference valueReferences[],
                                   size_t nValueReferences,
                                   const fmi3UInt64 counters[],
                                   const fmi3UInt64 resolutions[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetShiftDecimal(fmi3Instance instance,
                               const fmi3ValueReference valueReferences[],
                               size_t nValueReferences,
                               const fmi3Float64 shifts[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetShiftFraction(fmi3Instance instance,
                                const fmi3ValueReference valueReferences[],
                                size_t nValueReferences,
                                const fmi3UInt64 counters[],
                                const fmi3UInt64 resolutions[]) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3EvaluateDiscreteStates(fmi3Instance instance) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3UpdateDiscreteStates(fmi3Instance instance,
                                    fmi3Boolean* discreteStatesNeedUpdate,
                                    fmi3Boolean* terminateSimulation,
                                    fmi3Boolean* nominalsOfContinuousStatesChanged,
                                    fmi3Boolean* valuesOfContinuousStatesChanged,
                                    fmi3Boolean* nextEventTimeDefined,
                                    fmi3Float64* nextEventTime) {
    
    /* Container has no discrete mode */
    *discreteStatesNeedUpdate = false;
    *terminateSimulation = false;
    *nominalsOfContinuousStatesChanged = false;
    *valuesOfContinuousStatesChanged = false;
    *nextEventTimeDefined = false;
    *nextEventTime = 0.0;

    return fmi3OK;
}

/*----------------------------------------------------------------------------
          F M I 3   F U N C T I O N S   ( C O S I M U L A T I O N )
----------------------------------------------------------------------------*/
 
fmi3Status fmi3EnterStepMode(fmi3Instance instance)  {
    return fmi3OK;
}


fmi3Status fmi3GetOutputDerivatives(fmi3Instance instance,
                                    const fmi3ValueReference valueReferences[],
                                    size_t nValueReferences,
                                    const fmi3Int32 orders[],
                                    fmi3Float64 values[],
                                    size_t nValues)  {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3DoStep(fmi3Instance instance,
                      fmi3Float64 currentCommunicationPoint,
                      fmi3Float64 communicationStepSize,
                      fmi3Boolean noSetFMUStatePriorToCurrentPoint,
                      fmi3Boolean* eventHandlingNeeded,
                      fmi3Boolean* terminateSimulation,
                      fmi3Boolean* earlyReturn,
                      fmi3Float64* lastSuccessfulTime) {
    container_t* container = (container_t*)instance;


    *earlyReturn = false;
    *eventHandlingNeeded = false;
    *terminateSimulation = false;

    if (container_do_step(container, currentCommunicationPoint, communicationStepSize) != FMU_STATUS_OK)
        return fmi3Error;

    *lastSuccessfulTime = container->reals64[0];

    return fmi3OK;
}


/*----------------------------------------------------------------------------
          F M I 3   F U N C T I O N S   ( M O D E L E X C H A N G E )
----------------------------------------------------------------------------*/

fmi3Instance fmi3InstantiateModelExchange(
    fmi3String                 instanceName,
    fmi3String                 instantiationToken,
    fmi3String                 resourcePath,
    fmi3Boolean                visible,
    fmi3Boolean                loggingOn,
    fmi3InstanceEnvironment    instanceEnvironment,
    fmi3LogMessageCallback     logMessage) {
        return NULL;
    }


fmi3Status fmi3EnterContinuousTimeMode(fmi3Instance instance) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3CompletedIntegratorStep(fmi3Instance instance,
                                       fmi3Boolean  noSetFMUStatePriorToCurrentPoint,
                                       fmi3Boolean* enterEventMode,
                                       fmi3Boolean* terminateSimulation) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetTime(fmi3Instance instance, fmi3Float64 time) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetContinuousStates(fmi3Instance instance,
                                   const fmi3Float64 continuousStates[],
                                   size_t nContinuousStates) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetContinuousStateDerivatives(fmi3Instance instance,
                                             fmi3Float64 derivatives[],
                                            size_t nContinuousStates) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetEventIndicators(fmi3Instance instance,
                                  fmi3Float64 eventIndicators[],
                                  size_t nEventIndicators) {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetContinuousStates(fmi3Instance instance,
                                   fmi3Float64 continuousStates[],
                                   size_t nContinuousStates)  {
    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetNominalsOfContinuousStates(fmi3Instance instance,
                                             fmi3Float64 nominals[],
                                             size_t nContinuousStates) {
    __NOT_IMPLEMENTED__
}



fmi3Status fmi3GetNumberOfEventIndicators(fmi3Instance instance,
                                          size_t* nEventIndicators)  {
    __NOT_IMPLEMENTED__
}



fmi3Status fmi3GetNumberOfContinuousStates(fmi3Instance instance,
                                           size_t* nContinuousStates) {
    __NOT_IMPLEMENTED__
}


/*----------------------------------------------------------------------------
    F M I 3   F U N C T I O N S   ( S C H E D U L E D   E X E C U T I O N )
----------------------------------------------------------------------------*/

fmi3Instance fmi3InstantiateScheduledExecution(
    fmi3String                     instanceName,
    fmi3String                     instantiationToken,
    fmi3String                     resourcePath,
    fmi3Boolean                    visible,
    fmi3Boolean                    loggingOn,
    fmi3InstanceEnvironment        instanceEnvironment,
    fmi3LogMessageCallback         logMessage,
    fmi3ClockUpdateCallback        clockUpdate,
    fmi3LockPreemptionCallback     lockPreemption,
    fmi3UnlockPreemptionCallback   unlockPreemption) {
    return NULL;
}

fmi3Status fmi3ActivateModelPartition(fmi3Instance instance,
                                      fmi3ValueReference clockReference,
                                      fmi3Float64 activationTime) {
    __NOT_IMPLEMENTED__
}
