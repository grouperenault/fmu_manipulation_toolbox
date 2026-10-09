# Audit du serveur MCP (FastMCP)

**Audit** : 3 octobre 2026 — **Vérification de clôture** : 9 octobre 2026 (§8) — **Branche** : `features/mcp`
**Périmètre initial** : `fmu_manipulation_toolbox/gui/fmucontainer/mcp_server.py` (616 l.). Ce fichier n'existe plus : le serveur a
été réorganisé dans le paquet `fmu_manipulation_toolbox/assistant/` (`server.py`, `models.py`, `paths.py`, `auth.py`, `headless.py`,
`fmutools.py`, `knowledge.py`), le bridge Qt est dans `gui/fmucontainer/mcp_bridge.py` et le serveur autonome dans
`cli/fmutool_mcp.py`. Les références `mcp_server.py:NNN` des constats sont historiques ; la colonne « Emplacement actuel » donne
l'endroit où chaque point est traité aujourd'hui.
**Environnement** : audit avec `fastmcp` 4.0.3, Python 3.13.3, macOS ; vérification avec `fastmcp` 4.1.0, Python 3.14.8, macOS.
**Méthode** : lecture de code + exécution réelle du serveur via `fastmcp.Client` en mémoire (inventaire, scénarios, cas d'erreur) + `pytest`.

---

## 1. Synthèse

**État au 9 octobre 2026.** Les 14 étapes du plan d'action (§6) sont réalisées, l'étape 12 partiellement, comme prévu. Le serveur
expose **21 tools annotés, 4 resources, 1 resource template et 3 prompts**. Il démarre sans GUI (`fmutool-mcp`, stdio) ou depuis la
GUI (HTTP, jeton optionnel), et il est couvert par **214 tests**. Les 6 constats bloquants et les 12 importants sont corrigés ; I7 et
I8 le sont partiellement, par choix documenté. Restent ouverts : M4 (accès aux attributs privés dans le bridge Qt), un message vague
du bridge Qt pour M3, l'absence de test dédié pour I11, et un constat nouveau (N3) ; N1 sera résolu par la fusion de la branche
`element-tree` (§8).

**Synthèse initiale (3 octobre 2026).** Le serveur exposait **12 tools, 2 resources, 0 prompt** et pilotait la GUI *Container Builder*
en direct. Le marshalling vers le thread Qt (`MainThreadInvoker`) et l'arrêt d'uvicorn étaient soignés et correctement justifiés.
**Deux scénarios complets d'assemblage ont été exécutés avec succès** (export JSON en 9 appels, build d'un container FMI-2 valide de
93 807 o en 7 appels), et trois messages d'erreur sur quatre se sont révélés réellement actionnables pour un LLM. Les faiblesses
étaient ailleurs : le serveur **n'existait que si la GUI tournait** (pas de point d'entrée, pas de transport stdio), il **n'était
couvert par aucun test**, il **n'appliquait aucun contrôle sur le système de fichiers** — j'ai écrasé par accident un fichier versionné
du dépôt pendant l'audit — et il **acceptait `fmi_version=7` en produisant un FMU corrompu annoncé comme un succès**. Enfin, il ne
couvrait qu'une fraction de la toolbox : rien de `fmutool`, du `Checker` ni de `fmusplit`. Les tools manquaient d'annotations
(`readOnlyHint`/`destructiveHint`), de typage contraint (`Literal`, `Field`) et de bornes sur les sorties.

---

## 2. Constats par sévérité

Les constats sont ceux du 3 octobre ; la colonne « État » est celle de la vérification du 9 octobre.

### 🔴 Bloquant

