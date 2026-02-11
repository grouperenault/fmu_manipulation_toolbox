#include <math.h>
#include <string.h>

#include "fmi2Functions.h"

#include "container.h"
#include "logger.h"

/*
 * FMI-2.0 implementation
 */

/*----------------------------------------------------------------------------
                               U T I L I T I E S
----------------------------------------------------------------------------*/

/* unimplemented fmi2 functions */
#define __NOT_IMPLEMENTED__ \
    logger(LOGGER_ERROR, "Function '%s' is not implemented", __func__); \
    return fmi2Error;

#define ASSERT_CONTAINER_STATE(_container, _state) \
    if (_container->state != _state) { \
    	logger(LOGGER_ERROR, "Must be in state %s to call %s", #_state, __func__); \
        return fmi2Error; \
    }

/*----------------------------------------------------------------------------
               F M I 2   F U N C T I O N S   ( G E N E R A L )
----------------------------------------------------------------------------*/

const char* fmi2GetTypesPlatform(void) {
    return fmi2TypesPlatform;
}


const char* fmi2GetVersion(void) {
    return fmi2Version;
}


fmi2Status  fmi2SetDebugLogging(fmi2Component c,
    fmi2Boolean loggingOn,
    size_t nCategories,
    const fmi2String categories[]) {

    logger_set_debug(loggingOn);

    return fmi2OK;
}


fmi2Component fmi2Instantiate(fmi2String instanceName,
    fmi2Type fmuType,
    fmi2String fmuGUID,
    fmi2String fmuResourceLocation,
    const fmi2CallbackFunctions* functions,
    fmi2Boolean visible,
    fmi2Boolean loggingOn) {
    container_t* container;

    container = container_new(instanceName, fmuGUID);

    if (container) {
        logger_function_t container_logger;
        container_logger.logger_fmi2 = functions->logger;
        if (functions->allocateMemory) {
            container->allocate_memory = functions->allocateMemory;
            container->free_memory = functions->freeMemory;
        }
        logger_init(FMU_2, container_logger, functions->componentEnvironment, container->instance_name, loggingOn); 
        /* logger() is available starting this point ! */

        if (fmuType != fmi2CoSimulation) {
            logger(LOGGER_ERROR, "Only CoSimulation mode is supported.");
            container_free(container);
            return NULL;
        } 

        logger(LOGGER_DEBUG, "Container model loading...");
        if (strncmp(fmuResourceLocation, "file://", 7) == 0)
            fmuResourceLocation += 7;
#ifdef WIN32
        if (fmuResourceLocation[0] == '/')
            fmuResourceLocation += 1;
#endif

        if (container_configure(container, fmuResourceLocation)) {
            logger(LOGGER_ERROR, "Cannot read container configuration.");
            container_free(container);
            return NULL;
        }
        logger(LOGGER_DEBUG, "Container configuration read.");
    }

    container->state = CONTAINER_STATE_INSTANTIATED;
    
    return container;
}


void fmi2FreeInstance(fmi2Component c) {
    container_t* container = (container_t*)c;

    logger(LOGGER_DEBUG, "Container instance '%s' release", container->instance_name);
    container_free(container);

    return;
}


fmi2Status fmi2SetupExperiment(fmi2Component c,
    fmi2Boolean toleranceDefined,
    fmi2Real tolerance,
    fmi2Real startTime,
    fmi2Boolean stopTimeDefined,
    fmi2Real stopTime) {
    container_t* container = (container_t*)c;

    ASSERT_CONTAINER_STATE(container, CONTAINER_STATE_INSTANTIATED);

    if (container_setup_experiment(container, toleranceDefined, tolerance,  startTime, stopTimeDefined, stopTime) != FMU_STATUS_OK)
        return fmi2Error;

    return fmi2OK;
}


fmi2Status fmi2EnterInitializationMode(fmi2Component c) {
    container_t* container = (container_t*)c;

    ASSERT_CONTAINER_STATE(container, CONTAINER_STATE_INSTANTIATED);

    if (container_enter_initialization_mode(container) != FMU_STATUS_OK) 
        return fmi2Error;
    
    container->state = CONTAINER_STATE_INITIALIZATION_MODE;

    return fmi2OK;
}


fmi2Status fmi2ExitInitializationMode(fmi2Component c) {
    container_t* container = (container_t*)c;

    ASSERT_CONTAINER_STATE(container, CONTAINER_STATE_INITIALIZATION_MODE);

    if (container_exit_initialization_mode(container) != FMU_STATUS_OK)
        return fmi2Error;

    container->state = CONTAINER_STATE_STEP_MODE; /* event mode is already handled */

    return fmi2OK;
}


fmi2Status fmi2Terminate(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_status_t status = fmuTerminate(&container->fmu[i]);

        if (status != FMU_STATUS_OK)
            return fmi2Error;
    }
 
    return fmi2OK;
}


