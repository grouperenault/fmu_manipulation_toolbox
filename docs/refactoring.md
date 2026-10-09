# Refactoring : passage de `modelDescription.xml` à ElementTree

**Date** : 9 octobre 2026 — **Branche** : `features/mcp` — **Périmètre** : `operations.py`, `container.py`, `split.py`, `checker.py`

---

## 1. Pourquoi

Le code lit et écrit `modelDescription.xml` à la main. Il y a deux mécanismes :

- **en lecture/réécriture** : `Manipulation` (`operations.py`) parse avec `xml.parsers.expat`, élément par élément, puis
  **régénère** le XML avec des `print()`. Chaque `FMU.apply_operation()` réécrit le descripteur, même pour une opération en
  lecture seule (`-summary`, `-check`, `EmbeddedFMU`) ;
- **en génération** : `container.py` produit le `modelDescription.xml` du container avec des f-strings
  (`EmbeddedFMUPort.xml()`, `HEADER_XML_2/3`, `make_fmu_xml()`).

Défauts constatés, dont la plupart ont été reproduits avec une opération vide (`OperationAbstract`) :

| # | Défaut | Où | Corrigé par ElementTree ? |
|---|---|---|---|
| D1 | Le texte entre balises n'est pas échappé : `x &lt; y` devient `x < y`, donc XML invalide | `Manipulation.char_data` | ✅ par construction |
| D2 | `<Start value>` des `String`/`Binary` FMI-3 non échappé | `FMUPort.write_xml` | ✅ par construction |
| D3 | Double désencodage des attributs : `a &amp;lt; b` devient `a &lt; b` | `Manipulation.escape` | ✅ par construction |
| D4 | Sous-éléments d'une variable perdus : `<Annotations>` (FMI-2), `<Alias>` (FMI-3), plusieurs `<Start>` (tableaux de `String`) | `start_element` / `FMUPort.write_xml` | ✅ si l'arbre est **modifié en place** au lieu d'être régénéré |
| D5 | Commentaires et déclaration `<?xml?>` supprimés. **Non conforme** : FMI-2 §2.2 et FMI-3 §2.4 exigent que la première ligne déclare l'encodage UTF-8 | `Manipulation` | ⚠️ seulement si on le demande explicitement (`TreeBuilder(insert_comments=True)`, `xml_declaration=True`) |
| D6 | Conséquence de D1/D2 : la **deuxième** opération d'une chaîne lève `ExpatError` (ex. `fmutool -remove-toplevel -check`) | — | ✅ |
| D7 | XML du container non échappé (attributs `description`, `name`… recopiés tels quels depuis les FMU embarquées) | `EmbeddedFMUPort.xml`, `HEADER_XML_*` | ✅ si la génération passe aussi par ElementTree (phase 4) |
| D8 | Container : `encoding="ISO-8859-1"` déclaré, mais fichier ouvert en `"wt"` **sans encodage**, donc écrit avec l'encodage de la locale (UTF-8 sous Linux/macOS, cp1252 sous Windows). **Non conforme** : les deux standards exigent UTF-8 | `container.py:2020`, `:1465`, `:1502` | ✅ avec `tree.write(..., encoding="UTF-8")` |
| D9 | `-remove-sources` supprime `sources/` mais laisse `<SourceFiles>` dans le descripteur | `OperationRemoveSources` | ➖ pas automatique, mais devient trivial |
| D10 | Une opération qui supprime **toutes** les variables (ex. `-keep-only-regexp` sans correspondance) produit un `<ModelVariables>` vide, que le XSD FMI-2 comme FMI-3 interdit. L'outil livre alors une FMU invalide sans prévenir | `Manipulation` | ➖ non ; il faut un garde-fou explicite (erreur ou avertissement) |
| D11 | FMI-2 : l'attribut `derivative` (index 1-based de l'état, §2.2.7) **n'est pas renuméroté** quand des ports sont supprimés. Dans `tests/data/me/velocity_me.fmu`, après `rename_from_csv`, `Deriv1` pointe sur lui-même | `Manipulation` (seuls `<Unknown index>` et `dependencies` sont renumérotés) | ➖ non ; à traiter en phase 2 |
| D12 | Supprimer une variable référencée par une autre laisse une **référence pendante** : `derivative` (FMI-2 et FMI-3), `previous`, `clocks`, `<Dimension valueReference>` (FMI-3) | `Manipulation` | ➖ non ; refuser l'opération ou supprimer en cascade (décision en phase 2) |
| D13 | Les renommages (`-remove-toplevel`, `-trim-until`…) peuvent donner **le même nom** à plusieurs variables, alors que les noms (et les alias FMI-3) doivent être uniques (FMI-3 §2.4 *uniqueNameAttribute*). Le XSD ne le vérifie pas. Constaté sur 5 FMU de `tests/data` (`ls-bus/bus`, `split/container-*`) | opérations de renommage | ➖ non ; garde-fou en phase 2 |
| D14 | *(trouvé en phase 2)* L'ancienne réécriture supprimait les `<Start value="">` vides des `Binary` FMI-3 et les `<Dimension start="1">` : un tableau de taille 1 devenait un scalaire. Constaté sur les FMU ls-bus de `tests/data` | `FMUPort.write_xml` | ✅ corrigé en phase 2 (arbre modifié en place) |

D1 à D6 et D9 à D14 sont reproduits par des tests (phases 0 à 2) et **corrigés en phase 2**. D7 et D8 viennent de la lecture
du code ; ils seront couverts par les tests de la phase 4. Pour D10, D12 et D13, la politique retenue est le **refus** de
l'opération (`OperationError`, FMU laissée intacte).

