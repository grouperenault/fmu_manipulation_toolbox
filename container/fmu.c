#include <stdarg.h>
#include <string.h>

#include "convert.h"
#include "container.h"
#include "fmu.h"
#include "logger.h"
#include "profile.h"

#pragma warning(disable : 4100)     /* no complain abourt unref formal param */
#pragma warning(disable : 4996)     /* no complain about strncpy/strncat */


fmu_status_t fmu_set_inputs(fmu_t* fmu) {
    fmu_status_t status = FMU_STATUS_OK;

    if (fmu->set_input) {
        const container_t* container = fmu->container;
        const fmu_io_t* fmu_io = &fmu->fmu_io;

#define SET_INPUT(variable, fmi_type) \
    for (int i = 0; i < fmu_io-> variable .in.nb; i += 1) { \
        const unsigned int fmu_vr = fmu_io-> variable .in.translations[i].fmu_vr; \
        const unsigned int local_vr = fmu_io-> variable .in.translations[i].vr; \
        status = fmuSet ## fmi_type (fmu, &fmu_vr, 1, &container-> variable [local_vr]); \
        if (status != FMU_STATUS_OK) \
            return status; \
    }

        SET_INPUT(reals64, Real64);
        SET_INPUT(reals32, Real32);
        SET_INPUT(integers8, Integer8);
        SET_INPUT(uintegers8, UInteger8);
        SET_INPUT(integers16, Integer16);
        SET_INPUT(uintegers16, UInteger16);
        SET_INPUT(integers32, Integer32);
        SET_INPUT(uintegers32, UInteger32);
        SET_INPUT(integers64, Integer64);
        SET_INPUT(uintegers64, UInteger64);
        SET_INPUT(booleans, Boolean);
        SET_INPUT(booleans1, Boolean1);
        SET_INPUT(strings, String);
#undef SET_INPUT
    }
    else
        fmu->set_input = 1; /* Skip only the first doStep() */

    return status;
}


fmu_status_t fmu_get_outputs(fmu_t* fmu) {
    container_t* container = fmu->container;
    const fmu_io_t* fmu_io = &fmu->fmu_io;
    fmu_status_t status = FMU_STATUS_OK;

#define GET_OUTPUT(variable, fmi_type) \
    for (size_t i = 0; i < fmu_io-> variable .out.nb; i += 1) { \
        const fmu_vr_t fmu_vr = fmu_io-> variable .out.translations[i].fmu_vr; \
        const fmu_vr_t local_vr = fmu_io-> variable .out.translations[i].vr; \
        status = fmuGet ## fmi_type (fmu, &fmu_vr, 1, &container-> variable [local_vr]); \
        if (status != FMU_STATUS_OK) \
            return status; \
    }

GET_OUTPUT(reals64, Real64);
GET_OUTPUT(reals32, Real32);
GET_OUTPUT(integers8, Integer8);
GET_OUTPUT(uintegers8, UInteger8);
GET_OUTPUT(integers16, Integer16);
GET_OUTPUT(uintegers16, UInteger16);
GET_OUTPUT(integers32, Integer32);
GET_OUTPUT(uintegers32, UInteger32);
GET_OUTPUT(integers64, Integer64);
GET_OUTPUT(uintegers64, UInteger64);
GET_OUTPUT(booleans, Boolean);
GET_OUTPUT(booleans1, Boolean1);
GET_OUTPUT(strings, String);

#undef GET_OUTPUT

    /* cast conversion between local variables */
    convert_proceed(fmu->container, fmu->conversions);

    return status;
}


static int fmu_do_step_thread(fmu_t* fmu) {
    const container_t* container =fmu->container;

    while (!fmu->cancel) {
        thread_mutex_lock(&fmu->mutex_container);
        if (fmu->cancel)
            break;

        fmu->status = fmu_set_inputs(fmu);
        if (fmu->status != FMU_STATUS_OK) {
            thread_mutex_unlock(&fmu->mutex_fmu);
            continue;
        }
        double time = container->time_step * container->nb_steps + container->start_time;
        fmu->status = fmuDoStep(fmu, 
                                time,
                                container->time_step);

        thread_mutex_unlock(&fmu->mutex_fmu);
    }

    thread_mutex_unlock(&fmu->mutex_fmu);
    return 0;
}


