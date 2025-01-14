/*
 * 2022-2024 Nicolas.LAURENT@Renault.com
 *
 * DLL/SO loading functions.
 */

#ifdef WIN32
#	include <windows.h>
#	include <imagehlp.h>
#else
#	include <dlfcn.h>
#   include <unistd.h> 
#endif

#include "hash.h"
#include "library.h"
#include "logger.h"


#ifdef WIN32
typedef enum {
    LIBRARY_DLL_NOT_FOUND,
    LIBRARY_DLL_MISSING_DEPENDENCIES,
    LIBRARY_DLL_OK
} libray_status_t;

static libray_status_t* libray_analyse(hash_t* dll_db, const char* filename);
#endif

void *library_symbol(library_t library, const char *symbol_name) {
#ifdef WIN32
	return (void *)GetProcAddress(library, symbol_name);
#else
	return dlsym(library, symbol_name);
#endif
}


static void library_load_error(const char* library_filename) {
#ifdef WIN32
	hash_t* dll_db = hash_new();
    libray_analyse(dll_db, library_filename);
	hash_free(dll_db);
#else
	logger(fmi2Error, "dlopen Error: %s", dlerror());
#endif
	logger(fmi2Error, "Cannot load `%s'", library_filename);

	return; /* Never reached */
}


library_t library_load(const char* library_filename) {
	library_t handle;
#ifdef WIN32
	handle = LoadLibraryA(library_filename);
#else
	handle = dlopen(library_filename, RTLD_LAZY);	/* RTLD_LOCAL can lead to failure */
#endif
    if (!handle)
        library_load_error(library_filename);

	return handle;
}


void library_unload(library_t library) {
	if (library) {
#ifdef WIN32
		FreeLibrary(library);
#else
		dlclose(library);
#endif
	}
}

/*----------------------------------------------------------------------------
                  D E P E N D E N C I E S   A N A L Y S I S
----------------------------------------------------------------------------*/
/*
 * see: https://stackoverflow.com/questions/597260/how-to-determine-a-windows-executables-dll-dependencies-programmatically
 */
#ifdef WIN32
static PIMAGE_SECTION_HEADER GetEnclosingSectionHeader(DWORD rva, PIMAGE_NT_HEADERS pNTHeader) {
    PIMAGE_SECTION_HEADER section = IMAGE_FIRST_SECTION(pNTHeader);
    unsigned i;

    for (i = 0; i < pNTHeader->FileHeader.NumberOfSections; i++, section++)
    {
        // This 3 line idiocy is because Watcom's linker actually sets the
        // Misc.VirtualSize field to 0.  (!!! - Retards....!!!)
        DWORD size = section->Misc.VirtualSize;
        if (0 == size)
            size = section->SizeOfRawData;

        // Is the RVA within this section?
        if ((rva >= section->VirtualAddress) &&
            (rva < (section->VirtualAddress + size)))
            return section;
    }

    return 0;
}


static LPVOID GetPtrFromRVA(DWORD rva, PIMAGE_NT_HEADERS pNTHeader, PBYTE imageBase) {
    PIMAGE_SECTION_HEADER pSectionHdr;
    INT delta;

    pSectionHdr = GetEnclosingSectionHeader(rva, pNTHeader);
    if (!pSectionHdr)
        return 0;

    delta = (INT)(pSectionHdr->VirtualAddress - pSectionHdr->PointerToRawData);
    return (PVOID)(imageBase + rva - delta);
}


static libray_status_t* libray_try_load(const char* filename) {
    libray_status_t* status = malloc(sizeof(*status));

    HINSTANCE handle = LoadLibraryExA(filename, NULL, DONT_RESOLVE_DLL_REFERENCES);
    if (handle) {
        FreeLibrary(handle);

        handle = LoadLibraryA(filename);
        if (handle) {
            FreeLibrary(handle);
            *status = LIBRARY_DLL_OK;
        }
        else {
            *status = LIBRARY_DLL_MISSING_DEPENDENCIES;
        }
    }
    else {
        *status = LIBRARY_DLL_NOT_FOUND;
    }
    return status;
}


static libray_print_status(const char* filename, libray_status_t* status) {
    switch (*status) {
    case LIBRARY_DLL_OK:
        logger(fmi2Warning, "DLL `%s' is found.", filename);
        break;
    case LIBRARY_DLL_NOT_FOUND:
        logger(fmi2Warning, "DLL `%s' is not found.", filename);
        break;
    case LIBRARY_DLL_MISSING_DEPENDENCIES:
        logger(fmi2Warning, "DLL `%s' has missing dependencies.", filename);
        break;
    }
}


static void libray_analyse_deeply(hash_t* dll_db, const char* filename) {
    PLOADED_IMAGE image = ImageLoad(filename, NULL);
    if (!image) {
        logger(fmi2Error, "Cannot ImageLoad(%s)", filename);
    }
    else {
        if (image->FileHeader->OptionalHeader.NumberOfRvaAndSizes >= 2) {
            PIMAGE_IMPORT_DESCRIPTOR importDesc =
                (PIMAGE_IMPORT_DESCRIPTOR)GetPtrFromRVA(
                    image->FileHeader->OptionalHeader.DataDirectory[1].VirtualAddress,
                    image->FileHeader, image->MappedAddress);
            while (1) {
                // See if we've reached an empty IMAGE_IMPORT_DESCRIPTOR
                if ((importDesc->TimeDateStamp == 0) && (importDesc->Name == 0))
                    break;
                const char* dll_filename = GetPtrFromRVA(importDesc->Name, image->FileHeader, image->MappedAddress);
                libray_analyse(dll_db, dll_filename);
                importDesc++;
            }
        }
        ImageUnload(image);
    }
    return;
}


static libray_status_t* libray_analyse_really(hash_t* dll_db, const char* filename) {
    libray_status_t* status = libray_try_load(filename);
    hash_set_value(dll_db, strdup(filename), status);
    if (*status == LIBRARY_DLL_MISSING_DEPENDENCIES)
        libray_analyse_deeply(dll_db, filename);

    libray_print_status(filename, status);

    return status;
}


static libray_status_t* libray_analyse(hash_t* dll_db, const char* filename) {
    libray_status_t* status;

    status = hash_get_value(dll_db, filename);
    if (!status)
        status = libray_analyse_really(dll_db, filename);

    return status;
}
#endif /* WIN32 */
