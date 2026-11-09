#include <stdlib.h>
#include <string.h>

#include "fmi2Functions.h"
#include "fmi3Functions.h"

#include "library.h"
#include "test.h"

/*
 * Stub FMUs of FMI-LS-XCP (stub_xcp_fmi2.c, stub_xcp_fmi3.c), called directly: their journal records the
 * configuration they receive and when their service starts.
 */

#define JOURNAL_DIR     TEST_BINARY_DIR "/stub_xcp"


/* Content of the journal of the stubs, or "" when there is none. */
static const char *read_journal(void) {
    static char content[4096];
    size_t length = 0;
    FILE *file = fopen(JOURNAL_DIR "/xcp.log", "rt");

    content[0] = '\0';
    if (file) {
        length = fread(content, 1, sizeof(content) - 1, file);
        fclose(file);
    }
    content[length] = '\0';
    return content;
}


static int reset_journal(void) {
    return test_write_file(JOURNAL_DIR, "xcp.log", "");
}


int test_stub_xcp_fmi2(void) {
    library_t library = library_load(NULL, STUB_XCP_FMI2_LIBRARY);
    TEST_ASSERT(library != NULL);
    fmi2InstantiateTYPE *instantiate = (fmi2InstantiateTYPE *)library_symbol(library, "fmi2Instantiate");
    fmi2SetupExperimentTYPE *setup = (fmi2SetupExperimentTYPE *)library_symbol(library, "fmi2SetupExperiment");
    fmi2SetIntegerTYPE *set_integer = (fmi2SetIntegerTYPE *)library_symbol(library, "fmi2SetInteger");
    fmi2TerminateTYPE *terminate = (fmi2TerminateTYPE *)library_symbol(library, "fmi2Terminate");
    fmi2FreeInstanceTYPE *free_instance = (fmi2FreeInstanceTYPE *)library_symbol(library, "fmi2FreeInstance");
    TEST_ASSERT(instantiate && setup && set_integer && terminate && free_instance);
    TEST_ASSERT_EQUAL_INT(0, reset_journal());

    fmi2CallbackFunctions functions;
    memset(&functions, 0, sizeof(functions));
    fmi2Component stub = instantiate("stub", fmi2CoSimulation, "{stub-xcp-fmi2}", "file://" JOURNAL_DIR,
                                     &functions, fmi2False, fmi2False);
    TEST_ASSERT(stub != NULL);
    const fmi2ValueReference port_vr = 2;
    const fmi2Integer port = 6000;
    TEST_ASSERT_EQUAL_INT(fmi2OK, set_integer(stub, &port_vr, 1, &port));
    TEST_ASSERT_EQUAL_INT(fmi2OK, setup(stub, fmi2False, 0.0, 0.0, fmi2False, 1.0));
    TEST_ASSERT_EQUAL_INT(fmi2Error, set_integer(stub, &port_vr, 1, &port));
    TEST_ASSERT_EQUAL_INT(fmi2OK, terminate(stub));
    free_instance(stub);
    library_unload(library);

    TEST_ASSERT(strcmp(read_journal(), "set port=6000\n"
                                       "start tcp 127.0.0.1:6000 at fmi2SetupExperiment\n"
                                       "refused port in started service\n"
                                       "stop at fmi2Terminate\n") == 0);
    return 0;
}


int test_stub_xcp_fmi3(void) {
    library_t library = library_load(NULL, STUB_XCP_FMI3_LIBRARY);
    TEST_ASSERT(library != NULL);
    fmi3InstantiateCoSimulationTYPE *instantiate =
        (fmi3InstantiateCoSimulationTYPE *)library_symbol(library, "fmi3InstantiateCoSimulation");
    fmi3EnterConfigurationModeTYPE *enter = (fmi3EnterConfigurationModeTYPE *)library_symbol(library,
                                                                                    "fmi3EnterConfigurationMode");
    fmi3ExitConfigurationModeTYPE *exit_ = (fmi3ExitConfigurationModeTYPE *)library_symbol(library,
                                                                                    "fmi3ExitConfigurationMode");
    fmi3EnterInitializationModeTYPE *initialize =
        (fmi3EnterInitializationModeTYPE *)library_symbol(library, "fmi3EnterInitializationMode");
    fmi3SetUInt16TYPE *set_uint16 = (fmi3SetUInt16TYPE *)library_symbol(library, "fmi3SetUInt16");
    fmi3SetStringTYPE *set_string = (fmi3SetStringTYPE *)library_symbol(library, "fmi3SetString");
    fmi3FreeInstanceTYPE *free_instance = (fmi3FreeInstanceTYPE *)library_symbol(library, "fmi3FreeInstance");
    TEST_ASSERT(instantiate && enter && exit_ && initialize && set_uint16 && set_string && free_instance);
    TEST_ASSERT_EQUAL_INT(0, reset_journal());

    fmi3Instance stub = instantiate("stub", "{stub-xcp-fmi3}", JOURNAL_DIR, fmi3False, fmi3False, fmi3False,
                                    fmi3False, NULL, 0, NULL, NULL, NULL);
    TEST_ASSERT(stub != NULL);
    const fmi3ValueReference port_vr = 2, address_vr = 3;
    const fmi3UInt16 port = 6001;
    const fmi3String address = "0.0.0.0";
    TEST_ASSERT_EQUAL_INT(fmi3Error, set_uint16(stub, &port_vr, 1, &port, 1));
    TEST_ASSERT_EQUAL_INT(fmi3OK, enter(stub));
    TEST_ASSERT_EQUAL_INT(fmi3OK, set_uint16(stub, &port_vr, 1, &port, 1));
    TEST_ASSERT_EQUAL_INT(fmi3OK, set_string(stub, &address_vr, 1, &address, 1));
    TEST_ASSERT_EQUAL_INT(fmi3OK, exit_(stub));
    TEST_ASSERT_EQUAL_INT(fmi3OK, initialize(stub, fmi3False, 0.0, 0.0, fmi3False, 1.0));
    free_instance(stub);

    /* Without Configuration Mode: the service starts with its default configuration. */
    stub = instantiate("stub", "{stub-xcp-fmi3}", JOURNAL_DIR, fmi3False, fmi3False, fmi3False, fmi3False, NULL, 0,
                       NULL, NULL, NULL);
    TEST_ASSERT(stub != NULL);
    TEST_ASSERT_EQUAL_INT(fmi3OK, initialize(stub, fmi3False, 0.0, 0.0, fmi3False, 1.0));
    free_instance(stub);
    library_unload(library);

    TEST_ASSERT(strcmp(read_journal(), "refused port in Instantiated\n"
                                       "set port=6001\n"
                                       "set address=0.0.0.0\n"
                                       "start tcp 0.0.0.0:6001 at fmi3ExitConfigurationMode\n"
                                       "start tcp 127.0.0.1:5555 at fmi3EnterInitializationMode\n") == 0);
    return 0;
}