**Ce qu'ElementTree ne corrige pas** (à traiter à part, voir phase 3) : `BadZipFile` brute au lieu de `FMUError`, nettoyage du
répertoire temporaire dans `__del__`, code de sortie de `-check` toujours à 0.

**Réponse courte** : oui, commencer par ElementTree plutôt que de corriger les bugs un par un. Les bugs D1 à D4, D6 et D7
viennent tous du même choix : écrire du XML à la main. Les corriger un par un dans `Manipulation` reviendrait à réimplémenter
un sérialiseur XML. **À une condition** : poser d'abord le filet de tests de la phase 0. Les tests actuels comparent les
fichiers **octet par octet** (`assert_identical_files`), alors qu'un changement de sérialiseur modifie forcément les octets
(`<X></X>` devient `<X/>`, espaces dans les balises, etc.) sans changer le sens.

---

## 2. Contraintes : l'API publique à préserver

`OperationAbstract` et `FMUPort` sont documentées comme API d'extension (`docs/user-guide/fmutool/python-api.md`, checkers
personnalisés chargés dynamiquement par `checker.py`). Elles sont aussi utilisées en interne :

| Consommateur | Ce qu'il utilise |
|---|---|
| `container.py` (`EmbeddedFMU`) | `port_attrs`, `fmu_port.fmi_type = "Integer"` (Enumeration → Integer), `fmu_port.get("start")`, `FMUPort` passé à `EmbeddedFMUPort`, `fmu.tmp_directory` |
| `gui/fmueditor` | `fmu_port[key] = value`, **`fmu_port.attrs_list[0][key] = value`**, itération sur `attrs_list` |
| `checker.py` | `fmi_attrs` puis validation XSD de `fmu.descriptor_filename` **sur disque** |
| `remoting.py`, `terminals.py` | fichiers de `fmu.tmp_directory` |
| `assistant/fmutools.py` | `FMU(...).apply_operation(...)` |
| Opérations internes | `ManipulationSkipTag` (levée depuis `port_attrs` pour supprimer un port) |

On garde donc :

- `FMU` : `fmu_filename`, `tmp_directory`, `descriptor_filename`, `fmi_version`, `apply_operation(op, apply_on)`,
  `repack()`, `save_descriptor()` ;
- `FMUPort` : `[]`, `get()`, `in`, `fmi_type`, `attrs_list`, `dimensions` ;
- `OperationAbstract` : toutes les callbacks, dans le même ordre d'appel (`fmi_attrs` → variables → `ModelStructure` →
  `closure`) ;
- **le descripteur écrit sur disque après chaque `apply_operation`**, pour que le checker XSD et les outils qui lisent
  `tmp_directory` continuent de fonctionner.

Avec ElementTree, `Element.attrib` est un vrai `dict`. Si `FMUPort.attrs_list` devient `[sv.attrib, child.attrib]`
(FMI-2) ou `[var.attrib]` (FMI-3), les modifications faites par les opérations, y compris l'accès direct de `fmueditor` à
`attrs_list[0]`, arrivent **directement dans l'arbre**, sans recopie. Changer `fmi_type` revient à renommer la balise de
l'élément enfant.

---

## 3. Plan

### Phase 0 — Filet de sécurité (avant de toucher au code)

1. **Comparaison canonique** : ajouter `assert_equivalent_xml(a, b)` dans `tests/_helpers/assertions.py`. Elle s'appuie sur
   `xml.etree.ElementTree.canonicalize()` (C14N 2.0, `strip_text=True`). Les tests qui comparent des `modelDescription.xml`
   (`test_operations.py`, `test_container.py`, `test_array.py`, `test_split.py`…) passent sur cette comparaison. Les
   comparaisons octet par octet restent pour les autres fichiers (`container.txt`, CSV).
2. **Tests de caractérisation** : pour chaque `.fmu` de `tests/data`, appliquer chaque opération intégrée et vérifier
   l'équivalence C14N avec la sortie **actuelle**. Les références sont générées une fois avec le code actuel et versionnées
   dans `tests/data/refactoring/`. Les FMU de test n'exercent pas les bugs D1 à D4, donc ces références sont fiables.
3. **Tests de non-régression des bugs**, marqués `xfail(strict=True)` en attendant la phase 2 :
   - aller-retour avec une opération vide : `canonicalize(avant) == canonicalize(après)` sur un descripteur qui contient du
     texte échappé, des `<Annotations>`, des `<Alias>`, un `<Start>` de `String` avec `"` et `<`, et un commentaire ;
   - enchaînement de deux opérations sur ce même descripteur (D6) ;
   - descripteur toujours bien formé et **valide XSD** après chaque opération intégrée.
4. **Mesure de référence** : temps et mémoire d'un `apply_operation` sur un gros descripteur synthétique (~100 000
   variables), pour vérifier en phase 2 que la construction d'un arbre complet reste acceptable.

*Critère de sortie* : suite verte, nouveaux tests `xfail` qui échouent bien pour les raisons attendues.

**État au 9 octobre 2026 : réalisée.**

