#ifndef FMU_H
#   define FMU_H

#	ifdef __cplusplus
extern "C" {
#	endif

#   include "fmi2Functions.h"
#   include "fmi3Functions.h"
#   include "container.h"
#   include "library.h"
#   include "profile.h"
#   include "thread.h"



/*----------------------------------------------------------------------------
                   F M U _ T R A N S L A T I O N _ T
----------------------------------------------------------------------------*/
typedef struct {
	fmi2ValueReference			vr;
	fmi2ValueReference			fmu_vr;
} fmu_translation_t;


/*----------------------------------------------------------------------------
              F M U _ T R A N S L A T I O N _ L I S T _ T
----------------------------------------------------------------------------*/
typedef struct {
	fmi2ValueReference			nb;
	fmu_translation_t			*translations;
} fmu_translation_list_t;


/*----------------------------------------------------------------------------
              F M U _ T R A N S L A T I O N _ P O R T _ T
----------------------------------------------------------------------------*/
typedef struct {
	fmu_translation_list_t		in;
	fmu_translation_list_t		out;
} fmu_translation_port_t;


/*----------------------------------------------------------------------------
              F M U _ S T A R T _ xxx _ T
----------------------------------------------------------------------------*/

#define DECLARE_START_TYPE(name, type) \
typedef struct { \
    fmi2ValueReference          nb; \
    struct { \
        fmi2ValueReference      vr; \
        int                     reset; \
        type                    value; \
    } *start_values; \
} fmu_start_ ## name ## _t

DECLARE_START_TYPE(reals, fmi2Real);
DECLARE_START_TYPE(integers, fmi2Integer);
DECLARE_START_TYPE(booleans, fmi2Boolean);
DECLARE_START_TYPE(strings, fmi2String);

#undef DECLARE_TYPE_START


/*----------------------------------------------------------------------------
                              F M U _ I O _ T
----------------------------------------------------------------------------*/
typedef struct {
	fmu_translation_port_t		reals;
	fmu_translation_port_t		integers;
	fmu_translation_port_t		booleans;
	fmu_translation_port_t		strings;

    fmu_start_reals_t           start_reals;
    fmu_start_integers_t        start_integers;
    fmu_start_booleans_t        start_booleans;
    fmu_start_strings_t         start_strings;
} fmu_io_t;


/*----------------------------------------------------------------------------
                        F M U _ I N T E R F A C E _ T
----------------------------------------------------------------------------*/
typedef union {
#	define DECLARE_FMI_FUNCTION(x) x ## TYPE *x
    struct {
        DECLARE_FMI_FUNCTION(fmi2GetTypesPlatform);
        DECLARE_FMI_FUNCTION(fmi2GetVersion);
        DECLARE_FMI_FUNCTION(fmi2SetDebugLogging);
        DECLARE_FMI_FUNCTION(fmi2Instantiate);
        DECLARE_FMI_FUNCTION(fmi2FreeInstance);
        DECLARE_FMI_FUNCTION(fmi2SetupExperiment);
        DECLARE_FMI_FUNCTION(fmi2EnterInitializationMode);
        DECLARE_FMI_FUNCTION(fmi2ExitInitializationMode);
        DECLARE_FMI_FUNCTION(fmi2Terminate);
        DECLARE_FMI_FUNCTION(fmi2Reset);
        DECLARE_FMI_FUNCTION(fmi2GetReal);
        DECLARE_FMI_FUNCTION(fmi2GetInteger);
        DECLARE_FMI_FUNCTION(fmi2GetBoolean);
        DECLARE_FMI_FUNCTION(fmi2GetString);
        DECLARE_FMI_FUNCTION(fmi2SetReal);
        DECLARE_FMI_FUNCTION(fmi2SetInteger);
        DECLARE_FMI_FUNCTION(fmi2SetBoolean);
        DECLARE_FMI_FUNCTION(fmi2SetString);
        DECLARE_FMI_FUNCTION(fmi2GetFMUstate);
        DECLARE_FMI_FUNCTION(fmi2SetFMUstate);
        DECLARE_FMI_FUNCTION(fmi2FreeFMUstate);
        DECLARE_FMI_FUNCTION(fmi2SerializedFMUstateSize);
        DECLARE_FMI_FUNCTION(fmi2SerializeFMUstate);
        DECLARE_FMI_FUNCTION(fmi2DeSerializeFMUstate);
        DECLARE_FMI_FUNCTION(fmi2GetDirectionalDerivative);
        DECLARE_FMI_FUNCTION(fmi2SetRealInputDerivatives);
        DECLARE_FMI_FUNCTION(fmi2GetRealOutputDerivatives);
        DECLARE_FMI_FUNCTION(fmi2DoStep);
        DECLARE_FMI_FUNCTION(fmi2CancelStep);
        DECLARE_FMI_FUNCTION(fmi2GetStatus);
        DECLARE_FMI_FUNCTION(fmi2GetRealStatus);
        DECLARE_FMI_FUNCTION(fmi2GetIntegerStatus);
        DECLARE_FMI_FUNCTION(fmi2GetBooleanStatus);
        DECLARE_FMI_FUNCTION(fmi2GetStringStatus);
    } version_2;
    struct {
        DECLARE_FMI_FUNCTION(fmi3GetVersion);
        DECLARE_FMI_FUNCTION(fmi3SetDebugLogging);
        DECLARE_FMI_FUNCTION(fmi3InstantiateCoSimulation);
        DECLARE_FMI_FUNCTION(fmi3FreeInstance);
        DECLARE_FMI_FUNCTION(fmi3EnterInitializationMode);
        DECLARE_FMI_FUNCTION(fmi3ExitInitializationMode);
        DECLARE_FMI_FUNCTION(fmi3EnterEventMode);
        DECLARE_FMI_FUNCTION(fmi3Terminate);
        DECLARE_FMI_FUNCTION(fmi3Reset);
        DECLARE_FMI_FUNCTION(fmi3GetFloat32);
        DECLARE_FMI_FUNCTION(fmi3GetFloat64);
        DECLARE_FMI_FUNCTION(fmi3GetInt8);
        DECLARE_FMI_FUNCTION(fmi3GetUInt8);
        DECLARE_FMI_FUNCTION(fmi3GetInt16);        
        DECLARE_FMI_FUNCTION(fmi3GetUInt16);
        DECLARE_FMI_FUNCTION(fmi3GetInt32);
        DECLARE_FMI_FUNCTION(fmi3GetUInt32);
        DECLARE_FMI_FUNCTION(fmi3GetInt64);        
        DECLARE_FMI_FUNCTION(fmi3GetUInt64);
        DECLARE_FMI_FUNCTION(fmi3GetBoolean);
        DECLARE_FMI_FUNCTION(fmi3GetString);
        DECLARE_FMI_FUNCTION(fmi3GetBinary);
        DECLARE_FMI_FUNCTION(fmi3GetClock);
        DECLARE_FMI_FUNCTION(fmi3SetFloat32);
        DECLARE_FMI_FUNCTION(fmi3SetFloat64);
        DECLARE_FMI_FUNCTION(fmi3SetInt8);
        DECLARE_FMI_FUNCTION(fmi3SetUInt8);
        DECLARE_FMI_FUNCTION(fmi3SetInt16);        
        DECLARE_FMI_FUNCTION(fmi3SetUInt16);
        DECLARE_FMI_FUNCTION(fmi3SetInt32);
        DECLARE_FMI_FUNCTION(fmi3SetUInt32);
        DECLARE_FMI_FUNCTION(fmi3SetInt64);        
        DECLARE_FMI_FUNCTION(fmi3SetUInt64);
        DECLARE_FMI_FUNCTION(fmi3SetBoolean);
        DECLARE_FMI_FUNCTION(fmi3SetString);
        DECLARE_FMI_FUNCTION(fmi3SetBinary);
        DECLARE_FMI_FUNCTION(fmi3SetClock);
        DECLARE_FMI_FUNCTION(fmi3GetNumberOfVariableDependencies);
        DECLARE_FMI_FUNCTION(fmi3GetVariableDependencies);
        DECLARE_FMI_FUNCTION(fmi3GetFMUState);
        DECLARE_FMI_FUNCTION(fmi3SetFMUState);
        DECLARE_FMI_FUNCTION(fmi3FreeFMUState);
        DECLARE_FMI_FUNCTION(fmi3SerializedFMUStateSize);
        DECLARE_FMI_FUNCTION(fmi3SerializeFMUState);
        DECLARE_FMI_FUNCTION(fmi3DeserializeFMUState);
        DECLARE_FMI_FUNCTION(fmi3GetDirectionalDerivative);
        DECLARE_FMI_FUNCTION(fmi3GetAdjointDerivative);
        DECLARE_FMI_FUNCTION(fmi3EnterConfigurationMode);
        DECLARE_FMI_FUNCTION(fmi3ExitConfigurationMode);
        DECLARE_FMI_FUNCTION(fmi3GetIntervalDecimal);
        DECLARE_FMI_FUNCTION(fmi3GetIntervalFraction);
        DECLARE_FMI_FUNCTION(fmi3GetShiftDecimal);
        DECLARE_FMI_FUNCTION(fmi3GetShiftFraction);
        DECLARE_FMI_FUNCTION(fmi3SetIntervalDecimal);
        DECLARE_FMI_FUNCTION(fmi3SetIntervalFraction);
        DECLARE_FMI_FUNCTION(fmi3SetShiftDecimal);
        DECLARE_FMI_FUNCTION(fmi3SetShiftFraction);
        DECLARE_FMI_FUNCTION(fmi3EvaluateDiscreteStates);
        DECLARE_FMI_FUNCTION(fmi3UpdateDiscreteStates);
        DECLARE_FMI_FUNCTION(fmi3EnterStepMode);
        DECLARE_FMI_FUNCTION(fmi3GetOutputDerivatives);
        DECLARE_FMI_FUNCTION(fmi3DoStep);
    } version_3;
} fmu_interface_t;
#	undef DECLARE_FMI_FUNCTION


/*----------------------------------------------------------------------------
                           F M U _ S T A T U S _ T
----------------------------------------------------------------------------*/
typedef enum {
    FMU_OK=0,
    FMU_WARNING=1,
    FMU_ERROR=2
} fmu_status_t;


/*----------------------------------------------------------------------------
                                F M U _ T
----------------------------------------------------------------------------*/
#   define FMU_PATH_MAX_LEN 4096

typedef struct {
    char                        *name; /* based on directory */
    int                         index; /* index of this FMU in container */
	library_t                   library;
	char						resource_dir[FMU_PATH_MAX_LEN];
	char						*guid;
    int                         fmi_version;
    void                        *component; /* fmi2Component or fmi3Instance */

	fmu_interface_t				fmi_functions;

	thread_t			    	thread;
	mutex_t				    	mutex_fmu;
	mutex_t				    	mutex_container;

	fmu_io_t					fmu_io;
	
	fmu_status_t				status;
	int							cancel;
    int                         set_input;
	
    profile_t                   *profile;

	struct container_s			*container;
} fmu_t;


/*----------------------------------------------------------------------------
                            P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern fmi2Status fmu_set_inputs(fmu_t *fmu);
extern int fmu_load_from_directory(struct container_s *container, int i,
                                   const char *directory, const char *name,
                                   const char *identifier, const char *guid);
extern void fmu_unload(fmu_t *fmu);

extern fmi2Status fmuGetReal(const fmu_t *fmu, const fmi2ValueReference vr[],
                             size_t nvr, fmi2Real value[]);
extern fmi2Status fmuGetInteger(const fmu_t *fmu, const fmi2ValueReference vr[],
                                size_t nvr, fmi2Integer value[]);
extern fmi2Status fmuGetBoolean(const fmu_t *fmu, const fmi2ValueReference vr[],
                                size_t nvr, fmi2Boolean value[]);
extern fmi2Status fmuGetString(const fmu_t* fmu, const fmi2ValueReference vr[],
                               size_t nvr, fmi2String value[]);
extern fmi2Status fmuSetReal(const fmu_t *fmu, const fmi2ValueReference vr[],
                             size_t nvr, const fmi2Real value[]);
extern fmi2Status fmuSetInteger(const fmu_t *fmu, const fmi2ValueReference vr[],
                                size_t nvr, const fmi2Integer value[]);
extern fmi2Status fmuSetBoolean(const fmu_t *fmu, const fmi2ValueReference vr[],
                                size_t nvr, const fmi2Boolean value[]);
extern fmi2Status fmuSetString(const fmu_t* fmu, const fmi2ValueReference vr[],
                               size_t nvr, const fmi2String value[]);
extern fmi2Status fmuDoStep(const fmu_t *fmu, 
                            fmi2Real currentCommunicationPoint, 
                            fmi2Real communicationStepSize, 
                            fmi2Boolean noSetFMUStatePriorToCurrentPoint);
extern fmi2Status fmuEnterInitializationMode(const fmu_t *fmu);
extern fmi2Status fmuExitInitializationMode(const fmu_t *fmu);
extern fmi2Status fmuSetupExperiment(const fmu_t *fmu,
                                     fmi2Boolean toleranceDefined,
                                     fmi2Real tolerance,
                                     fmi2Real startTime,
                                     fmi2Boolean stopTimeDefined,
                                     fmi2Real stopTime);
extern fmi2Status fmuInstantiate(fmu_t *fmu, fmi2String instanceName);
extern void fmuFreeInstance(const fmu_t *fmu);
extern fmi2Status fmuTerminate(const fmu_t *fmu);
extern fmi2Status fmuReset(const fmu_t *fmu);
extern fmi2Status fmi2GetBooleanStatus(fmi2Component c, const fmi2StatusKind s, fmi2Boolean* value);
extern fmi2Status fmuGetRealStatus(const fmu_t *fmu, const fmi2StatusKind s, fmi2Real* value);
extern fmi2Status fmuGetBooleanStatus(const fmu_t *fmu, const fmi2StatusKind s, fmi2Boolean* value);

#	ifdef __cplusplus
}
#	endif
#endif
