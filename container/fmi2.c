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

    container = malloc(sizeof(*container));
    if (container) {
        container->instance_name = strdup(instanceName);
        container->uuid = strdup(fmuGUID);

        logger_function_t container_logger;
        container_logger.logger_fmi2 = functions->logger;
        logger_init(FMU_2, container_logger, functions->componentEnvironment, container->instance_name, loggingOn); 
        /* logger() is available starting this point ! */

        if (fmuType != fmi2CoSimulation) {
            logger(LOGGER_ERROR, "Only CoSimulation mode is supported.");
            free(container);
            return NULL;
        }

        container->mt = 0;
        container->nb_fmu = 0;
        container->fmu = NULL;

        container->nb_local_reals = 0;
        container->nb_local_integers = 0;
        container->nb_local_booleans = 0;
        container->nb_local_strings = 0;
        container->reals = NULL;
        container->integers = NULL;
        container->booleans = NULL;
        container->strings = NULL;

        container->nb_ports_reals = 0;
        container->nb_ports_integers = 0;
        container->nb_ports_booleans = 0;
        container->nb_ports_strings = 0;
        container->vr_reals = NULL;
        container->vr_integers = NULL;
        container->vr_booleans = NULL;
        container->vr_strings = NULL;

        container->time_step = 0.001;
        container->time = 0.0;
        container->tolerance = 1.0e-8;

        logger(LOGGER_DEBUG, "Container model loading...");
        if (strncmp(fmuResourceLocation, "file:///", 8) == 0)
            fmuResourceLocation += 8;

        if (container_read_conf(container, fmuResourceLocation)) {
            logger(LOGGER_ERROR, "Cannot read container configuration.");
            fmi2FreeInstance(container);
            return NULL;
        }
        logger(LOGGER_DEBUG, "Container configuration read.");

        for (int i = 0; i < container->nb_fmu; i += 1)
            container->fmu[i].component = NULL;

        for(int i=0; i < container->nb_fmu; i += 1) {
            fmu_status_t status = fmuInstantiateCoSimulation(&container->fmu[i],
                                                             container->instance_name);
            if (status != FMU_STATUS_OK) {
                logger(LOGGER_ERROR, "Cannot Instantiate FMU#%d", i);
                fmi2FreeInstance(container);
                return NULL;
            }
        }
    }
    return container;
}


void fmi2FreeInstance(fmi2Component c) {
    container_t* container = (container_t*)c;

    if (container) {

        if (container->fmu) {
            for (int i = 0; i < container->nb_fmu; i += 1) {
                fmuFreeInstance(&container->fmu[i]);
                fmu_unload(&container->fmu[i]);

                free(container->fmu[i].fmu_io.reals.in.translations);
                free(container->fmu[i].fmu_io.integers.in.translations);
                free(container->fmu[i].fmu_io.booleans.in.translations);
                free(container->fmu[i].fmu_io.strings.in.translations);

                free(container->fmu[i].fmu_io.reals.out.translations);
                free(container->fmu[i].fmu_io.integers.out.translations);
                free(container->fmu[i].fmu_io.booleans.out.translations);
                free(container->fmu[i].fmu_io.strings.out.translations);

                free(container->fmu[i].fmu_io.start_reals.start_values);
                free(container->fmu[i].fmu_io.start_integers.start_values);
                free(container->fmu[i].fmu_io.start_booleans.start_values);

                for (int j = 0; j < container->fmu[i].fmu_io.start_strings.nb; j += 1)
                    free((char *)container->fmu[i].fmu_io.start_strings.start_values[j].value);
                free(container->fmu[i].fmu_io.start_strings.start_values);
            }

            free(container->fmu);
        }

        free(container->instance_name);
        free(container->uuid);

        free(container->vr_reals);
        free(container->port_reals);
        free(container->vr_integers);
        free(container->port_integers);
        free(container->vr_booleans);
        free(container->port_booleans);
        free(container->vr_strings);
        free(container->port_strings);

        free(container->reals);
        free(container->integers);
        free(container->booleans);
        free((void*)container->strings);

        free(container);
    }

    return;
}


static void container_set_start_values(container_t* container, int early_set) {
    if (early_set)
        logger(LOGGER_DEBUG, "Setting start values...");
    else
        logger(LOGGER_DEBUG, "Re-setting some start values...");
    for (int i = 0; i < container->nb_fmu; i += 1) {
#define SET_START(fmi_type, type) \
        for(fmi2ValueReference j=0; j<container->fmu[i].fmu_io.start_ ## type .nb; j ++) { \
            if (early_set || container->fmu[i].fmu_io.start_ ## type.start_values[j].reset) \
                fmuSet ## fmi_type(&container->fmu[i], &container->fmu[i].fmu_io.start_ ## type.start_values[j].vr, 1, \
                    &container->fmu[i].fmu_io.start_ ## type.start_values[j].value); \
        }
 
        SET_START(Real, reals);
        SET_START(Integer, integers);
        SET_START(Boolean, booleans);
        SET_START(String, strings);
#undef SET_START
    }
    logger(LOGGER_DEBUG, "Start values are set.");
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


FMI_GETTER(reals, Real);
FMI_GETTER(integers, Integer);
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


FMI_SETTER(reals, Real);
FMI_SETTER(integers, Integer);
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

GETTER(reals, Real);
GETTER(integers, Integer);
GETTER(booleans, Boolean);
GETTER(strings, String);

#undef GETTER

    return status;
}


static fmu_status_t do_internal_step_serie(container_t *container, fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    fmu_status_t status;

    for (int i = 0; i < container->nb_fmu; i += 1) {
        fmu_t* fmu = &container->fmu[i];

        status = fmu_set_inputs(fmu);
        if (status != FMU_STATUS_OK)
            return status;
            
        /* COMPUTATION */
        status = fmuDoStep(fmu, container->time, container->time_step);
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

    for (size_t i = 0; i < container->nb_fmu; i += 1) {          
        status = fmu_set_inputs(&container->fmu[i]);
        if (status != FMU_STATUS_OK) 
            return status;
    }

    for (size_t i = 0; i < container->nb_fmu; i += 1) {
        const fmu_t* fmu = &container->fmu[i];
        /* COMPUTATION */
        status = fmuDoStep(fmu, container->time, container->time_step);
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


fmi2Status fmi2DoStep(fmi2Component c,
    fmi2Real currentCommunicationPoint,
    fmi2Real communicationStepSize,
    fmi2Boolean noSetFMUStatePriorToCurrentPoint) {
    container_t *container = (container_t*)c;
    const fmi2Real end_time = currentCommunicationPoint + communicationStepSize;
    fmu_status_t status = FMU_STATUS_OK;


    const int nb_step = (int)((end_time - container->time + container->tolerance) / container->time_step);
    
    /*
     * Early return if requested end_time is lower than next container time step.
     */
    if (nb_step == 0)
        return fmi2OK;
    
    for(int i = 0; i < nb_step; i += 1) {
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
    }

    if (fabs(end_time - container->time) > container->tolerance) {
        logger(LOGGER_WARNING, "Container CommunicationStepSize should be divisible by %e. (currentCommunicationPoint=%e, container_time=%e, expected_time=%e, tolerance=%e, nb_step=%d)", 
            container->time_step, currentCommunicationPoint, container->time, end_time, container->tolerance, nb_step);
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
