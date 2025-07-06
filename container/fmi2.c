#include <math.h>
#include <string.h>

#include "fmi2Functions.h"

#include "container.h"
#include "logger.h"



/*----------------------------------------------------------------------------
                               U T I L I T I E S
----------------------------------------------------------------------------*/

/* unimplemented fmi2 functions */
#define __NOT_IMPLEMENTED__ \
    logger(LOGGER_ERROR, "Function '%s' is not implemented", __func__); \
    return fmi2Error;


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
    container_t* container = (container_t*)c;

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

        if (container_configure(container, fmuResourceLocation)) {
            logger(LOGGER_ERROR, "Cannot read container configuration.");
            container_free(container);
            return NULL;
        }
        logger(LOGGER_DEBUG, "Container configuration read.");
    }
    return container;
}


void fmi2FreeInstance(fmi2Component c) {
    container_t* container = (container_t*)c;

    if (container)
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

    container->tolerance_defined = toleranceDefined;
    container->tolerance = tolerance;
    container->start_time = startTime;
    container->stop_time_defined = 0; /* stopTime can cause rounding issues. Disbale it.*/
    container->stop_time = stopTime;

    for(int i=0; i < container->nb_fmu; i += 1) {
        fmu_status_t status = fmuSetupExperiment(&container->fmu[i]);    
        
        if (status != FMU_STATUS_OK)
            return fmi2OK;
    }

    container_set_start_values(container, 1);
    logger(LOGGER_DEBUG, "fmi2SetupExperiment -- OK");

    return fmi2OK;
}


fmi2Status fmi2EnterInitializationMode(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_status_t status = fmuEnterInitializationMode(&container->fmu[i]);
        if (status != FMU_STATUS_OK)
            return fmi2Error;
    }

    container_set_start_values(container, 0);

    return fmi2OK;
}


fmi2Status fmi2ExitInitializationMode(fmi2Component c) {
    container_t* container = (container_t*)c;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_status_t status = fmuExitInitializationMode(&container->fmu[i]);

        if (status != FMU_STATUS_OK)
            return fmi2Error;
    }
 
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
#define FMI_GETTER(type, fmi_type) \
fmi2Status fmi2Get ## fmi_type (fmi2Component c, const fmi2ValueReference vr[], size_t nvr, fmi2 ## fmi_type value[]) { \
    container_t* container = (container_t*)c; \
    fmu_status_t status; \
\
    for (size_t i = 0; i < nvr; i += 1) { \
        const container_port_t *port = &container->port_ ##type [vr[i]]; \
        const int fmu_id = port->links[0].fmu_id; \
\
        if (fmu_id < 0) { \
            value[i] = container-> type [vr[i]]; \
        } else { \
            const fmu_vr_t fmu_vr = port->links[0].fmu_vr; \
            const fmu_t *fmu = &container->fmu[fmu_id]; \
\
            status = fmuGet ## fmi_type (fmu, &fmu_vr, 1, &value[i]); \
            if (status != FMU_STATUS_OK) \
                return fmi2Error; \
        } \
    } \
\
    return fmi2OK; \
}


FMI_GETTER(reals64, Real);
FMI_GETTER(integers32, Integer);
FMI_GETTER(booleans, Boolean);
FMI_GETTER(strings, String);
#undef FMI_GETTER

#define FMI_SETTER(type, fmi_type) \
fmi2Status fmi2Set ## fmi_type (fmi2Component c, const fmi2ValueReference vr[], size_t nvr, const fmi2 ## fmi_type value[]) { \
    container_t* container = (container_t*)c; \
    fmu_status_t status; \
\
    for (size_t i = 0; i < nvr; i += 1) { \
        const container_port_t *port = &container->port_ ##type [vr[i]]; \
        for(int j = 0; j < port->nb; j += 1) { \
            const int fmu_id = port->links[j].fmu_id; \
\
            if (fmu_id < 0) {\
                container-> type [vr[i]] = value[i]; \
            } else { \
                const fmu_t* fmu = &container->fmu[fmu_id]; \
                const fmi2ValueReference fmu_vr = port->links[j].fmu_vr; \
\
                status = fmuSet ## fmi_type (fmu, &fmu_vr, 1, &value[i]); \
                if (status != FMU_STATUS_OK) \
                    return fmi2Error; \
            } \
        } \
    } \
\
    return fmi2OK; \
}


FMI_SETTER(reals64, Real);
FMI_SETTER(integers32, Integer);
FMI_SETTER(booleans, Boolean);
FMI_SETTER(strings, String);

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

