#include <string.h>

#include "fmi2Functions.h"
#include "fmi3Functions.h"

#include "container.h"
#include "test.h"

/*
 * Configuration of the embedded FMUs of FMI-LS-XCP by the container (fixtures xcp_fmi2 and xcp_fmi3, stub FMUs of
 * stub_xcp_fmi<2|3>.c): the journal of the stub shows what it receives and when its XCP service starts.
 *   - FMI 3.0: structural parameters, set in Configuration Mode only (start values <RESET>=2, then the values set on
 *     the container), with or without the Configuration Mode of the container;
 *   - FMI 2.0: parameters, set before fmi2SetupExperiment where the service starts.
 */

#define PORT_VR_FMI3        83886080    /* uinteger16 of the container, linked to XCP.TCP.Port */
#define PORT_VR_FMI2        100663298   /* integer32 of the container, linked to XCP.TCP.Port */


static const char *read_journal(const char *fixture) {
    static char content[4096];
    char path[4096];
    size_t length = 0;

    snprintf(path, sizeof(path), "%s/%s/00/resources/xcp.log", TEST_FIXTURES_DIR, fixture);
    FILE *file = fopen(path, "rt");
    if (file) {
        length = fread(content, 1, sizeof(content) - 1, file);
        fclose(file);
    }
    content[length] = '\0';
    return content;
}


static int reset_journal(const char *fixture) {
    char directory[4096];

    snprintf(directory, sizeof(directory), "%s/%s/00/resources", TEST_FIXTURES_DIR, fixture);
    return test_write_file(directory, "xcp.log", "");
}


static fmi3Instance instantiate_fmi3(void) {
    char location[4096];

    snprintf(location, sizeof(location), "%s/xcp_fmi3", TEST_FIXTURES_DIR);
    return fmi3InstantiateCoSimulation("xcp", "{uuid}", location, fmi3False, fmi3False, fmi3False, fmi3False, NULL, 0,
                                       NULL, NULL, NULL);
}


/* The importer configures the container: its values prevail over the start values. */
int test_xcp_configuration_mode(void) {
    TEST_ASSERT_EQUAL_INT(0, reset_journal("xcp_fmi3"));
    fmi3Instance container = instantiate_fmi3();
    TEST_ASSERT(container != NULL);

    const fmi3ValueReference vr = PORT_VR_FMI3;
    const fmi3UInt16 port = 7000;
    TEST_ASSERT_EQUAL_INT(fmi3OK, fmi3EnterConfigurationMode(container));
    TEST_ASSERT_EQUAL_INT(fmi3OK, fmi3SetUInt16(container, &vr, 1, &port, 1));
    TEST_ASSERT_EQUAL_INT(fmi3OK, fmi3ExitConfigurationMode(container));
    TEST_ASSERT_EQUAL_INT(fmi3OK, fmi3EnterInitializationMode(container, fmi3False, 0.0, 0.0, fmi3False, 1.0));
    fmi3FreeInstance(container);

    TEST_ASSERT(strcmp(read_journal("xcp_fmi3"), "set port=6000\n"
                                                 "set address=0.0.0.0\n"
                                                 "set port=7000\n"
                                                 "start tcp 0.0.0.0:7000 at fmi3ExitConfigurationMode\n") == 0);
    return 0;
}


/* The importer does not use the Configuration Mode: the container configures the FMU before its initialization,
   with the value set on the container meanwhile. */
int test_xcp_without_configuration_mode(void) {
    TEST_ASSERT_EQUAL_INT(0, reset_journal("xcp_fmi3"));
    fmi3Instance container = instantiate_fmi3();
    TEST_ASSERT(container != NULL);

    const fmi3ValueReference vr = PORT_VR_FMI3;
    const fmi3UInt16 port = 7001;
    TEST_ASSERT_EQUAL_INT(fmi3OK, fmi3SetUInt16(container, &vr, 1, &port, 1));   /* kept until the configuration */
    TEST_ASSERT(strcmp(read_journal("xcp_fmi3"), "") == 0);
    TEST_ASSERT_EQUAL_INT(fmi3OK, fmi3EnterInitializationMode(container, fmi3False, 0.0, 0.0, fmi3False, 1.0));
    fmi3FreeInstance(container);

    TEST_ASSERT(strcmp(read_journal("xcp_fmi3"), "set port=6000\n"
                                                 "set address=0.0.0.0\n"
                                                 "set port=7001\n"
                                                 "start tcp 0.0.0.0:7001 at fmi3ExitConfigurationMode\n") == 0);
    return 0;
}


/* FMI 2.0: the start values, then the values set on the container, before fmi2SetupExperiment. */
int test_xcp_fmi2_before_setup_experiment(void) {
    char location[4096];
    fmi2CallbackFunctions functions;

    TEST_ASSERT_EQUAL_INT(0, reset_journal("xcp_fmi2"));
    snprintf(location, sizeof(location), "file://%s/xcp_fmi2", TEST_FIXTURES_DIR);
    memset(&functions, 0, sizeof(functions));
    fmi2Component container = fmi2Instantiate("xcp", fmi2CoSimulation, "{uuid}", location, &functions, fmi2False,
                                              fmi2False);
    TEST_ASSERT(container != NULL);

    const fmi2ValueReference vr = PORT_VR_FMI2;
    const fmi2Integer port = 7002;
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2SetInteger(container, &vr, 1, &port));
    TEST_ASSERT_EQUAL_INT(fmi2OK, fmi2SetupExperiment(container, fmi2False, 0.0, 0.0, fmi2False, 1.0));
    fmi2FreeInstance(container);

    TEST_ASSERT(strcmp(read_journal("xcp_fmi2"), "set port=7002\n"
                                                 "set port=6002\n"
                                                 "set port=7002\n"
                                                 "start tcp 127.0.0.1:7002 at fmi2SetupExperiment\n") == 0);
    return 0;
}