| Élément | Fichier |
|---|---|
| `canonical_xml()`, `assert_equivalent_xml()`, `VOLATILE_XML_ATTRIBUTES` (remplace `assert_identical_files_but_guid`, supprimé) | `tests/_helpers/assertions.py` |
| Tests du helper : il ignore la mise en forme, mais pas un attribut, un texte, un niveau d'échappement, un élément en plus ou l'ordre des éléments | `tests/unit/test_xml_assertions.py` |
| Comparaisons des `modelDescription.xml` passées en C14N | `tests/integration/test_array.py`, `test_container.py` |
| Caractérisation : 48 FMU × 8 opérations modifiantes + 4 opérations en lecture seule (comparées à `noop.xml`), dump CSV et rapport `-summary` | `tests/integration/test_operations_characterization.py` |
| Références (1,2 Mo, forme canonique, régénérables avec `pytest --update-refs`) | `tests/data/refactoring/<fmu>/` |
| Validité XSD après chaque opération modifiante (toutes les FMU de test sont valides au départ) | `test_operation_keeps_descriptor_valid` |
| Tests des défauts D1 à D6, D9 et `BadZipFile`, en `xfail(strict=True, raises=…)` : chacun n'est accepté qu'avec l'exception que produit le défaut | `tests/unit/test_xml_roundtrip.py` |
| Benchmark (hors suite) | `tests/benchmarks/bench_manipulation.py` |

Vérifications faites :

- deux mutations volontaires de `operations.py` (renumérotation décalée, attribut parasite en FMI-3) sont détectées par la
  caractérisation (257 et 269 échecs) ;
- les 9 cas où `keep_only_regexp` vide `<ModelVariables>` sont marqués `xfail` (D10) au lieu d'être masqués.

Mesure de référence (`python tests/benchmarks/bench_manipulation.py`). La ligne *ET parse+write* n'est pas une opération :
c'est une simple lecture/écriture ElementTree du même fichier, pour estimer dès maintenant le coût d'un arbre complet.

Python 3.14.8 — macOS-26.6.1-arm64-arm-64bit-Mach-O — best of 3 runs

| FMI | Variables | Descriptor | Operation | Time | Peak memory (tracemalloc) |
|---|---:|---:|---|---:|---:|
| 2.0 | 1,000 | 0.2 MB | noop | 0.01 s | 0.4 MB |
| 2.0 | 1,000 | 0.2 MB | remove 10% | 0.01 s | 0.4 MB |
| 2.0 | 1,000 | 0.2 MB | *ET parse+write (estimate)* | 0.00 s | 1.5 MB |
| 2.0 | 10,000 | 1.8 MB | noop | 0.05 s | 1.3 MB |
| 2.0 | 10,000 | 1.8 MB | remove 10% | 0.05 s | 1.4 MB |
| 2.0 | 10,000 | 1.8 MB | *ET parse+write (estimate)* | 0.05 s | 11.6 MB |
| 2.0 | 100,000 | 18.2 MB | noop | 0.54 s | 10.4 MB |
| 2.0 | 100,000 | 18.2 MB | remove 10% | 0.53 s | 11.1 MB |
| 2.0 | 100,000 | 18.2 MB | *ET parse+write (estimate)* | 0.47 s | 113.8 MB |
| 3.0 | 1,000 | 0.1 MB | noop | 0.00 s | 0.4 MB |
| 3.0 | 1,000 | 0.1 MB | remove 10% | 0.00 s | 0.4 MB |
| 3.0 | 1,000 | 0.1 MB | *ET parse+write (estimate)* | 0.00 s | 1.1 MB |
| 3.0 | 10,000 | 1.3 MB | noop | 0.04 s | 1.3 MB |
| 3.0 | 10,000 | 1.3 MB | remove 10% | 0.04 s | 1.4 MB |
| 3.0 | 10,000 | 1.3 MB | *ET parse+write (estimate)* | 0.03 s | 9.2 MB |
| 3.0 | 100,000 | 13.0 MB | noop | 0.45 s | 10.4 MB |
| 3.0 | 100,000 | 13.0 MB | remove 10% | 0.45 s | 11.1 MB |
| 3.0 | 100,000 | 13.0 MB | *ET parse+write (estimate)* | 0.34 s | 89.0 MB |

**Lecture** : le temps n'est pas un sujet, l'arbre complet est même un peu plus rapide. La mémoire l'est davantage : environ
6 fois la taille du descripteur (114 Mo pour 18 Mo), contre ~10 Mo en SAX. C'est acceptable pour un outil de bureau ou de CI,
mais c'est le point à surveiller.

### Phase 1 — Noyau `ModelDescription`

Nouveau module `fmu_manipulation_toolbox/model_description.py`, sans dépendance au reste :

- `ModelDescription.load(path)` : parse avec `ET.XMLParser(target=ET.TreeBuilder(insert_comments=True, insert_pis=True))`.
  Enregistre aussi les préfixes de namespaces rencontrés (`iterparse` sur `start-ns`, puis `ET.register_namespace`), pour
  éviter que les annotations vendeur ressortent en `ns0:` ;
- `fmi_version`, `root`, `model_variables`, `model_structure`, `parent_of(element)` ;
- `iter_ports()` : un `FMUPort` par variable (FMI-2 : `ScalarVariable` + enfant typé ; FMI-3 : élément typé, `<Dimension>`,
  `<Start>`) ;
- `save(path)` : `tree.write(path, encoding="UTF-8", xml_declaration=True, short_empty_elements=True)`, l'encodage
  qu'attend le standard FMI.

Tests unitaires dédiés : chargement FMI-2 et FMI-3, aller-retour C14N, namespaces, commentaires.