| # | Constat (3 oct.) | État au 9 oct. | Emplacement actuel |
|---|---|---|---|
| **B1** | **Aucun test.** Aucun fichier `tests/**/*mcp*` ; couverture du serveur = 0. | ✅ **Corrigé** (étape 3) : 214 tests (client en mémoire, bridge headless, bridge Qt, stdio, jeton, outils `fmutool`) | `tests/unit/test_assistant_*.py`, `tests/integration/test_assistant_stdio_server.py`, `tests/gui/test_assistant_qt_bridge.py` |
| **B2** | **Pas de point d'entrée autonome** : démarrage uniquement depuis le menu *AI Assistant On* ; aucun `console_scripts`, aucun transport stdio. | ✅ **Corrigé** (étape 10) : `fmutool-mcp`, stdio par défaut, sans GUI | `cli/fmutool_mcp.py`, `setup.py` |
| **B3** | **Aucun contrôle du système de fichiers** : tout chemin accepté, ni extension ni garde anti-écrasement. **Vérifié en pratique** : `save_as_json` a écrasé `tests/data/containers/bouncing_ball/bouncing.csv` (restauré via `git checkout`). | ✅ **Corrigé** (étape 2) ; revérifié : extension imposée, refus d'écraser sans `overwrite=True`, refus hors de la racine autorisée | `assistant/paths.py` (`PathPolicy`) |
| **B4** | **HTTP local sans authentification** : tout processus de la machine peut piloter la GUI et écrire des fichiers. | ✅ **Corrigé** (étape 13) : jeton partagé opt-in (`--token generate` / `FMUCONTAINER_MCP_TOKEN`), modèle de menace documenté ; stdio supprime le problème pour les clients qui lancent le serveur | `assistant/auth.py`, `cli/fmutool_mcp.py` |
| **B5** | **Pas de `ToolError`** : toute erreur interne fuit brute (`'NoneType' object has no attribute 'list_fmus'` + traceback). | ✅ **Corrigé** (étape 4) ; complété le 9 oct. pour les erreurs de validation d'arguments (N2, §8) | `assistant/server.py` (`_guard`, middleware `ArgumentErrors`) |
| **B6** | **`fmi_version` non validé** : `save_as_fmu(fmi_version=7)` renvoie `OK` et produit un `modelDescription.xml` de **0 octet**. | ✅ **Corrigé** (étape 1) ; revérifié : schéma `enum: [2, 3]`, 7 refusé avant d'atteindre le bridge | `assistant/server.py` (`save_as_fmu`), `assistant/bridge.py` (`SUPPORTED_FMI_VERSIONS`) |

### 🟠 Important

| # | Constat (3 oct.) | État au 9 oct. | Emplacement actuel |
|---|---|---|---|
| **I1** | **Aucune annotation** `readOnlyHint`/`destructiveHint`/`idempotentHint` sur les 12 tools. | ✅ **Corrigé** (étape 4) ; revérifié sur les 21 tools | `assistant/server.py` (`READ_ONLY`, `IDEMPOTENT_WRITE`, `DESTRUCTIVE_WRITE`) |
| **I2** | **Typage trop faible** : `options: Dict[str, Any]`, `fmi_version: int`, aucun `Annotated`/`Field`/`Literal`. | ✅ **Corrigé** (étape 5) | `assistant/models.py` (`ContainerOptions`), `assistant/server.py` |
| **I3** | **Sorties non structurées et non bornées** (`list_fmu_ports` : ni pagination, ni filtre, ni modèle). | ✅ **Corrigé** (étape 6) : modèles Pydantic, filtre par causalité et par motif, pagination | `assistant/models.py` (`FmuPorts`, `Port`) |
| **I4** | **Mauvais partage tools / resources** ; aucune resource templatisée. | ✅ **Corrigé** (étape 7) : `fmu://{name}/ports`, `assembly://current`… | `assistant/server.py` |
| **I5** | **Aucun usage de `Context`**, timeout figé de 60 s. | ✅ **Corrigé** (étape 8) : `report_progress` dans `save_as_fmu`, timeout configurable (`FMUCONTAINER_MCP_TIMEOUT`) | `assistant/server.py` (`save_as_fmu`, `resolve_timeout`) |
| **I6** | **Aucun prompt MCP** ; `USAGE_GUIDE` dupliquait la doc utilisateur. | ✅ **Corrigé** (étape 7) : 3 prompts, source unique (testée) | `assistant/server.py`, `assistant/knowledge.py` |
| **I7** | **Duplication au lieu de réutilisation** de l'API `Assembly`. | ✅ **Partiel, assumé** (étape 10) : le bridge headless s'appuie sur `Assembly` ; le bridge Qt pilote la scène, ce qui est sa raison d'être (l'utilisateur doit *voir* l'agent travailler) | `assistant/headless.py`, `gui/fmucontainer/mcp_bridge.py` |
| **I8** | **Couverture quasi nulle de la toolbox** (`fmutool`, `Checker`, `fmusplit`). | ✅ **Partiel, assumé** (étape 11) : `summarize_fmu`, `check_fmu`, `dump_ports_csv`, `rename_ports_from_csv`, `apply_operation` ; `fmusplit` et le remoting restent hors périmètre | `assistant/fmutools.py` |
| **I9** | **Dépendance `uvicorn` implicite.** | ✅ **Corrigé** (étape 9) | `setup.py` (extra `mcp`), `requirements.txt` |
| **I10** | **Contrat de version flou** (`>= 2.14.0` sans borne, doc « FastMCP 2 »). | ✅ **Corrigé** (étape 9) : `fastmcp >= 4.0.3, < 5`, plus aucune mention « FastMCP 2 » | `setup.py`, `requirements.txt` |
| **I11** | **Échecs de build avalés** : `FMUContainerError` journalisée, chemin renvoyé en succès. | ✅ **Corrigé** (étape 1) : l'erreur est propagée. ⚠️ Aucun test ne vérifie qu'un build raté est signalé comme un échec | `gui/fmucontainer/assembly_io.py` (`save_as_fmu`) |
| **I12** | **Testabilité dégradée par le couplage Qt.** | ✅ **Corrigé** (étapes 3 et 10) : le bridge headless se teste sans Qt ; le bridge Qt a ses propres tests | `assistant/headless.py`, `tests/gui/test_assistant_qt_bridge.py` |