fmi2Status fmi2Reset(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_status_t status = fmuReset(&container->fmu[i]);

        if (status != FMU_STATUS_OK)
            return fmi2Error;
    }
 
    return fmi2OK;
}


/* Getting and setting variable values */
#define FMI_GETTER(type, fmi_type, name) \
fmi2Status fmi2Get ## fmi_type (fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2 ## fmi_type value[]) { \
    container_t* container = (container_t*)c; \
    fmu_status_t status; \
\
    for (size_t i = 0; i < nvr; i += 1) { \
        const uint32_t local_vr = vr[i] & 0xFFFFFF; \
        const container_port_t *port = &container->port_ ##type [local_vr]; \
        const int fmu_id = port->links[0].fmu_id; \
\
        if (fmu_id < 0) { \
            value[i] = container-> type [local_vr]; \
        } else { \
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr; \
            const fmu_t *fmu = &container->fmu[fmu_id]; \
\
            status = fmuGet ## name (fmu, &fmu_vr, 1, &value[i]); \
            if (status != FMU_STATUS_OK) \
                return fmi2Error; \
        } \
    } \
\
    return fmi2OK; \
}


FMI_GETTER(reals64, Real, Real64);
FMI_GETTER(integers32, Integer, Integer32);
FMI_GETTER(booleans, Boolean, Boolean);
FMI_GETTER(strings, String, String);
#undef FMI_GETTER

#define FMI_SETTER(type, fmi_type, name) \
fmi2Status fmi2Set ## fmi_type (fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2 ## fmi_type value[]) { \
    container_t* container = (container_t*)c; \
    fmu_status_t status; \
\
    for (size_t i = 0; i < nvr; i += 1) { \
        const uint32_t local_vr = vr[i] & 0xFFFFFF; \
        const container_port_t *port = &container->port_ ##type [local_vr]; \
        for(int j = 0; j < port->nb; j += 1) { \
            const int fmu_id = port->links[j].fmu_id; \
\
            if (fmu_id < 0) {\
                container-> type [local_vr] = value[i]; \
            } else { \
                const fmu_t* fmu = &container->fmu[fmu_id]; \
                const fmi2ValueReference fmu_vr = port->links[j].fmu_vr; \
\
                status = fmuSet ## name (fmu, &fmu_vr, 1, &value[i]); \
                if (status != FMU_STATUS_OK) \
                    return fmi2Error; \
            } \
        } \
    } \
\
    return fmi2OK; \
}


FMI_SETTER(reals64, Real, Real64);
FMI_SETTER(integers32, Integer, Integer32);
FMI_SETTER(booleans, Boolean, Boolean);

fmi2Status fmi2SetString(fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2String value[]) {
    container_t* container = (container_t*)c;
    fmu_status_t status;
 
    for(size_t i = 0; i < nvr; i += 1) {
        const uint32_t local_vr = vr[i] & 0xFFFFFF;
        const container_port_t* port = &container->port_strings[local_vr];
        for(int j = 0; j < port->nb; j += 1) {
            const int fmu_id = port->links[j].fmu_id;

            if (fmu_id < 0) {
                free(container->strings[local_vr]);
                container->strings[local_vr] = strdup(value[i]);
            } else {
                const fmu_t* fmu = &container->fmu[fmu_id];
                const fmi2ValueReference fmu_vr = port->links[j].fmu_vr;
                
                status = fmuSetString(fmu, &fmu_vr, 1, &value[i]);
                if (status != FMU_STATUS_OK)
                    return fmi2Error;
            }
        }
    }
    return fmi2OK;
}

#undef FMI_SETTER


