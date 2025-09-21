/*    ___                                               __   __
 *  .'  _|.--------.--.--.  .----.-----.--------.-----.|  |_|__|.-----.-----.
 *  |   _||        |  |  |  |   _|  -__|        |  _  ||   _|  ||     |  _  |
 *  |__|  |__|__|__|_____|  |__| |_____|__|__|__|_____||____|__||__|__|___  |
 *  Copyright 2023 Renault SAS                                        |_____|
 *  The remoting code is written by Nicolas.LAURENT@Renault.com.
 *  This code is released under the 2-Clause BSD license.
 */

#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#ifdef WIN32
#   include <windows.h>
#   pragma warning(disable: 4996) /* Stop complaining about strdup() */
#else
#   include <dlfcn.h>
#endif
#include "process.h"
#include "server.h"

//#define SERVER_DEBUG 1
#ifdef SERVER_DEBUG
#   include <stdio.h>
#   define SERVER_LOG(message, ...) do { printf("[SERVER] " message, ##__VA_ARGS__); fflush(stdout); } while(0)
#else
#   define SERVER_LOG(message, ...)
#endif

/*----------------------------------------------------------------------------
                                 L O G G E R
----------------------------------------------------------------------------*/

#define _LOG(server, ...)           server_logger(server, server->instance_name, ##__VA_ARGS__)
#define LOG_DEBUG(server, ...)      _LOG(server, fmi2OK, "[SERVER]", ##__VA_ARGS__)
#define LOG_WARNING(server, ...)    _LOG(server, fmi2Warning, "SERVER", ##__VA_ARGS__)
#define LOG_ERROR(server, ...)      _LOG(server, fmi2Error, "SERVER]", ##__VA_ARGS__)


static void server_logger(fmi2ComponentEnvironment componentEnvironment,
    fmi2String instanceName,
    fmi2Status status,
    fmi2String category,
    fmi2String message,
    ...) {
    server_t *server = (server_t*)componentEnvironment;
    va_list params;

    if (server) {
        char *logmessage = server->communication->shm->message;
        const size_t offset = strlen(message);
        

        va_start(params, message);
        vsnprintf(logmessage + offset, COMMUNICATION_MESSAGE_SIZE - offset, message, params);
        va_end(params);

        strncat(logmessage + offset, "\n", COMMUNICATION_MESSAGE_SIZE - offset - strlen(logmessage + offset));
        logmessage[COMMUNICATION_MESSAGE_SIZE-1] = '\0'; /* paranoia */
        

        SERVER_LOG("LOG: %s\n", logmessage + offset);
    } else {
        /* Early log message sent buggy FMU */
        printf("Buggy FMU message: ");
        va_start(params, message);
        vprintf(message, params);
        va_end(params);
        printf("\n");
    }
    return;
}


/*----------------------------------------------------------------------------
                            L O A D I N G   D L L
----------------------------------------------------------------------------*/

static void *library_symbol(library_t library, const char* symbol_name) {
    if (library)
#ifdef WIN32
        return (void *)GetProcAddress(library, symbol_name);
#else
        return dlsym(library, symbol_name);
#endif
    else
        return NULL;
}


static library_t library_load(const char* library_filename) {
    library_t handle;
    SERVER_LOG("Loading Dynamic Library `%s'\n", library_filename);
#ifdef WIN32
    handle = LoadLibraryA(library_filename);
#else
    handle = dlopen(library_filename, RTLD_LAZY | RTLD_LOCAL);
#endif

#ifdef SERVER_DEBUG
    if (!handle) 
        SERVER_LOG("Cannot load `%s'\n", library_filename);
    else
        SERVER_LOG("Loaded.\n");
#endif

    return handle;
}


static void library_unload(library_t library) {
    if (library) {
#ifdef WIN32
        FreeLibrary(library);
#else
        dlclose(library);
#endif
    }
}