### 🟡 Mineur

| # | Constat (3 oct.) | État au 9 oct. | Emplacement actuel |
|---|---|---|---|
| **M1** | `int(os.environ[...])` au chargement du module : valeur mal formée → `ValueError` à l'import. | ✅ **Corrigé** : lu au démarrage, message clair | `assistant/server.py` (`resolve_port`) |
| **M2** | Sonde `NodeItem` créée puis `del` : ne garantit pas la libération d'un `QGraphicsItem`. | ➖ **Inchangé, sans impact constaté** : la sonde n'est jamais ajoutée à une scène, Python la libère | `gui/fmucontainer/mcp_bridge.py` (`_inspect_fmu_file_impl`) |
| **M3** | FMU identifiées par *basename* : ambigu si deux fichiers homonymes. | ⚠️ **Partiel** : le bridge headless refuse un second fichier homonyme avec un message explicite ; le bridge Qt le refuse aussi, mais avec un message hésitant (« could not be added (already present?) ») | `assistant/headless.py`, `gui/fmucontainer/mcp_bridge.py` (`_add_fmu_impl`) |
| **M4** | Accès intensif aux attributs privés d'autres classes. | ❌ **Ouvert** : 6 accès restants (`fmu_detail._current_node`, `_load_from_node`, `wire_detail._wire`, `_load_from_wire`, import de `_NodeTreeModel`) | `gui/fmucontainer/mcp_bridge.py` |
| **M5** | Docstrings mono-ligne : ni préconditions, ni exemples, ni « quand utiliser ». | ✅ **Corrigé** (étape 5) : docstrings et descriptions de champs détaillées, visibles dans le schéma | `assistant/server.py` |
| **M6** | `list_fmu_ports` mélange deux intentions (FMU du canvas **ou** fichier disque). | ✅ **Corrigé** : `list_fmu_ports` (assemblage) et `inspect_fmu_file` (disque) séparés | `assistant/server.py` |
| **M7** | Doc client incomplète (JetBrains + VS Code seulement). | ✅ **Corrigé** (étape 14) : Claude Desktop, VS Code, JetBrains, limites connues | `docs/user-guide/fmucontainer/ai-assistant.md` |
| **M8** | `list_fmu_ports` fusionne `input` et `parameter`, exclut les `local`, les `outputs` sans `causality` ni `start`. | ✅ **Corrigé** (étape 6) : chaque port avec sa causalité, sa variabilité, son type, son unité, son `start` | `assistant/models.py` (`Port`) |

### ✅ Points conformes (3 oct., toujours vrais le 9 oct.)
Nommage `verbe_objet` cohérent · une intention par tool (M6 corrigé depuis) · `outputSchema` généré pour tous les tools (12, puis 21) · marshalling thread-safe documenté · arrêt gracieux puis forcé d'uvicorn · pré-vérification du port avec `SO_REUSEADDR` · erreurs remontées sur le thread principal · messages de validation métier réellement actionnables (S8 ci-dessous). Ces points sont aujourd'hui dans `gui/fmucontainer/mcp_bridge.py` (`MainThreadInvoker`, démarrage et arrêt du serveur HTTP).

---

## 3. Couverture

