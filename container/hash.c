#include <stdlib.h>
#include <string.h>

#include "hash.h"


#define HASH_DEFAULT_SIZE 201    /* prime number far from power of 2 numbers */
#define HASH_COLLISION_MAX 100

/*
 * hash table utilities. Used by library.c.
 */
static unsigned long hash_function(const char *key, unsigned long hash_size) {
	register unsigned long int	val=0;

	while(*key != '\0')
	{
		register unsigned long int tmp;
		val = (val << 4) + (*key);
		tmp = val & 0xf0000000;
		if (tmp)
		{
			val ^= tmp >> 24;
			val ^= tmp;
		}

		key++;
	}

	return(val % hash_size);
}


hash_entry_t* hash_get_entry(const hash_t* hash, const char* key) {
	unsigned long index = hash_function(key, hash->size);

	for (hash_entry_t* entry = hash->entry[index]; entry; entry = entry->next)
		if (strcmp(entry->key, key) == 0)
			return entry;

	return NULL;
}


void *hash_get_value(const hash_t *hash, const char *key) {
	hash_entry_t *entry = hash_get_entry(hash, key);
	if (entry)
		return entry->value;
	
	return NULL;
}


static hash_entry_t *hash_entry_new(char *key, void *value) {
	hash_entry_t *entry;

	entry = malloc(sizeof(*entry));
	entry->key   = key;
	entry->value = value;
	entry->next  = NULL;

	return entry;
}


static void hash_entry_free(hash_entry_t *entry) {
	free(entry->key);
	free(entry->value);
	free(entry);
}


unsigned long hash_entries_number(const hash_t *hash) {
    return hash->nb;
}


static void hash_reorder(hash_t *hash)
{
	unsigned long i;
	const unsigned long N = hash->size;
	const unsigned long N2 = N * 2 + 1; /* pour avoir un nombre impaire */
	hash_entry_t **new_entry;

	/* Initialisation de la nouvelle table */
	new_entry = malloc(sizeof(*new_entry) * N2);
	for (i = 0; i<N2; i++)
		new_entry[i] = NULL;

	/* insertion de l'ancienne dans la nouvelle */
	for (i = 0; i<N; i++)
	{
		hash_entry_t *e;
		hash_entry_t *next;

		for (e = hash->entry[i]; e; e = next)
		{
			unsigned long indice;
			next = e->next;

			indice = hash_function(e->key, N2);
			e->next = new_entry[indice];
			new_entry[indice] = e;
		}
	}

	/* lib�ration de l'ancienne et M-�-J */
	free(hash->entry);
	hash->entry = new_entry;
	hash->size = N2;

	return;
}


void hash_set_value(hash_t *hash, char *key, void *value) {
	hash_entry_t *entry = hash_get_entry(hash, key);
	if (entry) {
		free(entry->value);
		entry->value = value;
	} else {
		unsigned collision = 0;
		unsigned long index = hash_function(key, hash->size);
		hash_entry_t *current = hash->entry[index];
		hash->entry[index] = hash_entry_new(key, value);
		hash->entry[index]->next = current;
		hash->nb += 1;

		/* calculate collision */
		for (entry = hash->entry[index]; entry->next; entry = entry->next)
			collision += 1;
		if (collision >= HASH_COLLISION_MAX)
			hash_reorder(hash);
	}
}


hash_t *hash_new(void) {
	hash_t *hash;

	hash = malloc(sizeof(*hash));
	hash->size  = HASH_DEFAULT_SIZE;
	hash->nb    = 0;
	hash->entry = malloc(sizeof(*hash->entry) * hash->size);
	for(unsigned long i = 0; i < hash->size; i += 1)
		hash->entry[i] = NULL;

	return hash;
}


void hash_free(hash_t *hash) {
	for(unsigned long i = 0; i < hash->size; i += 1) {
		hash_entry_t *entry = hash->entry[i];
		while(entry) {
			hash_entry_t *next = entry->next;
			hash_entry_free(entry);
			entry =next;
		}
	}
	free(hash->entry);
	free(hash);
}
