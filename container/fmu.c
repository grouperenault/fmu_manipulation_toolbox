#include <stdarg.h>
#include <string.h>

#include "container.h"
#include "fmu.h"
#include "logger.h"
#include "profile.h"

#pragma warning(disable : 4100)     /* no complain abourt unref formal param */
#pragma warning(disable : 4996)     /* no complain about strncpy/strncat */


fmi2Status fmu_set_inputs(fmu_t *fmu) {
    fmi2Status status = fmi2OK;

    if (fmu->set_input) {
        const container_t *container = fmu->container;
        const fmu_io_t *fmu_io = &fmu->fmu_io;
        
#define SETTER(type, fmi_type) \
    for (fmi2ValueReference i = 0; i < fmu_io-> type .in.nb; i += 1) { \
        const fmi2ValueReference fmu_vr = fmu_io-> type .in.translations[i].fmu_vr; \
        const fmi2ValueReference local_vr = fmu_io-> type .in.translations[i].vr; \
        status = fmuSet ## fmi_type (fmu, &fmu_vr, 1, &container-> type [local_vr]); \
        if (status != fmi2OK) \
            return status; \
    }

        SETTER(reals, Real);
        SETTER(integers, Integer);
        SETTER(booleans, Boolean);
#undef SETTER
    } else
        fmu->set_input = 1; /* Skip only the first doStep() */
 
    return status;
}


static int fmu_do_step_thread(fmu_t* fmu) {
    const container_t* container =fmu->container;

    while (!fmu->cancel) {
        thread_mutex_lock(&fmu->mutex_container);
        if (fmu->cancel)
            break;

        fmu->status = fmu_set_inputs(fmu);
        if (fmu->status != fmi2OK) {
            thread_mutex_unlock(&fmu->mutex_fmu);
            continue;
        }

        fmu->status = fmuDoStep(fmu, 
                                container->fmi_currentCommunicationPoint,
                                container->fmi_step_size,
                                container->fmi_noSetFMUStatePriorToCurrentPoint);

        thread_mutex_unlock(&fmu->mutex_fmu);
    }

    thread_mutex_unlock(&fmu->mutex_fmu);
    return 0;
}


/** 
 * Specific: FMI2.0
 */
static int fmu_map_functions(fmu_t *fmu){

#define OPT_MAP(x) fmu->fmi_functions.x = (x ## TYPE*)library_symbol(fmu->library, #x)
#define REQ_MAP(x) OPT_MAP(x); if (!fmu->fmi_functions.x) return -1

    OPT_MAP(fmi2GetTypesPlatform);
    OPT_MAP(fmi2GetVersion);
    OPT_MAP(fmi2SetDebugLogging);
    REQ_MAP(fmi2Instantiate);
    REQ_MAP(fmi2FreeInstance);
    REQ_MAP(fmi2SetupExperiment);
    REQ_MAP(fmi2EnterInitializationMode);
    REQ_MAP(fmi2ExitInitializationMode);
    REQ_MAP(fmi2Terminate);
    REQ_MAP(fmi2Reset);
    REQ_MAP(fmi2GetReal);
    REQ_MAP(fmi2GetInteger);
    REQ_MAP(fmi2GetBoolean);
    OPT_MAP(fmi2GetString);
    REQ_MAP(fmi2SetReal);
    REQ_MAP(fmi2SetInteger);
    REQ_MAP(fmi2SetBoolean);
    OPT_MAP(fmi2SetString);
    OPT_MAP(fmi2GetFMUstate);
    OPT_MAP(fmi2SetFMUstate);
    OPT_MAP(fmi2FreeFMUstate);
    OPT_MAP(fmi2SerializedFMUstateSize);
    OPT_MAP(fmi2SerializeFMUstate);
    OPT_MAP(fmi2DeSerializeFMUstate);
    OPT_MAP(fmi2GetDirectionalDerivative);
    OPT_MAP(fmi2SetRealInputDerivatives);
    OPT_MAP(fmi2GetRealOutputDerivatives);
    REQ_MAP(fmi2DoStep);
    OPT_MAP(fmi2CancelStep);
    OPT_MAP(fmi2GetStatus);
    REQ_MAP(fmi2GetRealStatus);
    OPT_MAP(fmi2GetIntegerStatus);
    REQ_MAP(fmi2GetBooleanStatus);
    OPT_MAP(fmi2GetStringStatus);
#undef MAP
    return 0;
}