| Fonctionnalité | Exposée via MCP (3 oct.) | Utilité agent | Recommandation | État au 9 oct. |
|---|---|---|---|---|
| Assembler un container | **Oui** | Haute | Conserver ; durcir types + annotations | ✅ |
| Introspecter les ports d'une FMU | **Partiel** (M8) | Haute | Enrichir, filtrer, paginer | ✅ `list_fmu_ports`, `inspect_fmu_file` |
| Relire l'assemblage | Oui | Haute | Doubler en resource | ✅ `assembly://current` |
| `OperationSummary` | **Non** | Haute | À exposer | ✅ `summarize_fmu` |
| `Checker` / validation XSD | **Non** | Haute | À exposer | ✅ `check_fmu` |
| `OperationSaveNamesToCSV` | **Non** | Haute | À exposer | ✅ `dump_ports_csv` |
| `OperationRenameFromCSV` | **Non** | Moyenne | À exposer | ✅ `rename_ports_from_csv` |
| Regexp / TrimUntil / TopLevel | **Non** | Moyenne | Tool `apply_operation` paramétré | ✅ `apply_operation` (⚠️ N1, §8) |
| `fmusplit` | **Non** | Moyenne | À exposer | ➖ Hors périmètre (I8) |
| Lecture assemblage JSON/CSV/SSP | **Non** | Moyenne | `read_assembly(path)` | ➖ Reporté, limite documentée (§7) |
| Sous-containers imbriqués | **Non** | Moyenne | Manque structurant | ➖ Reporté, limite documentée (§7) |
| `remove_link` / `unset_start_value` | **Non** | Moyenne | Ajouter | ✅ (+ `add_links` en lot) |
| Terminals / LS-BUS | **Non** (lecture seule) | Moyenne | Documenter la limite | ✅ terminaux lus par `list_fmu_ports` |
| Remoting / frontend win32-64 | **Non** | Faible | Laisser au CLI | ➖ Laissé au CLI |
| `datalog2pcap` | **Non** | Faible | Laisser au CLI | ➖ Laissé au CLI |

---|---|---|---|
| Assembler un container | **Oui** | Haute | Conserver ; durcir types + annotations |
| Introspecter les ports d'une FMU | **Partiel** (M8) | Haute | Enrichir, filtrer, paginer |
| Relire l'assemblage | Oui | Haute | Doubler en resource |
| `OperationSummary` | **Non** | Haute | À exposer (`operations.py:872`) |
| `Checker` / validation XSD | **Non** | Haute | À exposer (`checker.py:78`) |
| `OperationSaveNamesToCSV` | **Non** | Haute | À exposer (`operations.py:698`) |
| `OperationRenameFromCSV` | **Non** | Moyenne | À exposer (`operations.py:769`) |
| Regexp / TrimUntil / TopLevel | **Non** | Moyenne | Tool `apply_operation` paramétré |
| `fmusplit` | **Non** | Moyenne | À exposer (`split.py:110`) |
| Lecture assemblage JSON/CSV/SSP | **Non** | Moyenne | `read_assembly(path)` |
| Sous-containers imbriqués | **Non** | Moyenne | Manque structurant |
| `remove_link` / `unset_start_value` | **Non** | Moyenne | Ajouter (seuls les `add_*` existent) |
| Terminals / LS-BUS | **Non** (lecture seule) | Moyenne | Documenter la limite |
| Remoting / frontend win32-64 | **Non** | Faible | Laisser au CLI |
| `datalog2pcap` | **Non** | Faible | Laisser au CLI |

---

## 4. Scénarios

Exécutés via `fastmcp.Client` en mémoire, vrai `MainThreadInvoker`, boucle Qt active (`QT_QPA_PLATFORM=offscreen`),
données `tests/data/containers/bouncing_ball/`.

| # | Scénario | Résultat (3 oct.) | Appels | Blocage (3 oct.) | Rejoué le 9 oct. |
|---|---|---|---|---|---|
| **S1** | Assembler 2 FMU + export JSON | **Va au bout.** JSON correct | **9** | Aucun | ✅ Va au bout (bridge headless) ; un second export sans `overwrite=True` est refusé |
| **S2** | Construire le container `.fmu` FMI-2 | **Va au bout.** 93 807 o, `fmiVersion="2.0"` | **7** | Aucun | ✅ Va au bout : 93 770 o |
| **S3** | Inspecter entrées/sorties d'une FMU hors canvas | **Partiel** : paramètres mêlés aux entrées, locals absents | 1 | Infos insuffisantes | ✅ `inspect_fmu_file` : chaque causalité, unité, `start`, description |
| **S4** | Renommer des ports depuis un CSV | ❌ Bloque immédiatement | 0 | `OperationRenameFromCSV` non exposée | ✅ `rename_ports_from_csv` (tests unitaires) |
| **S5** | Retirer les variables locales | ❌ Bloque immédiatement | 0 | Aucun tool `fmutool` | ✅ `apply_operation` (`remove_regexp` + `causality=["local"]`) ; non rejoué, filtrage par causalité couvert par les tests unitaires |
| **S6** | Vérifier la conformité d'une FMU | ❌ Bloque immédiatement | 0 | `Checker` non exposé | ✅ `check_fmu` exécuté : conforme FMI-2.0 |
| **S7** | Comparer deux versions d'une FMU | ❌ Impossible | 0 | Ni dump CSV, ni summary, ni diff | ✅ Possible : `summarize_fmu` + `dump_ports_csv` (la comparaison reste à faire par l'agent) |
| **S8** | Gestion d'erreurs | 3 cas/4 corrects | 4 | 1 corruption silencieuse | ✅ 4 cas/4 corrects (détail ci-dessous) |