**Cohérence avec les spécifications FMI-2 et FMI-3.** Le module doit suivre ce que disent les spécifications publiées sur
[fmi-standard.org](https://fmi-standard.org/), pas seulement ce que fait le code actuel. Celui-ci s'est construit au fil des
FMU rencontrées. Pour chaque version :

1. **Identifier la version de référence** : relever la version mineure exacte des XSD embarqués (`resources/fmi-2.0/`,
   `resources/fmi-3.0/`, leurs en-têtes ne la donnent pas), la comparer à la dernière version publiée de chaque standard
   (2.0.x et 3.0.x), et mettre à jour les XSD si besoin, dans une PR séparée.
2. **Construire une matrice de conformité** dans ce document : élément ou attribut du standard → section de la
   spécification → traitement par `model_description.py` → test qui le couvre. Points à vérifier au minimum :

   | Sujet | FMI-2 | FMI-3 |
   |---|---|---|
   | Variables | `<ScalarVariable>` avec exactement un enfant typé (`Real`, `Integer`, `Boolean`, `String`, `Enumeration`), puis `<Annotations>` optionnel | Un élément par type (`Float32`/`Float64`, `Int8`…`UInt64`, `Boolean`, `String`, `Binary`, `Enumeration`, `Clock`) ; enfants `<Dimension>`, `<Start>` (`String`/`Binary`), `<Alias>`, `<Annotations>` |
   | Définitions de types | `<TypeDefinitions>/<SimpleType>` avec des enfants **du même nom** que les types de variables : ne doivent pas être pris pour des variables | `<TypeDefinitions>` avec `Float64Type`, `EnumerationType`… |
   | Tableaux | — | `<Dimension start>` ou `<Dimension valueReference>` (paramètre structurel) ; attribut `start` multi-valeurs pour les types numériques |
   | `ModelStructure` | `<Outputs>`, `<Derivatives>`, `<InitialUnknowns>` → `<Unknown index dependencies dependenciesKind>`, `index` **1-based** dans l'ordre de `<ModelVariables>` | `<Output>`, `<ContinuousStateDerivative>`, `<ClockedState>`, `<InitialUnknown>`, `<EventIndicator>`, référencés par `valueReference` |
   | Types d'interface | `<ModelExchange>`, `<CoSimulation>` | idem + **`<ScheduledExecution>`**, qu'aucune callback d'`OperationAbstract` ne gère aujourd'hui |
   | Ordre des éléments racine | Celui imposé par le XSD : la sérialisation ne doit pas le changer | idem |
   | Encodage, déclaration XML, namespaces | Ce que la spécification impose ou recommande pour le fichier | idem |
   | Fichiers annexes | — | `terminalsAndIcons/terminalsAndIcons.xml`, `buildDescription.xml`, standards en couches (`extra/`) : hors de `ModelDescription`, mais à ne pas casser |

3. **Tester sur des FMU qui couvrent le standard**, pas seulement sur celles de `tests/data` : envisager les
   [Reference FMUs](https://github.com/modelica/Reference-FMUs) du projet Modelica (FMI-2 et FMI-3, licence BSD-2), qui
   exercent tableaux, horloges, `Binary`, `ScheduledExecution`, etc. Chaque cas de la matrice est couvert par un test, et
   chaque descripteur chargé puis enregistré reste **valide XSD** et équivalent en C14N.
4. **Consigner les écarts** : tout comportement du code actuel qui contredit la spécification est ajouté au tableau des
   défauts (D11…), avec la phase qui le corrige. On ne le reproduit pas en silence.

*Critère de sortie* : matrice de conformité complète, sans case « non traité » qui ne soit pas justifiée ; tests verts sur
les FMU de `tests/data` et sur l'échantillon de référence retenu.

**État au 9 octobre 2026 : réalisée.**

| Élément | Fichier |
|---|---|
| Module `ModelDescription` / `ModelVariable` / `ModelDescriptionError`, sans dépendance au reste du paquet | `fmu_manipulation_toolbox/model_description.py` |
| Descripteurs des Reference FMUs v0.0.41 (6 FMI-2, 9 FMI-3, 76 Ko, licence BSD-2) | `tests/data/reference-fmus/` |
| Tests du module (296) : chargement, erreurs, aller-retour C14N **avec commentaires**, déclaration UTF-8, validité XSD conservée, structure, compatibilité avec `FMUPort` | `tests/unit/test_model_description.py` |
| Tests des écarts au standard D11 à D13, en `xfail(strict=True)` | `tests/unit/test_operations_conformity.py` |

Choix de conception :

- `iter_ports()` renvoie des `ModelVariable`, et non des `FMUPort` : importer `operations.py` créerait un cycle dès la phase 2.
  `ModelVariable` expose la même interface (`[]`, `get()`, `in`, `fmi_type`, `attrs_list`, `dimensions`), mais
  `attrs_list` contient les `attrib` des éléments de l'arbre. En phase 2, `FMUPort` deviendra `ModelVariable` (alias ou
  sous-classe, à cause du `isinstance(attrs, FMUPort)` de `EmbeddedFMUPort`) ;
- les `<Start>` FMI-3 (`String`/`Binary`) apparaissent comme des niveaux `{"start": value}`, comme dans `FMUPort`, mais
  la lecture et l'écriture se font sur l'élément `<Start>` lui-même ;
- `test_model_variable_reads_like_fmu_port` compare, variable par variable, ce que lisent `ModelVariable` et l'`FMUPort`
  actuel sur les 63 descripteurs. Ils sont identiques, y compris la convention « `<Dimension start="1">` seul = scalaire » ;
- la déclaration XML est écrite à la main (`<?xml version="1.0" encoding="UTF-8"?>`, guillemets doubles comme dans
  l'exemple de la spécification), car ElementTree écrirait des guillemets simples ;
- commentaires et instructions de traitement placés **avant ou après** la racine : `TreeBuilder` les ignore, donc ils sont
  capturés à part (`prolog`, `epilog`) ;
- namespaces : les préfixes sont enregistrés juste avant l'écriture (le registre d'ElementTree est global).

Vérifications faites : trois mutations volontaires du module (niveaux `<Start>` omis, commentaires hors racine mal placés,
convention des dimensions) sont détectées (6, 1 et 3 échecs).

**Version de référence des XSD** (comparaison fichier à fichier avec les sources de `modelica/fmi-standard`) :

| Standard | XSD embarqués | Dernière version publiée | Écart |
|---|---|---|---|
| FMI 2.0 | **2.0.4** (identiques fichier à fichier) | 2.0.5 | Uniquement les commentaires d'en-tête (copyright, numéro de version) : aucune différence de schéma. Mise à jour possible pour la traçabilité, sans urgence |
| FMI 3.0 | **3.0.2** (identiques) | 3.0.2 | Aucun |

**Matrice de conformité** (FMI 2.0.5 / FMI 3.0.2 ; numéros de section calculés à partir des sources asciidoc de
`modelica/fmi-standard` aux tags `v2.0.5` et `v3.0.2`) :

| Règle du standard | Source | `model_description.py` | Test |
|---|---|---|---|
| Première ligne : déclaration XML, encodage **UTF-8 obligatoire** | FMI-2 §2.2, FMI-3 §2.4 | Déclaration toujours écrite, sortie toujours en UTF-8, quel que soit l'encodage d'entrée | `test_saved_file_starts_with_utf8_declaration`, `test_non_utf8_input_is_saved_in_utf8` |
| L'ordre des éléments est significatif (index FMI-2, vecteur d'états FMI-3) | FMI-2 §2.2, FMI-3 §2.4 | Arbre modifié en place, ordre conservé | `test_roundtrip_is_equivalent` (C14N, ordre significatif) |
| Variables FMI-2 : `<ScalarVariable>` + un enfant typé, `<Annotations>` optionnel | FMI-2 §2.2.7 | `variables()`, `ModelVariable.typed_element` ; annotations conservées | `edge/fmi2-variable-annotations` |
| `<TypeDefinitions>/<SimpleType>` FMI-2 : mêmes noms de balises que les types de variables | FMI-2 §2.2.3 | Seuls les enfants de `<ModelVariables>` sont des variables | `test_fmi2_type_definitions_are_not_variables` (Reference FMU `2.0/Feedthrough`) |
| Variables FMI-3 : 15 types, dont `Binary` et `Clock` | FMI-3 §2.4.7 | `FMI3_VARIABLE_TYPES` | Reference FMUs `3.0/Feedthrough`, `3.0/Clocks` |
| Tableaux FMI-3 : `<Dimension start>` ou `<Dimension valueReference>` | FMI-3 §2.4.7.2 | `ModelVariable.dimensions` | Reference FMU `3.0/StateSpace`, `test_model_variable_dimension_of_one_is_scalar` |
| `start` de `String`/`Binary` FMI-3 : suite d'éléments `<Start value>` | FMI-3 §2.4.7.5 | Niveaux `_StartValue`, tous conservés | `test_model_variable_fmi3_start_elements` |
| Alias FMI-3 `<Alias name>` | FMI-3 §2.4.7.3 | Conservés (arbre modifié en place) | `edge/fmi3-alias`, Reference FMU `3.0/BouncingBall` |
| Noms de variables et d'alias **uniques** | FMI-3 §2.4 *uniqueNameAttribute*, FMI-2 §2.2.7 | Hors périmètre du module (lecture/écriture) | Écart des opérations : **D13** |
| `ModelStructure` FMI-2 : `<Unknown index>` 1-based | FMI-2 §2.2.8 | `model_structure_entries()` → `(section, <Unknown>)` | `test_fmi2_model_structure_entries` |
| `ModelStructure` FMI-3 : `Output`, `ContinuousStateDerivative`, `ClockedState`, `InitialUnknown`, `EventIndicator` par `valueReference` | FMI-3 §2.4.8 | `model_structure_entries()` → `(balise, élément)` | `test_fmi3_model_structure_entries` |
| `derivative` FMI-2 = **index** de l'état | FMI-2 §2.2.7 | Exposé tel quel (attribut) | Écart des opérations : **D11** |
| Références entre variables FMI-3 (`derivative`, `previous`, `clocks`, `<Dimension valueReference>`) | FMI-3 §2.4.7 | Exposées telles quelles | Écart des opérations : **D12** |
| Types d'interface : au moins un parmi `ModelExchange`, `CoSimulation`, `ScheduledExecution` (FMI-3) | FMI-3 §2.4.1 | `interfaces` (les trois) | `test_interfaces` (dont `3.0/Clocks`, **uniquement** `ScheduledExecution`) |
| `<Annotations>/<Annotation type>` FMI-3 : contenu XML arbitraire, namespaces autorisés | FMI-3 §2.4 | Préfixes conservés | `test_namespace_prefixes_are_kept` |
| Fichiers annexes (`terminalsAndIcons.xml`, `buildDescription.xml`, `extra/`) | FMI-3 §2.4.9, §2.4.10, §2.5 | Hors périmètre : non touchés | — |
| *« It is not allowed to change the start values in the modelDescription.xml »* (FMI-3 ; *« not recommended »* en FMI-2) | FMI-3 §2.4.7.5, FMI-2 §2.2.7 | Hors périmètre | Vérifié : ni `fmueditor` ni les opérations ne modifient les `start` (le container les applique à l'exécution) |

Limites connues, justifiées :

- un **namespace par défaut** (`xmlns="…"` sans préfixe) dans une annotation est réécrit avec un préfixe généré (`ns0:`).
  C'est équivalent en XML, mais pas identique au texte. ElementTree ne permet pas mieux ; aucun cas rencontré dans les 63
  descripteurs ;
- la forme du texte change (`<X></X>` → `<X/>`, guillemets, position des déclarations `xmlns`), sans changer le sens ;
- la référence de caractérisation `tests/data/refactoring/me__velocity_me/rename_from_csv.xml` contient le défaut D11. Elle
  devra être régénérée volontairement quand la phase 2 le corrigera.

### Phase 2 — `Manipulation` réécrit sur l'arbre

`Manipulation.manipulate()` garde sa signature, mais fait maintenant :

1. charger le `ModelDescription` ;
2. appeler `fmi_attrs`, `cosimulation_attrs`, `modelexchange_attrs`, `experiment_attrs` sur les `attrib` des éléments
   concernés ;
3. parcourir les variables : `port_attrs(FMUPort)`. Si l'opération demande la suppression (valeur non nulle ou
   `ManipulationSkipTag`), on retire l'élément de `<ModelVariables>` et on enregistre la table de renumérotation
   (`port_translation`, `port_removed_vr`) ;