static void map_entries(fmu_entries_t* entries, library_t library) {
#	define MAP(x) entries->x = (x ## TYPE*)library_symbol(library, #x); \
	SERVER_LOG("function %-30s: %s\n", "`" #x "'", (entries->x)?"found":"not implemented")

    MAP(fmi2GetTypesPlatform);  /* 0 */
    MAP(fmi2GetVersion);
    MAP(fmi2SetDebugLogging);
    MAP(fmi2Instantiate);
    MAP(fmi2FreeInstance);
    MAP(fmi2SetupExperiment);
    MAP(fmi2EnterInitializationMode);
    MAP(fmi2ExitInitializationMode);
    MAP(fmi2Terminate);
    MAP(fmi2Reset);
    MAP(fmi2GetReal); /* 10 */
    MAP(fmi2GetInteger);
    MAP(fmi2GetBoolean);
    MAP(fmi2GetString);
    MAP(fmi2SetReal);
    MAP(fmi2SetInteger);
    MAP(fmi2SetBoolean);
    MAP(fmi2SetString);
    MAP(fmi2GetFMUstate);
    MAP(fmi2SetFMUstate);
    MAP(fmi2FreeFMUstate); /* 20 */
    MAP(fmi2SerializedFMUstateSize);
    MAP(fmi2SerializeFMUstate);
    MAP(fmi2DeSerializeFMUstate);
    MAP(fmi2GetDirectionalDerivative);

    MAP(fmi2EnterEventMode);
    MAP(fmi2NewDiscreteStates);
    MAP(fmi2EnterContinuousTimeMode);
    MAP(fmi2CompletedIntegratorStep);
    MAP(fmi2SetTime);
    MAP(fmi2SetContinuousStates); /* 30 */
    MAP(fmi2GetDerivatives);
    MAP(fmi2GetEventIndicators);
    MAP(fmi2GetContinuousStates);
    MAP(fmi2GetNominalsOfContinuousStates);

    MAP(fmi2SetRealInputDerivatives);
    MAP(fmi2GetRealOutputDerivatives);
    MAP(fmi2DoStep);
    MAP(fmi2CancelStep);
    MAP(fmi2GetStatus);
    MAP(fmi2GetRealStatus); /* 40 */
    MAP(fmi2GetIntegerStatus);
    MAP(fmi2GetBooleanStatus);
    MAP(fmi2GetStringStatus);
#undef MAP
    return;
}


/*----------------------------------------------------------------------------
                                S E R V E R
----------------------------------------------------------------------------*/


static void server_free(server_t* server) {
    if (server->communication)
        communication_free(server->communication);
    library_unload(server->library);
#ifdef WIN32
    CloseHandle(server->parent_handle);
#endif
    free(server->instance_name);
    free(server);

    return;
}
    

static server_t* server_new(const char *library_filename, unsigned long ppid, const char *secret) {
    server_t* server;
    server = malloc(sizeof(*server));
    if (!server)
        return NULL;
    server->instance_name = NULL;
    server->is_debug = 0;
#ifdef WIN32
    server->parent_handle = OpenProcess(SYNCHRONIZE, FALSE, ppid);
#else
    server->parent_handle = ppid;
#endif
    server->library_filename = library_filename;
    server->library = NULL; /* Library will be loaded on demand */
    server->functions.logger = server_logger;
    server->functions.allocateMemory = calloc;
    server->functions.freeMemory = free;
    server->functions.stepFinished = NULL;
    server->functions.componentEnvironment = server;
    strncpy(server->shared_key, secret, sizeof(server->shared_key));
    SERVER_LOG("Server UUID for IPC: '%s'\n", server->shared_key);

    server->communication = communication_new(server->shared_key, 0, 0, 0, COMMUNICATION_SERVER);
    communication_data_initialize(&server->data, server->communication);

    /* At this point Client and Server are Synchronized */


    return server;
}


/*-----------------------------------------------------------------------------
                             M A I N   L O O P
-----------------------------------------------------------------------------*/

static int is_parent_still_alive(const server_t *server) {
    return process_is_alive(server->parent_handle);
}

static fmi2Status do_step(const server_t *server) {
    fmi2Real currentCommunicationPoint = server->communication->shm->values[0];
    fmi2Real communicationStepSize = server->communication->shm->values[1];
    fmi2Boolean noSetFMUStatePriorToCurrentPoint = server->communication->shm->values[2];
    fmi2Status status;

    unsigned long nb_reals = 0;
    for(unsigned long i = 0; i < server->communication->nb_reals; i += 1) {
        if (server->data.reals.changed[i]) {
            server->update.reals.vr[nb_reals] = server->data.reals.vr[i];
            server->update.reals.value[nb_reals] = server->data.reals.value[i];
            nb_reals += 1;
        } 
    }

    unsigned long nb_integers = 0;
    for(unsigned long i = 0; i < server->communication->nb_integers; i += 1) {
        if (server->data.integers.changed[i]) {
            server->update.integers.vr[nb_integers] = server->data.integers.vr[i];
            server->update.integers.value[nb_integers] = server->data.integers.value[i];
            nb_integers += 1;
        } 
    }

    unsigned long nb_booleans = 0;
        for(unsigned long i = 0; i < server->communication->nb_booleans; i += 1) {
        if (server->data.booleans.changed[i]) {
            server->update.booleans.vr[nb_booleans] = server->data.booleans.vr[i];
            server->update.booleans.value[nb_booleans] = server->data.booleans.value[i];
            nb_booleans += 1;
        } 
    }
    
    server->entries.fmi2SetReal(server->component, server->update.reals.vr, nb_reals, server->update.reals.value);
    server->entries.fmi2SetInteger(server->component, server->update.integers.vr, nb_integers, server->update.integers.value);
    server->entries.fmi2SetBoolean(server->component, server->update.booleans.vr, nb_booleans, server->update.booleans.value);

    status = server->entries.fmi2DoStep(
        server->component,
        currentCommunicationPoint,
        communicationStepSize,
        noSetFMUStatePriorToCurrentPoint);

    server->entries.fmi2GetReal(server->component, server->data.reals.vr, server->communication->nb_reals, server->data.reals.value);
    server->entries.fmi2SetInteger(server->component, server->data.integers.vr, server->communication->nb_integers, server->data.integers.value);
    server->entries.fmi2SetBoolean(server->component, server->data.booleans.vr, server->communication->nb_booleans, server->data.booleans.value);
    
    return status;
}


int main(int argc, char* argv[]) {
    SERVER_LOG("STARING...\n");
    if (argc != 4) {
        fprintf(stderr, "Usage: server <parent_process_id> <secret> <library_path>\n");
        return 1;
    }

    SERVER_LOG("Initializing...\n");
    server_t* server = server_new(argv[3], strtoul(argv[1], NULL, 10), argv[2]);
    if (!server) {
        SERVER_LOG("Initialize server. Exit.\n");
        return -1;
    }


    communication_shm_t *fmu = server->communication->shm;

    communication_server_ready(server->communication);
    SERVER_LOG("server_ready = %d\n", server->communication->data->server_ready);

    int wait_for_function = 1;
    while (wait_for_function) {

        /*
         * Watch dog !
         */
        SERVER_LOG("WAIT\n");
        while (communication_timedwaitfor_client(server->communication,COMMUNICATION_TIMEOUT_DEFAULT)) {
            if (!is_parent_still_alive(server)) {
                SERVER_LOG("Parent process died.\n");
                wait_for_function = 0;
                break;
            }
        }
        if (!wait_for_function)
            break;

        /*
         * Decode & execute function
         */


        rpc_function_t function = fmu->function;
        SERVER_LOG("RPC: %s | execute\n", remote_function_name(function));
        fmu->status = -1; /* means that real function is not (yet?) called */

     
        switch (function) {
        case RPC_fmi2Instantiate:
            server->instance_name = strdup(fmu->instance_name);
            server->is_debug = fmi2False;
            server->library = library_load(server->library_filename);
            if (!server->library)
                LOG_ERROR(server, "Cannot open DLL object '%s'. ", server->library_filename);
            map_entries(&server->entries, server->library);
            server->component = NULL;

            if (server->entries.fmi2Instantiate)
                server->component = server->entries.fmi2Instantiate(
                    server->communication->shm->instance_name,
                    fmi2CoSimulation,
                    server->communication->shm->token,
                    server->communication->shm->resource_directory,
                    &server->functions,
                    fmi2False,
                    fmi2False);
            
            if (!server->component) {
                LOG_ERROR(server, "Cannot instanciate FMU.");
                fmu->status = fmi2Error;
            } else
                fmu->status = fmi2OK;
            break;

        case RPC_fmi2FreeInstance:
            if (server->entries.fmi2FreeInstance) {
                server->entries.fmi2FreeInstance(server->component);
                fmu->status = fmi2OK;
            } else {
                LOG_ERROR(server, "Function 'fmi2FreeInstance' not reachable.");
                fmu->status = fmi2Error;
            }
            server->component = NULL;
            library_unload(server->library);
            server->library = NULL;

            wait_for_function = 0;
            break;

        case RPC_fmi2SetupExperiment:
            if (server->entries.fmi2SetupExperiment) {
                fmi2Boolean toleranceDefined = server->communication->shm->values[0];
                fmi2Real tolerance = server->communication->shm->values[1];
                fmi2Real startTime = server->communication->shm->values[2];
                fmi2Boolean stopTimeDefined = server->communication->shm->values[3];
                fmi2Real stopTime = server->communication->shm->values[4];

                fmu->status = server->entries.fmi2SetupExperiment(
                    server->component,
                    toleranceDefined,
                    tolerance,
                    startTime,
                    stopTimeDefined,
                    stopTime);
            }
            break;

        case RPC_fmi2EnterInitializationMode:
            if (server->entries.fmi2EnterInitializationMode)
               fmu->status = server->entries.fmi2EnterInitializationMode(server->component);
            break;

        case RPC_fmi2ExitInitializationMode:
            if (server->entries.fmi2ExitInitializationMode)
                fmu->status = server->entries.fmi2ExitInitializationMode(server->component);
            break;

        case RPC_fmi2Terminate:
            if (server->entries.fmi2Terminate)
                fmu->status = server->entries.fmi2Terminate(server->component);
            break;

        case RPC_fmi2Reset:
            if (server->entries.fmi2Reset)
                fmu->status = server->entries.fmi2Reset(server->component);
            break;

        case RPC_fmi2DoStep:
            fmu->status = do_step(server);
            break;
        }

        /*
         * Acknoledge the client side !
         */
        if (fmu->status < 0) {
            LOG_ERROR(server, "Function '%d' unreachable.", function);
            fmu->status = fmi2Error;
        }
        SERVER_LOG("RPC: %d | processed.\n", function);
        communication_server_ready(server->communication);
    }

    /*
     * End of loop
     */
    server_free(server);
    SERVER_LOG("Exit.\n");


    return 0;
}