**Détail S8 (sorties réelles)**

| Cas | Résultat observé le 3 oct. | Verdict | Résultat observé le 9 oct. |
|---|---|---|---|
| `add_link` port inexistant | `ToolError: ... 'nope' is not an output of 'bb_velocity.fmu'.` | ✅ actionnable | `'nope' is not a port of 'bb_velocity.fmu'.` ✅ |
| `list_fmu_ports('ghost.fmu')` | `ToolError: ... is neither loaded nor a valid file path.` | ✅ actionnable | Refusé avec le nom du fichier ✅ |
| option inconnue | `ToolError: Unknown container option(s): ['stepsize']. Allowed: [...]` | ✅ excellent | Avant correction : texte Pydantic brut avec lien de documentation (N2). Après : `unknown option 'stepsize' (allowed: auto_input, …, step_size, ts_multiplier)` ✅ |
| `save_as_fmu(fmi_version=7)` | `OK` + archive au `modelDescription.xml` vide | ❌ **B6** | Refusé avant le bridge : `'fmi_version': Input should be 2 or 3 (got 7)` ✅ |

**Note méthodologique** — un premier harnais utilisant un invoker « direct » produisait un assemblage vide. Vérification faite,
**FastMCP exécute les tools synchrones dans un `AnyIO worker thread`** (`TOOL THREAD: AnyIO worker thread main=False`) : ce n'était pas un
bug produit mais un artefact de test, et cela **valide** le design du `MainThreadInvoker`.

**Manques / redondances / calibrage** (3 oct. → 9 oct.)
- *Manques* : `remove_link` ✅, `unset_start_value` ✅, sous-containers ➖ reporté, chargement d'un assemblage existant ➖ reporté,
  annulation ➖ non traitée.
- *Redondances* : `get_assembly_json` ≡ `assembly://current` (acceptable) ; `USAGE_GUIDE` dupliquait la doc utilisateur → ✅ source
  unique, testée.
- *Trop pauvres* : `add_fmu` ne renvoyait que le nom → ✅ renvoie une fiche (version FMI, générateur, ports par causalité) ;
  `remove_fmu` renvoyait `True` constant → ✅ renvoie les liens supprimés.
- *Non bornés* : `list_fmu_ports` → ✅ paginé ; `get_assembly_json` ➖ inchangé (la taille dépend de l'assemblage, pas d'une FMU).
- *Volumétrie d'appels* : pas de câblage en lot → ✅ `add_links`.

---

## 5. Recommandation sur les skills

**Le savoir-faire doit vivre dans le serveur, pas dans le dépôt.** La contrainte « utilisable par n'importe quel client MCP » disqualifie
`SKILL.md` et `.github/copilot-instructions.md` comme support principal : ils ne suivraient pas un utilisateur connecté depuis Claude
Desktop, Cline ou un agent maison.

| Support | Portable ? | Verdict |
|---|---|---|
| Docstrings de tools | ✅ | **Socle obligatoire** (trop pauvre le 3 oct., cf. M5 ; enrichi depuis) |
| **Prompts MCP** (`@mcp.prompt`) | ✅ | ✅ **Priorité 1** — voyagent avec le serveur |
| Resources MCP | ✅ | ✅ Bon pour la *référence* FMI, pas pour la procédure |
| Skills (`SKILL.md`) | ❌ Claude/Agent Skills | ⚠️ Complément seulement |
| `copilot-instructions.md` / prompt files | ❌ | ⚠️ Utile pour *contribuer* à fmutool, pas pour l'utilisateur final |

**Stratégie retenue, en 3 couches :**
1. Enrichir docstrings + annotations (coût faible, 100 % portable).
2. Exposer 3 prompts MCP reprenant `USAGE_GUIDE` : `build_container`, `diagnose_assembly`, `inspect_fmu`.
3. Ajouter 2 resources de référence : `fmi://conventions`, `container://options`.