4. parcourir `<ModelStructure>` avec la même logique qu'aujourd'hui (`unknown_attrs`, `handle_structure`). L'actuel
   mécanisme `delayed_tag` pour supprimer les sections vides devient un simple nettoyage après coup ;
5. `closure()`, puis `save()` sur `descriptor_filename`.

On supprime ensuite `escape()`, `char_data`, `skip_until`, `delayed_tag*` et `FMUPort.write_xml()`. On garde `push_attrs` et
le setter `dimensions` comme alias dépréciés (`DeprecationWarning`), au cas où des scripts utilisateurs les appelleraient.

Au passage, il devient simple de supprimer `<SourceFiles>` dans `OperationRemoveSources` (D9).

*Critère de sortie* : les tests `xfail` de la phase 0 passent (on retire `xfail`), les tests de caractérisation sont
équivalents en C14N, et le benchmark respecte, sur 100 000 variables : temps ≤ 1,5 × la référence SAX, mémoire ≤ 8 × la
taille du descripteur.

**État au 9 octobre 2026 : réalisée.**

| Élément | Fichier |
|---|---|
| `Manipulation` réécrit sur `ModelDescription` : callbacks dans l'ordre du document, arbre modifié en place, suppressions groupées | `fmu_manipulation_toolbox/operations.py` |
| `FMUPort` devient une sous-classe de `ModelVariable`. `FMUPort()` détaché et `push_attrs()` restent disponibles, avec `DeprecationWarning` ; `write_xml()`, `escape()` et le parseur expat sont supprimés | `operations.py` |
| `OperationAbstract.model_description` : accès à l'arbre complet pour ce que les callbacks ne savent pas exprimer | `operations.py` |
| `PrefixedAttributes` : les callbacks reçoivent toujours `xsi:noNamespaceSchemaLocation`, et non `{http://…}noNamespaceSchemaLocation` | `model_description.py` |
| D9 : `OperationRemoveSources` supprime aussi `<SourceFiles>`, et agit désormais sur les FMU Model Exchange seules | `operations.py` |
| Refus D10, D12, D13 et renumérotation D11 ; tests stricts (plus de `xfail`) | `tests/unit/test_operations_conformity.py` |
| `xfail` de D1 à D6 et D9 retirés ; tests de D14 ajoutés | `tests/unit/test_xml_roundtrip.py` |
| Références de caractérisation mises à jour (voir ci-dessous) ; `remove_sources` passe dans les opérations modifiantes ; une opération refusée a une référence `<cas>.error` | `tests/integration/test_operations_characterization.py`, `tests/data/refactoring/` |
| Documentation : callbacks, `model_description`, refus ; page d'API du module ; `CHANGELOG.md` | `docs/user-guide/fmutool/python-api.md`, `docs/API/model_description.md`, `mkdocs.yml` |