/* Getting and setting the internal FMU state */
fmi2Status fmi2GetFMUstate(fmi2Component c, fmi2FMUstate* FMUstate) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2SetFMUstate(fmi2Component c, fmi2FMUstate  FMUstate) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2FreeFMUstate(fmi2Component c, fmi2FMUstate* FMUstate) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2SerializedFMUstateSize(fmi2Component c, fmi2FMUstate  FMUstate, size_t* size) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2SerializeFMUstate(fmi2Component c, fmi2FMUstate  FMUstate, fmi2Byte serializedState[], size_t size) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2DeSerializeFMUstate(fmi2Component c, const fmi2Byte serializedState[], size_t size, fmi2FMUstate* FMUstate) {
    __NOT_IMPLEMENTED__
}


/* Getting partial derivatives */
fmi2Status fmi2GetDirectionalDerivative(fmi2Component c,
    const fmi2ValueReference vUnknown_ref[], size_t nUnknown,
    const fmi2ValueReference vKnown_ref[], size_t nKnown,
    const fmi2Real dvKnown[],
    fmi2Real dvUnknown[]) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2SetRealInputDerivatives(fmi2Component c,
    const fmi2ValueReference vr[], size_t nvr,
    const fmi2Integer order[],
    const fmi2Real value[]) {
    __NOT_IMPLEMENTED__
}


fmi2Status fmi2GetRealOutputDerivatives(fmi2Component c,
    const fmi2ValueReference vr[], size_t nvr,
    const fmi2Integer order[],
    fmi2Real value[]) {
    __NOT_IMPLEMENTED__
}


/*----------------------------------------------------------------------------
          F M I 2   F U N C T I O N S   ( C O S I M U L A T I O N )
----------------------------------------------------------------------------*/

fmi2Status fmi2DoStep(fmi2Component c,
    fmi2Real currentCommunicationPoint,
    fmi2Real communicationStepSize,
    fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    container_t *container = (container_t*)c;

    if (container_do_step(container, currentCommunicationPoint, communicationStepSize) != FMU_STATUS_OK)
        return fmi2Error;

    return fmi2OK;
}


fmi2Status fmi2CancelStep(fmi2Component c) {
    __NOT_IMPLEMENTED__
}


/*
 *  Can be called when the fmi2DoStep function returned 
 * fmi2Pending. The function delivers fmi2Pending if 
 * the computation is not finished. Otherwise the function 
 * returns the result of the asynchronously executed 
 * fmi2DoStep call.
 */
fmi2Status fmi2GetStatus(fmi2Component c, const fmi2StatusKind s, fmi2Status* value) {
    __NOT_IMPLEMENTED__
}


/*
 * Returns the end time of the last successfully completed 
 * communication step. Can be called after 
 * fmi2DoStep(..) returned fmi2Discard.
 */
fmi2Status fmi2GetRealStatus(fmi2Component c, const fmi2StatusKind s, fmi2Real* value) {
    container_t *container = (container_t*)c;

    if (s == fmi2LastSuccessfulTime) {
        *value = -1.0;
        fmi2Real last_time;
        for(int i = 0; i < container->nb_fmu; i += 1) {
            fmuGetRealStatus(&container->fmu[i], s, &last_time);
            if ((*value < 0) || (last_time < *value))
                *value = last_time;
        }
        return fmi2OK;
    }

    return fmi2Error;
}


fmi2Status fmi2GetIntegerStatus(fmi2Component c, const fmi2StatusKind s, fmi2Integer* value) {
    __NOT_IMPLEMENTED__
}


/*
 * Returns fmi2True, if the slave wants to terminate the 
 * simulation. Can be called after fmi2DoStep(..)
 * returned fmi2Discard. Use 
 * fmi2LastSuccessfulTime to determine the time 
 * instant at which the slave terminated.
 */
fmi2Status fmi2GetBooleanStatus(fmi2Component c, const fmi2StatusKind s, fmi2Boolean* value) {

    container_t *container = (container_t*)c;

    if (s == fmi2Terminated) {
        for(int i = 0; i < container->nb_fmu; i += 1) {
            fmuGetBooleanStatus(&container->fmu[i], s, value);
            if (value)
                break;
        }
        return fmi2OK;
    }

    return fmi2Error;
}


/*
 * Can be called when the fmi2DoStep function returned 
 * fmi2Pending. The function delivers a string which 
 * informs about the status of the currently running 
 * asynchronous fmi2DoStep computation.
 */
fmi2Status fmi2GetStringStatus(fmi2Component c, const fmi2StatusKind s, fmi2String* value) {
    __NOT_IMPLEMENTED__
}