**Les skills ne se justifient que** pour des workflows multi-outils dépassant le MCP (MCP + CLI `fmutool` + `fmpy` pour valider par
simulation). Elles restent alors un **sur-ensemble** des prompts, jamais un substitut.

| P | Skill | Objectif | Déclencheur | Tools |
|---|---|---|---|---|
| 1 | `build-fmu-container` | Assembler N FMU en un container valide | « combine/assemble ces FMU » | `add_fmu`, `list_fmu_ports`, `add_link`, `expose_*`, `set_container_options`, `get_assembly_json`, `save_as_fmu` |
| 2 | `diagnose-container-assembly` | Expliquer un build qui échoue | « le container ne marche pas » | `get_assembly_json`, `list_fmu_ports`, `set_container_options` |
| 3 | `inspect-fmu` | Fiche d'identité d'une FMU | « que contient cette FMU ? » | `inspect_fmu_file`, `summarize_fmu`, `check_fmu` |

<details>
<summary>Ébauche <code>build-fmu-container/SKILL.md</code> (mise à jour le 9 octobre 2026)</summary>

```markdown
---
name: build-fmu-container
description: >
  Assemble several FMUs into a single FMU Container using the FMU Manipulation
  Toolbox MCP server (fmucontainer). Use when the user wants to combine, merge,
  co-simulate or package multiple .fmu files together, or to export/build a
  container FMU. Works with the standalone `fmutool-mcp` server or with the
  Container Builder GUI (AI Assistant On).
---

# Build an FMU Container

## Preconditions
- The `fmutool` MCP server must be reachable. If tools are unavailable, tell the
  user to configure `fmutool-mcp` in the client, or to launch `fmucontainer-gui` and
  enable **Configuration -> AI Assistant On**.
- With the GUI server, actions are applied to the **live GUI** and are immediately
  visible to the user.

## Workflow
1. **Inventory** - `list_fmus`. Never assume the canvas is empty.
2. **Add** - `add_fmu(path)` per file. FMUs are identified afterwards by their
   **base name** (`controller.fmu`), not their full path. Refuse to continue if two
   different files share the same base name: ask the user to rename one.
3. **Introspect** - `list_fmu_ports(fmu)` for every FMU *before* wiring. Each port
   comes with its `causality`; filter by causality or name pattern, and page through
   large FMUs with `offset`/`limit`.
4. **Route** - `auto_link` is **on by default** and already connects ports sharing
   name and type. Only call `add_link` for ports whose names differ. Connect an
   OUTPUT to an INPUT; numeric conversions are applied but may be lossy, and
   real<->boolean is a red flag worth confirming.
5. **Boundary** - rely on `auto_input`/`auto_output` by default. Use
   `expose_input`/`expose_output` only when auto-exposure is disabled or when the
   user asks for a specific container interface.
6. **Initial values** - `set_start_value(fmu, port, value)`. Values are strings:
   `"true"`/`"false"` for booleans, `"0.01"` for reals.
7. **Options** - `set_container_options`. Accepted keys only: `step_size`, `mt`,
   `profiling`, `sequential`, `auto_link`, `auto_input`, `auto_output`,
   `auto_parameter`, `auto_local`, `ts_multiplier`. Leave `step_size` unset to let
   the toolbox derive it from the embedded FMUs; never invent a value.
8. **Review** - `get_assembly_json`, summarise FMUs/links/exposed ports/options.
   **Stop and ask for confirmation.**
9. **Build** - `save_as_fmu(path, fmi_version=2|3)`.
   - `fmi_version` is 2 or 3 (any other value is rejected).
   - `save_as_fmu` and `save_as_json` refuse to replace an existing file: ask the
     user before calling them again with `overwrite=True`. Never write inside a
     source or data directory.
10. **Verify** - restate the output path and the options actually used.

## Red flags
- An embedded input neither linked nor exposed stays at its start value: mention it.
- A port the user names but absent from `list_fmu_ports`: do not guess, ask.
- A failed build is reported as an error: never announce a container that was not built.
```
</details>

---

## 6. Plan d'action priorisé

Chaque étape est indépendante et dimensionnée pour une PR.