static void fs_make_path(char* buffer, size_t len, ...) {
	va_list params;
	va_start(params, len);
	const char* folder;
	int i = 0;
	while ((folder = va_arg(params, const char*))) {
		size_t current_len = strlen(buffer);
		if ((i > 0) && (current_len < len)) {
#ifdef WIN32
			buffer[current_len++] = '\\';
#else
            buffer[current_len++] = '/';
#endif
			buffer[current_len] = '\0';
		}
		strncat(buffer, folder, len - current_len -1);
		i += 1;
	}

	va_end(params);

	return;
}


/** 
 * Specific: FMI2.0
 */
int fmu_load_from_directory(container_t *container, int i, const char *directory, char *identifier, const char *guid) {
    if (! container)
        return -1;
    fmu_t *fmu = &container->fmu[i];
    fmu->container = container;
    fmu->identifier = identifier;
    fmu->index = i;
    

    char library_filename[FMU_PATH_MAX_LEN];

    fmu->guid = strdup(guid);
    library_filename[0] = '\0';
    fs_make_path(library_filename, FMU_PATH_MAX_LEN, directory, "binaries\\win64", identifier, NULL);
    strncat(library_filename, ".dll", FMU_PATH_MAX_LEN - strlen(library_filename));

    strncpy(fmu->resource_dir, "file:///", FMU_PATH_MAX_LEN);
	fs_make_path(fmu->resource_dir, FMU_PATH_MAX_LEN, directory, "resources", NULL);

    fmu->library = library_load(library_filename);
    if (!fmu->library)
        return -2;
    
    if (fmu_map_functions(fmu))
        return -3;

    fmu->cancel = 0;
    fmu->set_input = 0;
    if (container->profiling)
        fmu->profile = profile_new();
    else
        fmu->profile = NULL;

    fmu->mutex_fmu = thread_mutex_new();
    fmu->mutex_container = thread_mutex_new();
    fmu->thread = thread_new((thread_function_t)fmu_do_step_thread, fmu);

    return 0;
}


void fmu_unload(fmu_t *fmu) {

    /* Stop the thread */
    fmu->cancel = 1;
    thread_mutex_unlock(&fmu->mutex_container);
    thread_mutex_lock(&fmu->mutex_fmu);
#ifdef WIN32
    WaitForSingleObject(fmu->thread, INFINITE);
#else
    pthread_join(fmu->thread, NULL);
#endif


    /* Free resources linked to threading */
#ifdef WIN32
    CloseHandle(fmu->thread);
#endif

    thread_mutex_free(&fmu->mutex_fmu);
    thread_mutex_free(&fmu->mutex_container);

    free(fmu->guid);
    free(fmu->identifier);
    profile_free(fmu->profile);

    /* and finally unload the library */
    library_unload(fmu->library);
}


fmi2Status fmuGetReal(const fmu_t *fmu, const fmi2ValueReference vr[], size_t nvr, fmi2Real value[]) {
    fmi2Status status = fmu->fmi_functions.fmi2GetReal(fmu->component, vr, nvr, value);
    if (status != fmi2OK)
        logger(status, "%s: fmuGetReal status=%d", fmu->identifier, status);
    return status;
}


fmi2Status fmuGetInteger(const fmu_t *fmu, const fmi2ValueReference vr[], size_t nvr, fmi2Integer value[]) {
    fmi2Status status = fmu->fmi_functions.fmi2GetInteger(fmu->component, vr, nvr, value);
    if (status != fmi2OK)
        logger(status, "%s: fmuGetInteger status=%d", fmu->identifier, status);
    return status;
}


fmi2Status fmuGetBoolean(const fmu_t *fmu, const fmi2ValueReference vr[], size_t nvr, fmi2Boolean value[]) {
    fmi2Status status = fmu->fmi_functions.fmi2GetBoolean(fmu->component, vr, nvr, value);
    if (status != fmi2OK)
        logger(status, "%s: fmuGetBoolean status=%d", fmu->identifier, status);
    return status;
}


fmi2Status fmuSetReal(const fmu_t *fmu, const fmi2ValueReference vr[], size_t nvr, const fmi2Real value[]) {
    fmi2Status status = fmu->fmi_functions.fmi2SetReal(fmu->component, vr, nvr, value);
    if (status != fmi2OK)
        logger(status, "%s: fmuSetReal status=%d", fmu->identifier, status);
    return status;
}