static int fmu_map_functions(fmu_t *fmu, fmu_version_t fmi_version){
    int status = 0;

    if (fmi_version == 2) {
#define OPT_MAP(x) fmu->fmi_functions.version_2.x = (x ## TYPE*)library_symbol(fmu->library, #x)
#define REQ_MAP(x) OPT_MAP(x); if (!fmu->fmi_functions.version_2.x) { \
    logger(LOGGER_ERROR, "Missing API '" #x "'."); \
    status = -1; \
}
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
        REQ_MAP(fmi2GetString);
        REQ_MAP(fmi2SetReal);
        REQ_MAP(fmi2SetInteger);
        REQ_MAP(fmi2SetBoolean);
        REQ_MAP(fmi2SetString);
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
#undef OPT_MAP
#undef REQ_MAP
    }

    if (fmi_version == 3) {
#define OPT_MAP(x) fmu->fmi_functions.version_3.x = (x ## TYPE*)library_symbol(fmu->library, #x)
#define REQ_MAP(x) OPT_MAP(x); if (!fmu->fmi_functions.version_3.x) { \
    logger(LOGGER_ERROR, "Missing API '" #x "'."); \
    status = -1; \
}
        OPT_MAP(fmi3GetVersion);
        OPT_MAP(fmi3SetDebugLogging);
        REQ_MAP(fmi3InstantiateCoSimulation);
        REQ_MAP(fmi3FreeInstance);
        REQ_MAP(fmi3EnterInitializationMode);
        REQ_MAP(fmi3ExitInitializationMode);
        REQ_MAP(fmi3EnterEventMode);
        REQ_MAP(fmi3Terminate);
        REQ_MAP(fmi3Reset);
        REQ_MAP(fmi3GetFloat32);
        REQ_MAP(fmi3GetFloat64);
        REQ_MAP(fmi3GetInt8);
        REQ_MAP(fmi3GetUInt8);
        REQ_MAP(fmi3GetInt16);
        REQ_MAP(fmi3GetUInt16);
        REQ_MAP(fmi3GetInt32);
        REQ_MAP(fmi3GetUInt32);
        REQ_MAP(fmi3GetInt64);
        REQ_MAP(fmi3GetUInt64);
        REQ_MAP(fmi3GetBoolean);
        REQ_MAP(fmi3GetString);
        REQ_MAP(fmi3GetBinary);
        REQ_MAP(fmi3GetClock);
        REQ_MAP(fmi3SetFloat32);
        REQ_MAP(fmi3SetFloat64);
        REQ_MAP(fmi3SetInt8);
        REQ_MAP(fmi3SetUInt8);
        REQ_MAP(fmi3SetInt16);
        REQ_MAP(fmi3SetUInt16);
        REQ_MAP(fmi3SetInt32);
        REQ_MAP(fmi3SetUInt32);
        REQ_MAP(fmi3SetInt64);
        REQ_MAP(fmi3SetUInt64);
        REQ_MAP(fmi3SetBoolean);
        REQ_MAP(fmi3SetString);
        REQ_MAP(fmi3SetBinary);
        REQ_MAP(fmi3SetClock);
        OPT_MAP(fmi3GetNumberOfVariableDependencies);
        OPT_MAP(fmi3GetVariableDependencies);
        OPT_MAP(fmi3GetFMUState);
        OPT_MAP(fmi3SetFMUState);
        OPT_MAP(fmi3FreeFMUState);
        OPT_MAP(fmi3SerializedFMUStateSize);
        OPT_MAP(fmi3SerializeFMUState);
        OPT_MAP(fmi3DeserializeFMUState);
        OPT_MAP(fmi3GetDirectionalDerivative);
        OPT_MAP(fmi3GetAdjointDerivative);
        REQ_MAP(fmi3EnterConfigurationMode);
        REQ_MAP(fmi3ExitConfigurationMode);
        OPT_MAP(fmi3GetIntervalDecimal);
        OPT_MAP(fmi3GetIntervalFraction);
        OPT_MAP(fmi3GetShiftDecimal);
        OPT_MAP(fmi3GetShiftFraction);
        OPT_MAP(fmi3SetIntervalDecimal);
        OPT_MAP(fmi3SetIntervalFraction);
        OPT_MAP(fmi3SetShiftDecimal);
        OPT_MAP(fmi3SetShiftFraction);
        REQ_MAP(fmi3EvaluateDiscreteStates);
        OPT_MAP(fmi3UpdateDiscreteStates);
        REQ_MAP(fmi3EnterStepMode);
        OPT_MAP(fmi3GetOutputDerivatives);
        REQ_MAP(fmi3DoStep);
#undef OPT_MAP
#undef REQ_MAP
    }

    return status;
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


int fmu_load_from_directory(container_t *container, int i, const char *directory, const char *name,
                            const char *identifier, const char *guid, fmu_version_t fmi_version) {
    logger(LOGGER_DEBUG, "FMU#%d: loading '%s" FMU_BIN_SUFFIXE "' from directory '%s' (FMI-%d)", i, identifier, directory, fmi_version);

    fmu_t *fmu = &container->fmu[i];

    fmu->container = container;
    fmu->conversions = NULL;
    fmu->name = strdup(name);
    fmu->guid = strdup(guid);
    fmu->index = i;
    fmu->fmi_version = fmi_version;
    fmu->component = NULL;  /* will be set by fmuInstantiateCoSimulation() */

#define INIT_FMU_DATA(type) \
    fmu->fmu_io. type .in.translations = NULL; \
    fmu->fmu_io. type .out.translations = NULL; \
    fmu->fmu_io.start_ ## type .nb = 0; \
    fmu->fmu_io.start_ ## type .start_values = NULL;

    INIT_FMU_DATA(reals64);
    INIT_FMU_DATA(reals32);
    INIT_FMU_DATA(integers8);
    INIT_FMU_DATA(uintegers8);
    INIT_FMU_DATA(integers16);
    INIT_FMU_DATA(uintegers16);
    INIT_FMU_DATA(integers32);
    INIT_FMU_DATA(uintegers32);
    INIT_FMU_DATA(integers64);
    INIT_FMU_DATA(uintegers64);
    INIT_FMU_DATA(booleans);
    INIT_FMU_DATA(booleans1);
    INIT_FMU_DATA(strings);
#undef INIT_FMU_DATA

    char library_filename[FMU_PATH_MAX_LEN];
    library_filename[0] = '\0';
    switch(fmi_version) {
        case 2:
           strncpy(fmu->resource_dir, "file:///", FMU_PATH_MAX_LEN);
           fs_make_path(library_filename, FMU_PATH_MAX_LEN, directory, "binaries", FMU2_BINDIR, identifier, NULL);
            break;
        case 3:
            fmu->resource_dir[0] = '\0';
            fs_make_path(library_filename, FMU_PATH_MAX_LEN, directory, "binaries", FMU3_BINDIR, identifier, NULL);
            break;
        default:
            logger(LOGGER_ERROR, "Unsupported FMI-%d version.", fmi_version);
            return -1;
    }
    strncat(library_filename, FMU_BIN_SUFFIXE, FMU_PATH_MAX_LEN - strlen(library_filename));
 	fs_make_path(fmu->resource_dir, FMU_PATH_MAX_LEN, directory, "resources", NULL);

    fmu->library = library_load(library_filename);
    if (!fmu->library)
        return -2;
    
    if (fmu_map_functions(fmu, fmi_version)) {
        logger(LOGGER_ERROR, "missing API in %s", library_filename);
        return -3;
    }

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

    logger(LOGGER_DEBUG, "Unload FMU %s", fmu->name);

    /* Stop the thread */
    fmu->cancel = 1;
    thread_mutex_unlock(&fmu->mutex_container);
    thread_mutex_lock(&fmu->mutex_fmu);
    
    thread_join(fmu->thread);

    /* Free resources linked to threading */
    thread_mutex_free(&fmu->mutex_fmu);
    thread_mutex_free(&fmu->mutex_container);

    free(fmu->guid);
    free(fmu->name);
    convert_free(fmu->conversions);
    profile_free(fmu->profile);

    /* and finally unload the library */
    library_unload(fmu->library);

#define FREE_FMU_DATA(type) \
    free(fmu->fmu_io. type .in.translations); \
    free(fmu->fmu_io. type .out.translations); \
    free(fmu->fmu_io.start_ ## type .start_values)

    FREE_FMU_DATA(reals64);
    FREE_FMU_DATA(reals32);
    FREE_FMU_DATA(integers8);
    FREE_FMU_DATA(integers8);
    FREE_FMU_DATA(uintegers16);
    FREE_FMU_DATA(integers16);
    FREE_FMU_DATA(uintegers32);
    FREE_FMU_DATA(integers32);
    FREE_FMU_DATA(uintegers64);
    FREE_FMU_DATA(uintegers64);
    FREE_FMU_DATA(booleans);
    FREE_FMU_DATA(booleans1);
    for (int i = 0; i < fmu->fmu_io.start_strings.nb; i += 1)
        free((char*)fmu->fmu_io.start_strings.start_values[i].value);
    FREE_FMU_DATA(strings);
#undef FREE_FMU_DATA

    return;
}


#define GETTER_BOTH(type, fmi_type, fmi2_function, fmi3_function) \
fmu_status_t fmuGet ## fmi_type(const fmu_t *fmu, const fmu_vr_t vr[], size_t nvr, type value[]) { \
    fmu_status_t status = FMU_STATUS_OK; \
\
    if (fmu->fmi_version == FMU_2) { \
        fmi2Status status2 = fmu->fmi_functions.version_2. fmi2_function (fmu->component, vr, nvr, value); \
        if (status2 != fmi2OK) { \
            logger(LOGGER_ERROR, "%s: fmuGet" #fmi_type " status=%d", fmu->name, status2); \
            status = FMU_STATUS_ERROR; \
        } \
    } else { \
        fmi3Status status3 = fmu->fmi_functions.version_3. fmi3_function (fmu->component, vr, nvr, value, nvr); \
        if (status3 != fmi3OK) { \
            logger(LOGGER_ERROR, "%s: fmuGet" #fmi_type " status=%d", fmu->name, status3); \
            status = FMU_STATUS_ERROR; \
        } \
    } \
\
    return status;\
}


#define GETTER_3(type, fmi_type, fmi3_function) \
fmu_status_t fmuGet ## fmi_type(const fmu_t *fmu, const fmu_vr_t vr[], size_t nvr, type value[]) { \
    fmu_status_t status = FMU_STATUS_OK; \
\
    if (fmu->fmi_version == FMU_2) { \
        logger(LOGGER_ERROR, "%s: fmuGet" #fmi_type " not supported.", fmu->name); \
        status = FMU_STATUS_ERROR; \
    } else { \
        fmi3Status status3 = fmu->fmi_functions.version_3. fmi3_function (fmu->component, vr, nvr, value, nvr); \
        if (status3 != fmi3OK) { \
            logger(LOGGER_ERROR, "%s: fmuGet" #fmi_type " status=%d", fmu->name, status3); \
            status = FMU_STATUS_ERROR; \
        } \
    } \
\
    return status;\
}


#define GETTER_2(type, fmi_type, fmi2_function) \
fmu_status_t fmuGet ## fmi_type(const fmu_t *fmu, const fmu_vr_t vr[], size_t nvr, type value[]) { \
    fmu_status_t status = FMU_STATUS_OK; \
\
    if (fmu->fmi_version == FMU_2) { \
        fmi2Status status2 = fmu->fmi_functions.version_2. fmi2_function (fmu->component, vr, nvr, value); \
        if (status2 != fmi2OK) { \
            logger(LOGGER_ERROR, "%s: fmuGet" #fmi_type " status=%d", fmu->name, status2); \
            status = FMU_STATUS_ERROR; \
        } \
    } else { \
        logger(LOGGER_ERROR, "%s: fmuGet" #fmi_type " not supported.", fmu->name); \
        status = FMU_STATUS_ERROR; \
    } \
\
    return status;\
}


GETTER_BOTH(double,        Real64,      fmi2GetReal,    fmi3GetFloat64);

GETTER_3   (float,         Real32,                      fmi3GetFloat32);
GETTER_3   (int8_t,        Integer8,                    fmi3GetInt8);
GETTER_3   (uint8_t,       UInteger8,                   fmi3GetUInt8);
GETTER_3   (int16_t,       Integer16,                   fmi3GetInt16);
GETTER_3   (uint16_t,      UInteger16,                  fmi3GetUInt16);
GETTER_BOTH(int32_t,       Integer32,  fmi2GetInteger,  fmi3GetInt32);
GETTER_3   (uint32_t,      UInteger32,                  fmi3GetUInt32);
GETTER_3   (int64_t,       Integer64,                   fmi3GetInt64);
GETTER_3   (uint64_t,      UInteger64,                  fmi3GetUInt64);
GETTER_2   (int,           Boolean,    fmi2GetBoolean)
GETTER_3   (bool,          Boolean1,                    fmi3GetBoolean)
GETTER_BOTH(const char *,  String,     fmi2GetString,   fmi3GetString);

#undef GETTER_BOTH
#undef GETTER_3
#undef GETTER_2


#define SETTER_BOTH(type, fmi_type, fmi2_function, fmi3_function) \
fmu_status_t fmuSet ## fmi_type(const fmu_t *fmu, const fmu_vr_t vr[], size_t nvr, const type value[]) { \
    fmu_status_t status = FMU_STATUS_OK; \
\
    if (fmu->fmi_version == FMU_2) { \
        fmi2Status status2 = fmu->fmi_functions.version_2. fmi2_function (fmu->component, vr, nvr, value); \
        if (status2 != fmi2OK) { \
            logger(LOGGER_ERROR, "%s: fmuSet" #fmi_type " status=%d", fmu->name, status2); \
            status = FMU_STATUS_ERROR; \
        } \
    } else { \
        fmi3Status status3 = fmu->fmi_functions.version_3. fmi3_function (fmu->component, vr, nvr, value, nvr); \
        if (status3 != fmi3OK) { \
            logger(LOGGER_ERROR, "%s: fmuSet" #fmi_type " status=%d", fmu->name, status3); \
            status = FMU_STATUS_ERROR; \
        } \
    } \
\
    return status; \
} 


#define SETTER_3(type, fmi_type, fmi3_function) \
fmu_status_t fmuSet ## fmi_type(const fmu_t *fmu, const fmu_vr_t vr[], size_t nvr, const type value[]) { \
    fmu_status_t status = FMU_STATUS_OK; \
\
    if (fmu->fmi_version == FMU_2) { \
        logger(LOGGER_ERROR, "%s: fmuSet" #fmi_type " not supported.", fmu->name); \
        status = FMU_STATUS_ERROR; \
    } else { \
        fmi3Status status3 = fmu->fmi_functions.version_3. fmi3_function (fmu->component, vr, nvr, value, nvr); \
        if (status3 != fmi3OK) { \
            logger(LOGGER_ERROR, "%s: fmuSet" #fmi_type " tatus=%d", fmu->name, status3); \
            status = FMU_STATUS_ERROR; \
        } \
    } \
\
    return status;\
}


#define SETTER_2(type, fmi_type, fmi2_function) \
fmu_status_t fmuSet ## fmi_type(const fmu_t *fmu, const fmu_vr_t vr[], size_t nvr, const type value[]) { \
    fmu_status_t status = FMU_STATUS_OK; \
\
    if (fmu->fmi_version == FMU_2) { \
        fmi2Status status2 = fmu->fmi_functions.version_2. fmi2_function (fmu->component, vr, nvr, value); \
        if (status2 != fmi2OK) { \
            logger(LOGGER_ERROR, "%s: fmuSet" #fmi_type " status=%d", fmu->name, status2); \
            status = FMU_STATUS_ERROR; \
        } \
    } else { \
        logger(LOGGER_ERROR, "%s: fmuSet" #fmi_type " not supported.", fmu->name); \
        status = FMU_STATUS_ERROR; \
    } \
\
    return status;\
}


SETTER_BOTH(double,        Real64,      fmi2SetReal,    fmi3SetFloat64);
SETTER_3   (float,         Real32,                      fmi3SetFloat32);
SETTER_3   (int8_t,        Integer8,                    fmi3SetInt8);
SETTER_3   (uint8_t,       UInteger8,                   fmi3SetUInt8);
SETTER_3   (int16_t,       Integer16,                   fmi3SetInt16);
SETTER_3   (uint16_t,      UInteger16,                  fmi3SetUInt16);
SETTER_BOTH(int32_t,       Integer32,  fmi2SetInteger,  fmi3SetInt32);
SETTER_3   (uint32_t,      UInteger32,                  fmi3SetUInt32);
SETTER_3   (int64_t,       Integer64,                   fmi3SetInt64);
SETTER_3   (uint64_t,      UInteger64,                  fmi3SetUInt64);
SETTER_2   (int,           Boolean,    fmi2SetBoolean)
SETTER_3   (bool,          Boolean1,                    fmi3SetBoolean)
SETTER_BOTH(char * const,  String,     fmi2SetString,   fmi3SetString);

#undef SETTER_BOTH
#undef SETTER_3
#undef SETTER_2


fmu_status_t fmuDoStep(const fmu_t *fmu, 
                       double currentCommunicationPoint, 
                       double communicationStepSize) {
    fmu_status_t status = FMU_STATUS_ERROR;

    if (fmu->profile)
        profile_tic(fmu->profile);

    if (fmu->fmi_version == 2) {
        fmi2Status status2;
        logger(LOGGER_DEBUG, "%s fmuDoStep(%x, %f, %f) start %x", fmu->name, fmu->component, currentCommunicationPoint, communicationStepSize,
            fmu->fmi_functions.version_2.fmi2DoStep);

        status2 = fmu->fmi_functions.version_2.fmi2DoStep(fmu->component,
                                                          currentCommunicationPoint,
                                                          communicationStepSize,
                                                          fmi2True); /* noSetFMUStatePriorToCurrentPoint */
        logger(LOGGER_DEBUG, "%s fmuDoStep() end %d", fmu->name, status2);
        if ((status2 == fmi2OK) || (status2 == fmi2Warning))
            status = FMU_STATUS_OK;
    } else {
        fmi3Status status3;
        fmi3Boolean eventHandlingNeeded, terminateSimulation, earlyReturn;
        fmi3Float64 lastSuccessfulTime;
        status3 = fmu->fmi_functions.version_3.fmi3DoStep(fmu->component,
                                                          currentCommunicationPoint,
                                                          communicationStepSize,
                                                          fmi3True, 
                                                          &eventHandlingNeeded, 
                                                          &terminateSimulation, 
                                                          &earlyReturn, 
                                                          &lastSuccessfulTime);
        if (terminateSimulation) {
            logger(LOGGER_WARNING, "FMU '%s' requested to end the simulation.", fmu->name);
            status = FMU_STATUS_ERROR;
        }
        if (earlyReturn) {
            logger(LOGGER_ERROR, "FMU '%s' made an early return which is not supported.", fmu->name);
            status = FMU_STATUS_ERROR;
        }
        if (eventHandlingNeeded) {
            logger(LOGGER_ERROR, "FMU '%s' requested event handling which is not supported.", fmu->name);
            status = FMU_STATUS_ERROR;
        }
        if ((status3 == fmi3OK) || (status3 == fmi3Warning))
            status = FMU_STATUS_OK;
    }
      
    if (fmu->profile) {
        fmu->container->reals64[fmu->index+1] = profile_toc(fmu->profile, currentCommunicationPoint+communicationStepSize);
    }
    logger(LOGGER_DEBUG, "%s fmuDoStep() --OK", fmu->name);
    return status;
}


fmu_status_t fmuEnterInitializationMode(const fmu_t *fmu) {
    if (fmu->fmi_version == 2) {
        fmi2Status status2 = fmu->fmi_functions.version_2.fmi2EnterInitializationMode(fmu->component);
        if (status2 == fmi2OK)
            return FMU_STATUS_OK;
        else
            return FMU_STATUS_ERROR;
    } else {
        fmi3Status status3 = fmu->fmi_functions.version_3.fmi3EnterInitializationMode(fmu->component,
                                                                                      fmu->container->tolerance_defined, fmu->container->tolerance,
                                                                                      fmu->container->start_time,
                                                                                      fmu->container->stop_time_defined, fmu->container->stop_time);
        if (status3 == fmi3OK)
            return FMU_STATUS_OK;
        else
            return FMU_STATUS_ERROR;
    }
}


fmu_status_t fmuExitInitializationMode(const fmu_t *fmu) {
    if (fmu->fmi_version == 2) {
        fmi2Status status2 = fmu->fmi_functions.version_2.fmi2ExitInitializationMode(fmu->component);
        if (status2 == fmi2OK)
            return FMU_STATUS_OK;
        else
            return FMU_STATUS_ERROR;
    } else {
        fmi3Status status3 = fmu->fmi_functions.version_3.fmi3ExitInitializationMode(fmu->component);
        if (status3 == fmi3OK)
            return FMU_STATUS_OK;
        else
            return FMU_STATUS_ERROR;
    }
}


fmu_status_t fmuSetupExperiment(const fmu_t *fmu) {
    fmu_status_t status = FMU_STATUS_ERROR;

    if (fmu->fmi_version == 2) {
        fmi2Status status2 = fmu->fmi_functions.version_2.fmi2SetupExperiment(fmu->component,
                                                                              fmu->container->tolerance_defined, fmu->container->tolerance,
                                                                              fmu->container->start_time,
                                                                              fmu->container->stop_time_defined, fmu->container->stop_time);
        if ((status2 == fmi2OK) || (status2 == fmi2Warning))
            status = FMU_STATUS_OK;
    } else {
        /* No such API in FMI-3.0 */
        status = FMU_STATUS_OK;
    }
    
    return status;
}


fmu_status_t fmuInstantiateCoSimulation(fmu_t *fmu, const char *instanceName) {
    if (fmu->fmi_version == 2) {
        fmu->fmi2_callback_functions.componentEnvironment = fmu;
        fmu->fmi2_callback_functions.logger = (fmi2CallbackLogger)logger_embedded_fmu;
        fmu->fmi2_callback_functions.allocateMemory = NULL;
        fmu->fmi2_callback_functions.freeMemory = NULL;
        fmu->fmi2_callback_functions.stepFinished = NULL;

        fmu->component = fmu->fmi_functions.version_2.fmi2Instantiate(instanceName,
                                                                      fmi2CoSimulation,
                                                                      fmu->guid,
                                                                      fmu->resource_dir,
                                                                      &fmu->fmi2_callback_functions,
                                                                      fmi2False,    /* visible */
                                                                      logger_get_debug());
    } else {
        fmu->component =  fmu->fmi_functions.version_3.fmi3InstantiateCoSimulation(
            instanceName, 
            fmu->guid,
            fmu->resource_dir,
            fmi3False,  /* visible */
            logger_get_debug(),
            fmi3False, /* eventModeUsed */
            fmi3False, /* earlyReturnAllowed */
            NULL, /* requiredIntermediateVariables[] */
            0, /*  nRequiredIntermediateVariables */
            fmu, /* fmi3InstanceEnvironment */
            (fmi3LogMessageCallback)logger_embedded_fmu,
            NULL /* intermediateUpdateCallback */
        );
    } 
    if (!fmu->component)
        return FMU_STATUS_ERROR;

    return FMU_STATUS_OK;                
}


void fmuFreeInstance(const fmu_t *fmu) {
    if (fmu && fmu->component) { /* if embedded FMU is not well initialized */
        if (fmu->fmi_version == 2)
            fmu->fmi_functions.version_2.fmi2FreeInstance(fmu->component);
        else
            fmu->fmi_functions.version_3.fmi3FreeInstance(fmu->component);
    }
}


fmu_status_t fmuTerminate(const fmu_t *fmu) {
    fmu_status_t status = FMU_STATUS_ERROR;

    if (fmu->fmi_version == 2) {
        fmi2Status status2 = fmu->fmi_functions.version_2.fmi2Terminate(fmu->component);
        if (status2 == fmi2OK)
            status = FMU_STATUS_OK;
    } else {
        fmi3Status status3 = fmu->fmi_functions.version_3.fmi3Terminate(fmu->component);
        if (status3 == fmi3OK)
            status = FMU_STATUS_OK;
    } 
    return status;
}


fmu_status_t fmuReset(const fmu_t *fmu) {
    fmu_status_t status = FMU_STATUS_ERROR;

    if (fmu->fmi_version == 2) {
        fmi2Status status2 = fmu->fmi_functions.version_2.fmi2Reset(fmu->component);
        if (status2 == fmi2OK)
            status = FMU_STATUS_OK;
    } else {
        fmi3Status status3 = fmu->fmi_functions.version_3.fmi3Reset(fmu->component);
        if (status3 == fmi3OK)
            status = FMU_STATUS_OK;
    } 
    return status;
}


fmu_status_t fmuGetBooleanStatus(const fmu_t *fmu, const fmi2StatusKind s, fmi2Boolean* value) {
    fmu_status_t status = FMU_STATUS_ERROR;

    if (fmu->fmi_version == 2) {
        fmi2Status status2 = fmu->fmi_functions.version_2.fmi2GetBooleanStatus(fmu->component, s, value);
        if (status2 == fmi2OK)
            status = FMU_STATUS_OK;
    }

    return status;
}


fmu_status_t fmuGetRealStatus(const fmu_t *fmu, const fmi2StatusKind s, fmi2Real* value) {
    fmu_status_t status = FMU_STATUS_ERROR;
    if (fmu->fmi_version == 2) {
        fmi2Status status2 = fmu->fmi_functions.version_2.fmi2GetRealStatus(fmu->component, s, value);
        if (status2 == fmi2OK)
            status = FMU_STATUS_OK;
    }
    
    return status;
}
