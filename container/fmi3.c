#include <math.h>
#include <string.h>

#include "fmi3Functions.h"

#include "container.h"
#include "logger.h"

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
    container_t* container = (container_t*)instance;

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
        return NULL;
    }

void fmi3FreeInstance(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    return;
}

fmi3Status fmi3EnterInitializationMode(fmi3Instance instance,
                                                   fmi3Boolean toleranceDefined,
                                                   fmi3Float64 tolerance,
                                                   fmi3Float64 startTime,
                                                   fmi3Boolean stopTimeDefined,
                                                   fmi3Float64 stopTime) {
    __NOT_IMPLEMENTED__
}

fmi3Status fmi3ExitInitializationMode(fmi3Instance instance){
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3EnterEventMode(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3Terminate(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3Reset(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetFloat32(fmi3Instance instance,
                          const fmi3ValueReference valueReferences[],
                          size_t nValueReferences,
                          fmi3Float32 values[],
                           size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetFloat64(fmi3Instance instance,
                          const fmi3ValueReference valueReferences[],
                          size_t nValueReferences,
                        fmi3Float64 values[],
                          size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetInt8(fmi3Instance instance,
                       const fmi3ValueReference valueReferences[],
                       size_t nValueReferences,
                       fmi3Int8 values[],
                       size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetUInt8(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        fmi3UInt8 values[],
                        size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetInt16(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        fmi3Int16 values[],
                        size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetUInt16(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         fmi3UInt16 values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetInt32(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        fmi3Int32 values[],
                        size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetUInt32(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         fmi3UInt32 values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetInt64(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        fmi3Int64 values[],
                        size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetUInt64(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         fmi3UInt64 values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetBoolean(fmi3Instance instance,
                          const fmi3ValueReference valueReferences[],
                          size_t nValueReferences,
                          fmi3Boolean values[],
                          size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetString(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         fmi3String values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetBinary(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         size_t valueSizes[],
                         fmi3Binary values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetClock(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        fmi3Clock values[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetFloat32(fmi3Instance instance,
                          const fmi3ValueReference valueReferences[],
                          size_t nValueReferences,
                          const fmi3Float32 values[],
                          size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetFloat64(fmi3Instance instance,
                          const fmi3ValueReference valueReferences[],
                          size_t nValueReferences,
                          const fmi3Float64 values[],
                          size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetInt8(fmi3Instance instance,
                       const fmi3ValueReference valueReferences[],
                       size_t nValueReferences,
                       const fmi3Int8 values[],
                       size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetUInt8(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        const fmi3UInt8 values[],
                        size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetInt16(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        const fmi3Int16 values[],
                        size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetUInt16(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         const fmi3UInt16 values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetInt32(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        const fmi3Int32 values[],
                        size_t nValues)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetUInt32(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         const fmi3UInt32 values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetInt64(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        const fmi3Int64 values[],
                        size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetUInt64(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         const fmi3UInt64 values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetBoolean(fmi3Instance instance,
                          const fmi3ValueReference valueReferences[],
                          size_t nValueReferences,
                          const fmi3Boolean values[],
                          size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetString(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         const fmi3String values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetBinary(fmi3Instance instance,
                         const fmi3ValueReference valueReferences[],
                         size_t nValueReferences,
                         const size_t valueSizes[],
                         const fmi3Binary values[],
                         size_t nValues) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetClock(fmi3Instance instance,
                        const fmi3ValueReference valueReferences[],
                        size_t nValueReferences,
                        const fmi3Clock values[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetNumberOfVariableDependencies(fmi3Instance instance,
                                               fmi3ValueReference valueReference,
                                               size_t* nDependencies) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetVariableDependencies(fmi3Instance instance,
                                       fmi3ValueReference dependent,
                                       size_t elementIndicesOfDependent[],
                                       fmi3ValueReference independents[],
                                       size_t elementIndicesOfIndependents[],
                                       fmi3DependencyKind dependencyKinds[],
                                       size_t nDependencies) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetFMUState(fmi3Instance instance, fmi3FMUState* FMUState) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetFMUState(fmi3Instance instance, fmi3FMUState  FMUState) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}

fmi3Status fmi3FreeFMUState(fmi3Instance instance, fmi3FMUState* FMUState) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SerializedFMUStateSize(fmi3Instance instance,
                                      fmi3FMUState FMUState,
                                      size_t* size) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SerializeFMUState(fmi3Instance instance,
                                 fmi3FMUState FMUState,
                                 fmi3Byte serializedState[],
                                 size_t size) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3DeserializeFMUState(fmi3Instance instance,
                                   const fmi3Byte serializedState[],
                                   size_t size,
                                   fmi3FMUState* FMUState) {
    container_t* container = (container_t*)instance;

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
    container_t* container = (container_t*)instance;

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
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3EnterConfigurationMode(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3ExitConfigurationMode(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetIntervalDecimal(fmi3Instance instance,
                                  const fmi3ValueReference valueReferences[],
                                  size_t nValueReferences,
                                  fmi3Float64 intervals[],
                                  fmi3IntervalQualifier qualifiers[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetIntervalFraction(fmi3Instance instance,
                                   const fmi3ValueReference valueReferences[],
                                   size_t nValueReferences,
                                   fmi3UInt64 counters[],
                                   fmi3UInt64 resolutions[],
                                   fmi3IntervalQualifier qualifiers[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetShiftDecimal(fmi3Instance instance,
                               const fmi3ValueReference valueReferences[],
                               size_t nValueReferences,
                               fmi3Float64 shifts[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetShiftFraction(fmi3Instance instance,
                                const fmi3ValueReference valueReferences[],
                                size_t nValueReferences,
                                fmi3UInt64 counters[],
                                fmi3UInt64 resolutions[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetIntervalDecimal(fmi3Instance instance,
                                  const fmi3ValueReference valueReferences[],
                                  size_t nValueReferences,
                                  const fmi3Float64 intervals[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetIntervalFraction(fmi3Instance instance,
                                   const fmi3ValueReference valueReferences[],
                                   size_t nValueReferences,
                                   const fmi3UInt64 counters[],
                                   const fmi3UInt64 resolutions[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetShiftDecimal(fmi3Instance instance,
                               const fmi3ValueReference valueReferences[],
                               size_t nValueReferences,
                               const fmi3Float64 shifts[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3SetShiftFraction(fmi3Instance instance,
                                const fmi3ValueReference valueReferences[],
                                size_t nValueReferences,
                                const fmi3UInt64 counters[],
                                const fmi3UInt64 resolutions[]) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3EvaluateDiscreteStates(fmi3Instance instance) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3UpdateDiscreteStates(fmi3Instance instance,
                                    fmi3Boolean* discreteStatesNeedUpdate,
                                    fmi3Boolean* terminateSimulation,
                                    fmi3Boolean* nominalsOfContinuousStatesChanged,
                                    fmi3Boolean* valuesOfContinuousStatesChanged,
                                    fmi3Boolean* nextEventTimeDefined,
                                    fmi3Float64* nextEventTime) {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}

/*----------------------------------------------------------------------------
          F M I 3   F U N C T I O N S   ( C O S I M U L A T I O N )
----------------------------------------------------------------------------*/
 
fmi3Status fmi3EnterStepMode(fmi3Instance instance)  {
    container_t* container = (container_t*)instance;

    __NOT_IMPLEMENTED__
}


fmi3Status fmi3GetOutputDerivatives(fmi3Instance instance,
                                    const fmi3ValueReference valueReferences[],
                                    size_t nValueReferences,
                                    const fmi3Int32 orders[],
                                    fmi3Float64 values[],
                                    size_t nValues)  {
    container_t* container = (container_t*)instance;

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

    __NOT_IMPLEMENTED__
}
