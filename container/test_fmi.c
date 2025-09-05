#include <stdio.h>

#include "fmi2TypesPlatform.h"
#include "fmi3PlatformTypes.h"

int main(int argc, char **argv) {

    printf("Check REALS\n");
    printf("sizeof(double)      = %d\n", sizeof(double));
    printf("sizeof(fmi2Real)    = %d\n", sizeof(fmi2Real));
    printf("sizeof(fmi3Float64) = %d\n", sizeof(fmi3Float64));
    printf("sizeof(fmi3Float32) = %d\n", sizeof(fmi3Float32));

    if ((sizeof(fmi2Real) != sizeof(double)) || (sizeof(fmi3Float64) != sizeof(double))) {
        printf("*** Cannort align Reals class storage.");
        return -1;
    }   

    printf("Check INTEGERS\n");
    printf("sizeof(int_32_t)    = %d\n", sizeof(int32_t));
    printf("sizeof(fmi2Integer) = %d\n", sizeof(fmi2Integer));
    printf("sizeof(fmi3Int32)   = %d\n", sizeof(fmi3Int32));
    if ((sizeof(fmi2Integer) != sizeof(int32_t)) || (sizeof(fmi3Int32) != sizeof(int32_t))) {
        printf("*** Cannort align Integers class storage.");
        return -1;
    }

    printf("Check BOOLEANS\n");
    printf("sizeof(int)         = %d\n", sizeof(int));
    printf("sizeof(fmi2Boolean) = %d\n", sizeof(fmi2Boolean));
    printf("sizeof(fmi3Boolean) = %d\n", sizeof(fmi3Boolean));
    if (sizeof(fmi3Boolean) > sizeof(fmi2Boolean)) {
        printf("*** Cannort align Booleans class storage.");
        return -1;
    }
    return 0;

}
