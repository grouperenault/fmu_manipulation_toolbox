#include <stdio.h>

#include "fmi2TypesPlatform.h"
#include "fmi3PlatformTypes.h"
#include "fmi3FunctionTypes.h"

/*
 * Used at configuration time to ensure compatiblity between FMI 2.0 and 3.0 data types. 
 */

int main(int argc, char **argv) {

    printf("Check REALS\n");
    printf(" > sizeof(double)                 = %lu\n", sizeof(double));
    printf(" > sizeof(fmi2Real)               = %lu\n", sizeof(fmi2Real));
    printf(" > sizeof(fmi3Float64)            = %lu\n", sizeof(fmi3Float64));
    printf(" > sizeof(fmi3Float32)            = %lu\n", sizeof(fmi3Float32));

    if ((sizeof(fmi2Real) != sizeof(double)) || (sizeof(fmi3Float64) != sizeof(double))) {
        printf("*** Cannort align Reals class storage.");
        return -1;
    }   

    printf("Check INTEGERS\n");
    printf(" > sizeof(int_32_t)              = %lu\n", sizeof(int32_t));
    printf(" > sizeof(fmi2Integer)           = %lu\n", sizeof(fmi2Integer));
    printf(" > sizeof(fmi3Int32)             = %lu\n", sizeof(fmi3Int32));
    if ((sizeof(fmi2Integer) != sizeof(int32_t)) || (sizeof(fmi3Int32) != sizeof(int32_t))) {
        printf("*** Cannort align Integers class storage.");
        return -1;
    }

    printf("Check BOOLEANS\n");
    printf(" > sizeof(int)                   = %lu\n", sizeof(int));
    printf(" > sizeof(fmi2Boolean)           = %lu\n", sizeof(fmi2Boolean));
    printf(" > sizeof(fmi3Boolean)           = %lu\n", sizeof(fmi3Boolean));
    if (sizeof(fmi3Boolean) > sizeof(fmi2Boolean)) {
        printf("*** Cannort align Booleans class storage.");
        return -1;
    }

    printf("Check ENUM\n");
    printf(" > sizeof(int)                   = %lu\n", sizeof(int));
    printf(" > sizeof(fmi3IntervalQualifier) = %lu\n", sizeof(fmi3IntervalQualifier));
    if (sizeof(int) != sizeof(fmi3IntervalQualifier)) {
        printf("*** Cannot map Enum to int.");
        return -1;
    }

    return 0;

}