**Revue des références de caractérisation modifiées.** Chaque changement est expliqué par un défaut corrigé ; rien d'autre
n'a bougé :

| Changement | Nombre | Cause |
|---|---:|---|
| `<cas>.xml` remplacé par `<cas>.error` « remove every variable » | 9 | D10 (`keep_only_regexp`) |
| `<cas>.xml` remplacé par `<cas>.error` « still referenced » | 10 | D12 : états (`derivative`), paramètres structurels (`Dimension`), horloges (`clocks`) |
| `<cas>.xml` remplacé par `<cas>.error` « same name » | 10 | D13 (`strip_top_level`, `trim_until_dot` sur 5 FMU) |
| `derivative` renuméroté (et vérifié : il pointe sur le bon état) | 6 | D11 |
| `<Start value="">` et `<Dimension start="1">` restaurés | 14 fichiers | D14 (FMU ls-bus) |
| Ligne `xmlns:xsi = …` absente du rapport `summary.txt` | 3 | Les déclarations `xmlns` ne sont pas des attributs |
| Nouveaux `remove_sources.xml` : égaux à `noop.xml` à `<SourceFiles>` près | 48 (2 avec `<SourceFiles>`) | D9 |

Un script a vérifié les invariants sur les 403 sorties acceptées : aucune référence pendante, aucun nom dupliqué introduit,
aucun `<ModelVariables>` vide, chaque `derivative` FMI-2 pointe sur le même état qu'avant l'opération.

Vérifications faites :