| # | PR | Contenu | Corrige | Effort | État |
|---|---|---|---|---|---|
| **1** | `fix(mcp): valider fmi_version` | `fmi_version: Literal[2, 3]` ; propager l'échec de `make_fmu` au lieu de renvoyer un succès. | B6, I11 | XS | ✅ fait |
| **2** | `fix(mcp): sécuriser les écritures` | Vérifier l'extension (`.json`/`.fmu`), refuser d'écraser sans `overwrite=True`, normaliser/résoudre les chemins, racine autorisée configurable. | B3 | S | ✅ fait |
| **3** | `test(mcp): premiers tests client en mémoire` | Fixture `QApplication` + boucle Qt + thread client ; couvrir inventaire, S1, S2 et les 4 cas d'erreur. Marqueur `gui`. | B1, I12 | M | ✅ fait |
| **4** | `feat(mcp): ToolError + annotations` | `ToolError` avec messages actionnables ; `readOnlyHint` sur les `list_*`/`get_*`, `destructiveHint` sur `remove_fmu`/`save_as_*`, `idempotentHint` sur `expose_*`/`set_*`. | B5, I1 | S | ✅ fait |
| **5** | `feat(mcp): typage strict des entrées` | `Annotated`/`Field` avec descriptions ; `ContainerOptions` en modèle Pydantic au lieu de `Dict[str, Any]`. | I2 | S | ✅ fait |
| **6** | `feat(mcp): sorties structurées et bornées` | Modèles Pydantic pour les ports ; filtre `causality`/regex + pagination sur `list_fmu_ports` ; exposer aussi `parameter` et `local` distinctement. | I3, M8 | M | ✅ fait |
| **7** | `feat(mcp): prompts et resources de référence` | 3 prompts (`build_container`, `diagnose_assembly`, `inspect_fmu`) ; resources `fmi://conventions`, `container://options`, `fmu://{name}/ports` ; `USAGE_GUIDE` devient la source unique. | I4, I6 | M | ✅ fait |
| **8** | `feat(mcp): progression et journalisation` | Injection de `Context` ; `ctx.info()` + `report_progress()` dans `save_as_fmu` ; timeout paramétrable. | I5 | S | ✅ fait (`report_progress` avec message : la *logging capability* du SDK est dépréciée depuis SEP-2577) |
| **9** | `chore(mcp): packaging` | Déclarer `uvicorn` dans l'extra `mcp` ; borner `fastmcp >= 2.14, < 5` ; aligner code et doc sur la version réellement supportée. | I9, I10 | XS | ✅ fait |
| **10** | `feat(mcp): serveur autonome stdio` | Extraire un bridge « headless » au-dessus de l'API `Assembly` ; `console_scripts` `fmutool-mcp` ; transport stdio ; mode GUI conservé. | B2, I7 | L | ✅ fait |
| **11** | `feat(mcp): exposer fmutool et le checker` | `summarize_fmu`, `check_fmu`, `dump_ports_csv`, `rename_ports_from_csv`, `apply_operation`. | I8, S4-S7 | M | ✅ fait |
| **12** | `feat(mcp): compléter l'édition d'assemblage` | `remove_link`, `unset_start_value`, `read_assembly(path)`, sous-containers, `add_links` en lot. | §4 manques | M | ✅ partiel : `remove_link`, `unset_start_value` et `add_links` livrés ; `read_assembly` et les sous-containers restent non couverts et sont désormais documentés comme limites connues |
| **13** | `chore(mcp): sécuriser le transport` | Jeton partagé ou socket Unix ; documenter le modèle de menace. | B4 | M | ✅ fait : jeton partagé opt-in sur HTTP + modèle de menace documenté. Le socket Unix n'a pas été retenu : l'étape 10 a rendu stdio disponible, ce qui supprime le problème à la racine pour les clients qui lancent le serveur |
| **14** | `docs(mcp): mettre à jour le guide` | Exemple Claude Desktop (après l'étape 10), limites connues, tableau des annotations. | M7 | XS | ✅ fait |

**Ordre conseillé** : 1 → 2 → 3 (sécurisation et filet de test), puis 4 → 5 → 6 → 7 (qualité d'interface agent),
puis 9 → 8, puis 10 (refonte structurante) et enfin 11 → 12 → 13 → 14.

Les constats mineurs M1 à M8 n'avaient pas d'étape dédiée ; leur état est donné au §2 (M2 inchangé sans impact, M3 partiel,
M4 ouvert). Les constats nouveaux de la vérification de clôture sont au §8.

## 7. Reste à faire

Les deux manques identifiés au §4 qui n'ont pas été traités, et pourquoi :

| Manque | Pourquoi reporté |
|---|---|
| **Sous-containers** (assemblages hiérarchiques) | Le protocole `AssemblyBridge` décrit un container plat. Les supporter demande un modèle d'arbre côté bridge *et* côté GUI (la scène Qt n'a pas de notion de sous-container pilotable par un agent). À traiter comme une évolution produit, pas comme un correctif d'interface. |
| **`read_assembly(path)`** | Charger un `.json` existant écraserait l'assemblage courant — destructif et sans undo côté MCP. Nécessite au minimum une sémantique explicite (remplacer / fusionner) et une confirmation. |

Les deux sont annoncés dans la section « Known limits » du guide utilisateur et dans le `guide://usage` servi aux agents, afin qu'un assistant ne promette pas ce qu'il ne peut pas faire.

Points encore ouverts après la vérification du 9 octobre 2026 :

| Point | Nature | Proposition |
|---|---|---|
| **M4** — accès aux attributs privés dans le bridge Qt | Fragilité : un renommage dans `details/` ou `tree/` casserait le bridge sans erreur à l'import | Exposer de petites méthodes publiques (`show_node`, `refresh_wire`…) dans les panneaux de détail et les utiliser depuis le bridge |
| **M3** — message du bridge Qt pour un fichier homonyme | « could not be added (already present?) » : le bridge ne sait pas pourquoi `add_node` a refusé | Vérifier l'homonymie dans le bridge avant d'appeler la scène, avec le même message que le bridge headless |
| **I11** — pas de test d'un build raté | La propagation de l'erreur existe, mais une régression passerait inaperçue | Test du bridge Qt et du bridge headless où `make_fmu` lève `FMUContainerError` : le client doit recevoir une erreur, pas un chemin |
| **N1** — `apply_operation` peut écrire une FMU invalide | Voir §8 | Corrigé sur la branche `element-tree` : résolu à sa fusion |
| **N3** — `summarize_fmu` renvoie le chemin d'un répertoire temporaire supprimé | Bruit inutile pour l'agent | Retirer la ligne `temporary directory` du rapport renvoyé par le tool |

---

## 8. Vérification de clôture (9 octobre 2026)

**Méthode.** Le serveur réel (`build_server` + bridge headless, racine confinée à un répertoire temporaire) est piloté par
`fastmcp.Client` en mémoire, comme lors de l'audit : inventaire, scénarios S1, S2, S3, S6, S8, outils d'édition et outils
`fmutool`, resources et prompts. Les constats ont ensuite été vérifiés dans le code un par un (§2), et les 214 tests du serveur
ont été exécutés.

**Inventaire constaté.** 21 tools, tous annotés et dotés d'un schéma de sortie : 6 en lecture seule (`list_fmus`,
`list_fmu_ports`, `inspect_fmu_file`, `get_assembly_json`, `summarize_fmu`, `check_fmu`), 7 écritures idempotentes, 8 écritures
destructives. 4 resources (`guide://usage`, `fmi://conventions`, `container://options`, `assembly://current`), 1 resource template
(`fmu://{name}/ports`), 3 prompts (`build_container`, `diagnose_assembly`, `inspect_fmu`).