static fmu_status_t do_step_get_outputs(container_t* container, int fmu_id) {
    const fmu_t* fmu = &container->fmu[fmu_id];
    const fmu_io_t* fmu_io = &fmu->fmu_io;
    fmu_status_t status = FMU_STATUS_OK;

#define GETTER(type, fmi_type) \
    for (size_t i = 0; i < fmu_io-> type .out.nb; i += 1) { \
        const fmu_vr_t fmu_vr = fmu_io-> type .out.translations[i].fmu_vr; \
        const fmu_vr_t local_vr = fmu_io-> type .out.translations[i].vr; \
        status = fmuGet ## fmi_type (fmu, &fmu_vr, 1, &container-> type [local_vr]); \
        if (status != FMU_STATUS_OK) \
            return status; \
    }

GETTER(reals64, Real);
GETTER(integers32, Integer);
GETTER(booleans, Boolean);
GETTER(strings, String);

#undef GETTER

    return status;
}

#if 0
static fmu_status_t do_internal_step_serie(container_t *container, fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    fmu_status_t status;
    double time = container->time_step * container->nb_steps + container->start_time;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t* fmu = &container->fmu[i];

        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK)
            return status;
            
        /* COMPUTATION */
        status = fmuDoStep(fmu, time, container->time_step);
        if (status != FMU_STATUS_OK)
            return status;

        status = do_step_get_outputs(container, i);
        if (status != FMU_STATUS_OK)
            return status;
        
    }

    return status;
}


static fmu_status_t do_internal_step_parallel_mt(container_t* container) {
    fmu_status_t status = FMU_STATUS_OK;

    /* Launch computation for all threads*/
    for(size_t i = 0; i < container->nb_fmu; i += 1) {
        container->fmu[i].status = FMU_STATUS_ERROR;
        thread_mutex_unlock(&container->fmu[i].mutex_container);
    }

    /* Consolidate results */
    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        thread_mutex_lock(&container->fmu[i].mutex_fmu);
        if (container->fmu[i].status != FMU_STATUS_OK)
            return FMU_STATUS_ERROR;
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        status = do_step_get_outputs(container, i);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container: FMU#%d failed doStep.", i);
            return FMU_STATUS_ERROR;
        }
    }
    
    return status;
}


static fmu_status_t do_internal_step_parallel(container_t* container) {
    static int set_input = 0;
    fmu_status_t status = FMU_STATUS_OK;
    double time = container->time_step * container->nb_steps + container->start_time;

    for (size_t i = 0; i < container->nb_fmu; i += 1) {          
        status = fmu_set_inputs(&container->fmu[i]);
        if (status != FMU_STATUS_OK) 
            return status;
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        const fmu_t* fmu = &container->fmu[i];
        /* COMPUTATION */
        status = fmuDoStep(fmu,time, container->time_step);
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container: FMU#%d failed doStep.", i);
            return status;
        }
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        status = do_step_get_outputs(container, i);
        if (status != FMU_STATUS_OK)
            return status;
    }
    
    return status;
}
#endif

fmi2Status fmi2DoStep(fmi2Component c,
    fmi2Real currentCommunicationPoint,
    fmi2Real communicationStepSize,
    fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    container_t *container = (container_t*)c;
    const fmi2Real end_time = currentCommunicationPoint + communicationStepSize;
    fmu_status_t status = FMU_STATUS_OK;
    const fmi2Real curent_time = container->start_time + container->time_step * container->nb_steps;


    const int local_steps = (int)((end_time - curent_time + container->tolerance) / container->time_step);
    
    /*
     * Early return if requested end_time is lower than next container time step.
     */
    if (local_steps == 0)
        return fmi2OK;
    
    for(int i = 0; i < local_steps; i += 1) {
        container->do_step(container);
        container->nb_steps += 1;

        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container cannot DoStep.");
            return fmi2Error;
        }
    }       
/*
#if 1
        if (container->mt)
            status = do_internal_step_parallel_mt(container);
        else
            status = do_internal_step_parallel(container);
        container->time += container->time_step;
        if (status != FMU_STATUS_OK) {
            logger(LOGGER_ERROR, "Container cannot do_internal_step.");
            return fmi2Error;
        }
#else
        status = do_internal_step_serie(container);
        container->time = start_time + (i + 1) * container->time_step;
        if ((status != fmi2OK) && (status != fmi2Warning)) {
            logger(LOGGER_ERROR, "Container cannot do_internal_step. Status=%d", status);
            return status;
        }
#endif
*/
    const double new_time = container->start_time + container->time_step * container->nb_steps;
    if (fabs(end_time - new_time) > container->tolerance) {
        logger(LOGGER_WARNING, "Container CommunicationStepSize should be divisible by %e. (currentCommunicationPoint=%e, container_time=%e, expected_time=%e, tolerance=%e, local_steps=%d, nb_steps=%lld)", 
            container->time_step, currentCommunicationPoint, new_time, end_time, container->tolerance, local_steps, container->nb_steps);
        return fmi2Warning;
    }

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