- les 21 nouveaux tests de défauts **échouent sur le code de la phase 1** (commit `8e63a40`) et passent sur la phase 2. Les
  5 tests qui passent des deux côtés sont des garde-fous : aller-retour simple, refus limité à ce que l'opération casse
  elle-même (doublons et références pendantes déjà présents dans la FMU d'origine ne sont pas reprochés) ;
- la suite complète passe (1763 tests, 1 `xfail` restant : `BadZipFile`, phase 3), y compris avec
  `-W error::DeprecationWarning` : le paquet n'utilise plus l'API dépréciée.

**Benchmark** (critère : temps ≤ 1,5 × la référence SAX, mémoire ≤ 8 × la taille du descripteur, sur 100 000 variables) :

Python 3.14.8 — macOS-26.6.1-arm64-arm-64bit-Mach-O — best of 3 runs

| FMI | Variables | Descriptor | Operation | Time | Peak memory (tracemalloc) |
|---|---:|---:|---|---:|---:|
| 2.0 | 1,000 | 0.2 MB | noop | 0.01 s | 1.5 MB |
| 2.0 | 1,000 | 0.2 MB | remove 10% | 0.01 s | 1.5 MB |
| 2.0 | 1,000 | 0.2 MB | *ET parse+write (estimate)* | 0.00 s | 1.5 MB |
| 2.0 | 10,000 | 1.8 MB | noop | 0.06 s | 12.6 MB |
| 2.0 | 10,000 | 1.8 MB | remove 10% | 0.07 s | 13.3 MB |
| 2.0 | 10,000 | 1.8 MB | *ET parse+write (estimate)* | 0.04 s | 11.6 MB |
| 2.0 | 100,000 | 18.2 MB | noop | 0.63 s | 126.2 MB |
| 2.0 | 100,000 | 18.2 MB | remove 10% | 0.72 s | 133.7 MB |
| 2.0 | 100,000 | 18.2 MB | *ET parse+write (estimate)* | 0.48 s | 113.8 MB |
| 3.0 | 1,000 | 0.1 MB | noop | 0.00 s | 1.2 MB |
| 3.0 | 1,000 | 0.1 MB | remove 10% | 0.00 s | 1.2 MB |
| 3.0 | 1,000 | 0.1 MB | *ET parse+write (estimate)* | 0.00 s | 1.1 MB |
| 3.0 | 10,000 | 1.3 MB | noop | 0.04 s | 10.1 MB |
| 3.0 | 10,000 | 1.3 MB | remove 10% | 0.05 s | 10.2 MB |
| 3.0 | 10,000 | 1.3 MB | *ET parse+write (estimate)* | 0.03 s | 9.2 MB |
| 3.0 | 100,000 | 13.0 MB | noop | 0.50 s | 101.4 MB |
| 3.0 | 100,000 | 13.0 MB | remove 10% | 0.54 s | 102.5 MB |
| 3.0 | 100,000 | 13.0 MB | *ET parse+write (estimate)* | 0.35 s | 89.0 MB |

| 100 000 variables | Référence SAX | Phase 2 | Rapport | Mémoire / descripteur |
|---|---:|---:|---:|---:|
| FMI 2.0, noop | 0,54 s | 0,63 s | 1,17 | 6,9 × |
| FMI 2.0, remove 10 % | 0,53 s | 0,72 s | 1,36 | 7,3 × |
| FMI 3.0, noop | 0,45 s | 0,50 s | 1,11 | 7,8 × |
| FMI 3.0, remove 10 % | 0,45 s | 0,54 s | 1,20 | 7,9 × |

Critère tenu. Deux corrections ont été nécessaires : la première version prenait 4,8 s pour `remove 10 %`, parce que
`Element.remove()` est linéaire et était appelé une fois par élément supprimé ; les suppressions sont maintenant groupées. La
mémoire FMI-3 est proche de la limite : c'est le coût de l'arbre ElementTree lui-même (6,8 × pour une simple lecture/écriture).

### Phase 3 — Cycle de vie de `FMU` (indépendant, petit)

- `zipfile.BadZipFile` → `FMUError` ;
- `FMU` devient un gestionnaire de contexte (`__enter__`/`__exit__`), et le nettoyage passe par `weakref.finalize` au lieu
  de `__del__` ;
- la CLI capture aussi `ET.ParseError` et la convertit en message clair.

**État au 9 octobre 2026 : réalisée.**

| Élément | Fichier |
|---|---|
| Ouverture : `BadZipFile`, répertoire (`IsADirectoryError`/`PermissionError`), fichier absent, descripteur absent → `FMUError` ; le répertoire temporaire est supprimé immédiatement en cas d'échec | `operations.py` (`FMU`) |
| `weakref.finalize` remplace `__del__` : le nettoyage a aussi lieu à l'arrêt de l'interpréteur, et ne lève plus d'exception si le répertoire a déjà disparu | `operations.py` |
| `close()`, `closed`, `__enter__`/`__exit__` ; un `FMU` fermé lève `FMUError` (« is closed ») au lieu d'une erreur de fichier introuvable | `operations.py` |
| `with FMU(...)` aux endroits où la durée de vie est délimitée : CLI `fmutool`, outils MCP (`fmutools.py`, `headless.py`), nœuds du graphe GUI. Restent sur le nettoyage automatique les objets qui vivent avec leur propriétaire (`EmbeddedFMU`, FMU affichée par la GUI `fmutool`) | `cli/fmutool.py`, `assistant/`, `gui/fmucontainer/graph/node.py` |
| CLI : un descripteur illisible arrive en `FMUError` depuis la phase 2 (et non plus en `ET.ParseError`) ; la boucle d'opérations l'attrape désormais (code de sortie −6) | `cli/fmutool.py` |
| Tests : cycle de vie (`tests/unit/test_fmu_lifecycle.py`, 16 tests) et 3 nouveaux cas CLI (fichier non-zip → −4, descripteur illisible → −6, opération refusée → −6) ; dernier `xfail` retiré | `tests/` |
| Documentation : guide de l'API Python, `CHANGELOG.md` | `docs/`, `CHANGELOG.md` |

Vérifications faites : 14 des nouveaux tests échouent sur le code de la phase 2 ; les 11 autres sont des tests existants ou
des cas déjà corrects (fichier absent, refus de la phase 2). Suite complète : 1781 tests, **aucun `xfail` restant**.

Non traité ici, comme prévu : le code de sortie de `-check` (toujours 0) et les codes de sortie négatifs de la CLI, laissés à
la phase 5.

### Phase 4 — Génération du container sur ElementTree

- `EmbeddedFMUPort.xml()` renvoie un `ET.Element` au lieu d'une chaîne ;
- `make_fmu_xml()` construit l'arbre (en-tête FMI-2/FMI-3, `ModelVariables`, `ModelStructure`) et l'écrit avec `save()` du
  module de la phase 1. Cela corrige D7 et D8 ;
- références de test : `REF-*modelDescription*.xml` comparés en C14N (phase 0), en ignorant les attributs
  volatils (`guid`, `generationDateAndTime`…) listés dans `VOLATILE_XML_ATTRIBUTES` ;
- on ajoute un test avec une FMU embarquée dont la `description` contient `&`, `"` et des caractères non ASCII.

### Phase 5 — Finalisation

- `split.py` : remplacer son parser expat en lecture seule par `ModelDescription`. Il n'y a pas de bug connu, l'intérêt est
  la cohérence du code ;
- `checker.py` : s'appuyer sur l'arbre pour ajouter des règles sémantiques (valueReference/noms uniques, index de
  `ModelStructure`, combinaisons causality/variability/initial), remplacer `validate()` par `iter_errors()`, et faire en sorte
  que `-check` renvoie un code de sortie non nul ;
- CLI : remplacer les codes de sortie négatifs (`sys.exit(-3)` donne 253 sous POSIX) par des codes positifs documentés.
  C'est une rupture pour les scripts qui testent ces valeurs : à annoncer dans `CHANGELOG.md` ;
- ne réécrire le descripteur que s'il a été modifié (indicateur de modification), puis parser une seule fois par FMU au lieu
  d'une fois par opération. **Attention** : `EmbeddedFMU` modifie aujourd'hui `fmi_type` (Enumeration → Integer) pendant une
  opération supposée en lecture seule. Il faut vérifier que rien ne dépend de cette modification écrite sur disque avant de
  changer ce comportement.

---

## 4. Risques

| Risque | Mitigation |
|---|---|
| Changement de rendu (espaces, `<X/>`, ordre des préfixes) qui casse des outils tiers faisant du diff textuel | C14N en test ; `ET` préserve l'ordre des attributs et le texte/`tail`, donc le diff textuel reste petit |
| Namespaces réécrits en `ns0:` | Enregistrement des préfixes au chargement (phase 1) et test dédié |
| Mémoire sur de très gros descripteurs | Benchmark en phase 0/2 ; si nécessaire, `iterparse` pour les opérations en lecture seule (phase 5) |
| Scripts utilisateurs qui dépendent d'internes de `Manipulation` | Seules `OperationAbstract`/`FMUPort` sont documentées ; alias dépréciés pour `push_attrs`/`dimensions` ; entrée dans `CHANGELOG.md` |
| XML malveillant (bombe d'entités) | Risque inchangé par rapport à aujourd'hui (même parser expat). libexpat ≥ 2.4.1 protège contre l'expansion exponentielle ; vérifier `pyexpat.version_info` sur les plateformes cibles, ou passer par `defusedxml` |

## 5. Ordre de livraison

Une PR par phase. La phase 0 est mergeable seule et sans risque. Les phases 1 et 2 forment le cœur du changement. Les phases 3
et 4 sont indépendantes l'une de l'autre et peuvent partir en parallèle une fois la phase 1 mergée.

## 6. Notes pour un futur plan

Hors du périmètre de ce refactoring : à reprendre lors de la **prochaine montée de version majeure**.

### Suppression de `FMUPort`

Depuis la phase 2, `FMUPort` n'est plus qu'une sous-classe de `ModelVariable`. Elle n'ajoute que le mode « détaché »,
déprécié : `FMUPort()` sans élément, `push_attrs()` et le setter de `dimensions`. Le nom reste pour l'instant, parce qu'il
fait partie de l'API publique documentée (`python-api.md`, checkers personnalisés) et que `container.py` teste
`isinstance(attrs, FMUPort)`.

À la version majeure :

1. utiliser `ModelVariable` en interne : `isinstance(attrs, ModelVariable)` dans `EmbeddedFMUPort` (`container.py`),
   annotations de type de `fmueditor`, `checker.py` et des opérations intégrées ;
2. présenter `ModelVariable` comme le type de référence dans `python-api.md` ;
3. retirer le mode détaché, `push_attrs()` et le setter de `dimensions` (dépréciés depuis la phase 2) ;
4. réduire `FMUPort` à un alias (`FMUPort = ModelVariable`), avec un `DeprecationWarning` à l'import, puis le supprimer
   dans une version ultérieure ;
5. entrée dans `CHANGELOG.md` (rupture d'API) ; adapter `tests/unit/test_operations_errors.py`, qui teste le mode détaché.