fmi2Status fmuSetInteger(const fmu_t *fmu, const fmi2ValueReference vr[], size_t nvr, const fmi2Integer value[]) {
    fmi2Status status = fmu->fmi_functions.fmi2SetInteger(fmu->component, vr, nvr, value);
    if (status != fmi2OK)
        logger(status, "%s: fmuSetInteger status=%d", fmu->identifier, status);
    return status;
}


fmi2Status fmuSetBoolean(const fmu_t *fmu, const fmi2ValueReference vr[], size_t nvr, const fmi2Boolean value[]) {
    fmi2Status status = fmu->fmi_functions.fmi2SetBoolean(fmu->component, vr, nvr, value);
    if (status != fmi2OK)
        logger(status, "%s: fmuSetBoolean status=%d", fmu->identifier, status);
    return status;
}


fmi2Status fmuDoStep(const fmu_t *fmu, 
                     fmi2Real currentCommunicationPoint, 
                     fmi2Real communicationStepSize, 
                     fmi2Boolean noSetFMUStatePriorToCurrentPoint) {

    if (fmu->profile)
        profile_tic(fmu->profile);

    logger(fmi2Error, "DEBUG-NL: %s doStep(%e, %e, %d)", fmu->identifier, currentCommunicationPoint, communicationStepSize, noSetFMUStatePriorToCurrentPoint);

    fmi2Status status = fmu->fmi_functions.fmi2DoStep(fmu->component, 
                                                     currentCommunicationPoint,
                                                     communicationStepSize,
                                                     noSetFMUStatePriorToCurrentPoint);

    if (fmu->profile) {
        fmu->container->reals[fmu->index] = profile_toc(fmu->profile, currentCommunicationPoint+communicationStepSize);
    }

    return status;
}


fmi2Status fmuEnterInitializationMode(const fmu_t *fmu) {
    return fmu->fmi_functions.fmi2EnterInitializationMode(fmu->component);
}


fmi2Status fmuExitInitializationMode(const fmu_t *fmu) {
    return fmu->fmi_functions.fmi2ExitInitializationMode(fmu->component);
}


fmi2Status fmuSetupExperiment(const fmu_t *fmu,
                              fmi2Boolean toleranceDefined,
                              fmi2Real tolerance,
                              fmi2Real startTime,
                              fmi2Boolean stopTimeDefined,
                              fmi2Real stopTime) {
    fmi2Status status;

    status = fmu->fmi_functions.fmi2SetupExperiment(fmu->component,
                                                    toleranceDefined, tolerance,
                                                    startTime,
                                                    stopTimeDefined, stopTime);
    
    return status;
}


fmi2Status fmuInstantiate(fmu_t *fmu,
                          fmi2String instanceName,
                          fmi2Type fmuType,
                          fmi2Boolean visible,
                          fmi2Boolean loggingOn) {

    fmu->fmi_callback_functions.componentEnvironment = fmu;
    fmu->fmi_callback_functions.logger = (fmi2CallbackLogger)logger_embedded_fmu;
    fmu->fmi_callback_functions.allocateMemory = fmu->container->callback_functions->allocateMemory;
    fmu->fmi_callback_functions.freeMemory = fmu->container->callback_functions->freeMemory;
    fmu->fmi_callback_functions.stepFinished = NULL;

    fmu->component = fmu->fmi_functions.fmi2Instantiate(instanceName,
                                                        fmuType,
                                                        fmu->guid,
                                                        fmu->resource_dir,
                                                        &fmu->fmi_callback_functions,
                                                        fmi2False,
                                                        fmu->container->debug);

    if (!fmu->component)
        return fmi2Error;

    return fmi2OK;                
}


void fmuFreeInstance(const fmu_t *fmu) {
    fmu->fmi_functions.fmi2FreeInstance(fmu->component);
}


fmi2Status fmuTerminate(const fmu_t *fmu) {
    return fmu->fmi_functions.fmi2Terminate(fmu->component);
}


fmi2Status fmuReset(const fmu_t *fmu) {
    return fmu->fmi_functions.fmi2Reset(fmu->component);
}


fmi2Status fmuGetBooleanStatus(const fmu_t *fmu, const fmi2StatusKind s, fmi2Boolean* value) {
    return fmu->fmi_functions.fmi2GetBooleanStatus(fmu->component, s, value);
}


fmi2Status fmuGetRealStatus(const fmu_t *fmu, const fmi2StatusKind s, fmi2Real* value) {
    return fmu->fmi_functions.fmi2GetRealStatus(fmu->component, s, value);
}