**Constats nouveaux.**

| # | Constat | État |
|---|---|---|
| **N1** | `apply_operation(operation="keep_only_regexp", argument="nothing")` renvoie `OK` et écrit une FMU dont `<ModelVariables>` est vide, ce que le XSD FMI interdit : une FMU invalide annoncée comme un succès, comme B6. Cause : `fmutool` lui-même (défaut D10 de `docs/refactoring.md`), pas le serveur MCP. | Corrigé sur la branche `element-tree` : l'opération est refusée (`OperationError`, transmise au client comme erreur actionnable). **Résolu à la fusion de cette branche.** |
| **N2** | Depuis le typage strict (étape 5), Pydantic rejette les arguments invalides *avant* l'outil, et FastMCP renvoie le texte brut (« 1 validation error for call[…] », code d'erreur, lien vers la documentation Pydantic). Le message « Unknown container option(s): … Allowed: […] », jugé excellent en S8, n'était plus produit. | ✅ **Corrigé le 9 octobre** : un middleware FastMCP (`ArgumentErrors`) reformule toute erreur de validation d'arguments, pour les 21 tools : option ou argument inconnu avec la liste des valeurs admises (lue dans le schéma de l'outil), argument manquant, valeur hors contrainte. 7 tests ajoutés (`tests/unit/test_assistant_server.py`). |
| **N3** | Le rapport de `summarize_fmu` contient `temporary directory = …`, le chemin d'un répertoire déjà supprimé quand l'agent le lit. | Ouvert, mineur (§7). |

**Conclusion.** Le plan d'action est réalisé. L'audit peut être clos une fois la branche `element-tree` fusionnée (N1). Les
points ouverts (M4, M3 côté Qt, test d'I11, N3) sont des améliorations de robustesse, sans risque pour l'utilisateur.

