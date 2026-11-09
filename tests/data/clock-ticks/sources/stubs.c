/* Functions of FMI 3.0 that ClockTicks does not need: they all fail. */
#include "fmi3Functions.h"

fmi3Instance fmi3InstantiateModelExchange(fmi3String instanceName, fmi3String instantiationToken, fmi3String resourcePath, fmi3Boolean visible, fmi3Boolean loggingOn, fmi3InstanceEnvironment instanceEnvironment, fmi3LogMessageCallback logMessage) {
    return NULL;
}

fmi3Instance fmi3InstantiateScheduledExecution(fmi3String instanceName, fmi3String instantiationToken, fmi3String resourcePath, fmi3Boolean visible, fmi3Boolean loggingOn, fmi3InstanceEnvironment instanceEnvironment, fmi3LogMessageCallback logMessage, fmi3ClockUpdateCallback clockUpdate, fmi3LockPreemptionCallback lockPreemption, fmi3UnlockPreemptionCallback unlockPreemption) {
    return NULL;
}

fmi3Status fmi3GetFloat32(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3Float32 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetInt8(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3Int8 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetUInt8(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3UInt8 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetInt16(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3Int16 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetUInt16(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3UInt16 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetInt32(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3Int32 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetUInt32(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3UInt32 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetInt64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3Int64 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetUInt64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3UInt64 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetBoolean(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3Boolean values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetString(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3String values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetBinary(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, size_t valueSizes[], fmi3Binary values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetFloat32(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Float32 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetFloat64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Float64 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetInt8(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Int8 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetUInt8(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3UInt8 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetInt16(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Int16 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetUInt16(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3UInt16 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetInt32(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Int32 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetUInt32(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3UInt32 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetInt64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Int64 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetUInt64(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3UInt64 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetBoolean(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Boolean values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetString(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3String values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3SetBinary(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const size_t valueSizes[], const fmi3Binary values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3GetNumberOfVariableDependencies(fmi3Instance instance, fmi3ValueReference valueReference, size_t* nDependencies) {
    return fmi3Error;
}

fmi3Status fmi3GetVariableDependencies(fmi3Instance instance, fmi3ValueReference dependent, size_t elementIndicesOfDependent[], fmi3ValueReference independents[], size_t elementIndicesOfIndependents[], fmi3DependencyKind dependencyKinds[], size_t nDependencies) {
    return fmi3Error;
}

fmi3Status fmi3GetFMUState(fmi3Instance instance, fmi3FMUState* FMUState) {
    return fmi3Error;
}

fmi3Status fmi3SetFMUState(fmi3Instance instance, fmi3FMUState FMUState) {
    return fmi3Error;
}

fmi3Status fmi3FreeFMUState(fmi3Instance instance, fmi3FMUState* FMUState) {
    return fmi3Error;
}

fmi3Status fmi3SerializedFMUStateSize(fmi3Instance instance, fmi3FMUState FMUState, size_t* size) {
    return fmi3Error;
}

fmi3Status fmi3SerializeFMUState(fmi3Instance instance, fmi3FMUState FMUState, fmi3Byte serializedState[], size_t size) {
    return fmi3Error;
}

fmi3Status fmi3DeserializeFMUState(fmi3Instance instance, const fmi3Byte serializedState[], size_t size, fmi3FMUState* FMUState) {
    return fmi3Error;
}

fmi3Status fmi3GetDirectionalDerivative(fmi3Instance instance, const fmi3ValueReference unknowns[], size_t nUnknowns, const fmi3ValueReference knowns[], size_t nKnowns, const fmi3Float64 seed[], size_t nSeed, fmi3Float64 sensitivity[], size_t nSensitivity) {
    return fmi3Error;
}

fmi3Status fmi3GetAdjointDerivative(fmi3Instance instance, const fmi3ValueReference unknowns[], size_t nUnknowns, const fmi3ValueReference knowns[], size_t nKnowns, const fmi3Float64 seed[], size_t nSeed, fmi3Float64 sensitivity[], size_t nSensitivity) {
    return fmi3Error;
}

fmi3Status fmi3EnterConfigurationMode(fmi3Instance instance) {
    return fmi3Error;
}

fmi3Status fmi3ExitConfigurationMode(fmi3Instance instance) {
    return fmi3Error;
}

fmi3Status fmi3GetIntervalFraction(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3UInt64 counters[], fmi3UInt64 resolutions[], fmi3IntervalQualifier qualifiers[]) {
    return fmi3Error;
}

fmi3Status fmi3GetShiftFraction(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, fmi3UInt64 counters[], fmi3UInt64 resolutions[]) {
    return fmi3Error;
}

fmi3Status fmi3SetIntervalDecimal(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Float64 intervals[]) {
    return fmi3Error;
}

fmi3Status fmi3SetIntervalFraction(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3UInt64 counters[], const fmi3UInt64 resolutions[]) {
    return fmi3Error;
}

fmi3Status fmi3SetShiftDecimal(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Float64 shifts[]) {
    return fmi3Error;
}

fmi3Status fmi3SetShiftFraction(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3UInt64 counters[], const fmi3UInt64 resolutions[]) {
    return fmi3Error;
}

fmi3Status fmi3EvaluateDiscreteStates(fmi3Instance instance) {
    return fmi3Error;
}

fmi3Status fmi3EnterContinuousTimeMode(fmi3Instance instance) {
    return fmi3Error;
}

fmi3Status fmi3CompletedIntegratorStep(fmi3Instance instance, fmi3Boolean noSetFMUStatePriorToCurrentPoint, fmi3Boolean* enterEventMode, fmi3Boolean* terminateSimulation) {
    return fmi3Error;
}

fmi3Status fmi3SetTime(fmi3Instance instance, fmi3Float64 time) {
    return fmi3Error;
}

fmi3Status fmi3SetContinuousStates(fmi3Instance instance, const fmi3Float64 continuousStates[], size_t nContinuousStates) {
    return fmi3Error;
}

fmi3Status fmi3GetContinuousStateDerivatives(fmi3Instance instance, fmi3Float64 derivatives[], size_t nContinuousStates) {
    return fmi3Error;
}

fmi3Status fmi3GetEventIndicators(fmi3Instance instance, fmi3Float64 eventIndicators[], size_t nEventIndicators) {
    return fmi3Error;
}

fmi3Status fmi3GetContinuousStates(fmi3Instance instance, fmi3Float64 continuousStates[], size_t nContinuousStates) {
    return fmi3Error;
}

fmi3Status fmi3GetNominalsOfContinuousStates(fmi3Instance instance, fmi3Float64 nominals[], size_t nContinuousStates) {
    return fmi3Error;
}

fmi3Status fmi3GetNumberOfEventIndicators(fmi3Instance instance, size_t* nEventIndicators) {
    return fmi3Error;
}

fmi3Status fmi3GetNumberOfContinuousStates(fmi3Instance instance, size_t* nContinuousStates) {
    return fmi3Error;
}

fmi3Status fmi3GetOutputDerivatives(fmi3Instance instance, const fmi3ValueReference valueReferences[], size_t nValueReferences, const fmi3Int32 orders[], fmi3Float64 values[], size_t nValues) {
    return fmi3Error;
}

fmi3Status fmi3ActivateModelPartition(fmi3Instance instance, fmi3ValueReference clockReference, fmi3Float64 activationTime) {
    return fmi3Error;
}
