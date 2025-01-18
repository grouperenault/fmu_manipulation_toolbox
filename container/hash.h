#ifndef HASH_T
#define HASH_T

#	ifdef __cplusplus
extern "C" {
#	endif


/*----------------------------------------------------------------------------
                           H A S H _ E N T R Y _ T
----------------------------------------------------------------------------*/

typedef struct hash_entry_s {
	char 				*key;
	void 				*value;
	struct hash_entry_s	*next;
} hash_entry_t;


/*----------------------------------------------------------------------------
                                  H A S H _ T
----------------------------------------------------------------------------*/

typedef struct {
	unsigned long		size;
	unsigned long		nb;
	hash_entry_t		**entry;
} hash_t;


/*----------------------------------------------------------------------------
				      H A S H _ LOOP _ F U N C T I O N _ T
----------------------------------------------------------------------------*/

typedef void (*hash_loop_function_t)(const hash_entry_t *, void *data);


/*----------------------------------------------------------------------------
                             P R O T O T Y P E S
----------------------------------------------------------------------------*/

extern void hash_free(hash_t *hash);
extern hash_t *hash_new(void);
extern unsigned long hash_entries_number(const hash_t *hash);
extern void hash_set_value(hash_t *hash, char *key, void *value);
extern void *hash_get_value(const hash_t *hash, const char *key);
extern hash_entry_t *hash_get_entry(const hash_t* hash, const char* key);
extern hash_entry_t* hash_get_entry_closest(const hash_t* hash, const char* key);
extern void hash_loop(const hash_t* hash, hash_loop_function_t function, void *data);

#	ifdef __cplusplus
}
#	endif
#endif
