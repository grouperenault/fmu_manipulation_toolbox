# Plan: optimize the MCP server for the context window

**Created**: 10 October 2026 — **Updated**: 10 October 2026 (decisions D1 to D5 taken) — **Status**: not started

The MCP server (`fmu_manipulation_toolbox/assistant/`, `fmutool-mcp` and the AI Assistant of the Container Builder)
is meant to work with any MCP client, including local models (Qwen, Llama, Mistral...) served by Ollama or LM Studio.
Their usable context is often small: Qwen2.5 and Qwen3 have a native window of about 32k tokens, and local
runtimes frequently start with a smaller one (`num_ctx`, of the order of 4k to 8k by default depending on the
version). Everything the server sends stays in the conversation: the tool definitions at every request, and every
tool result in the history.

---

## 1. Current state

### Measurements (10 October 2026)

Server built with `build_server(HeadlessAssemblyBridge())`, called through an in-memory FastMCP client. Synthetic FMI-2
FMU of 5000 variables (a quarter of each causality, hierarchical names, a unit and a description each), the size of
industrial FMUs; the test FMUs of `tests/data` have 49 variables at most. Tokens counted with `cl100k_base` (same
order of magnitude as the Qwen tokenizer).

| Item | Size |
|---|---|
| 21 tool definitions (name, description, input schema), sent with every request | ~4.8k tokens; ~7.7k with the output schemas |
| Largest definitions | `list_fmu_ports` ~1.1k, `inspect_fmu_file` ~1.0k (output schema included), `set_container_options` ~0.7k |
| Server instructions | none |
| `list_fmu_ports`, default page (100 ports) | ~5k tokens (~50 tokens per port) |
| `list_fmu_ports`, `limit=1000` (maximum allowed) | ~49k tokens |
| `check_fmu`, compliant FMU | ~50 tokens |
| **`check_fmu`, FMU with 2501 errors** (inputs and parameters without start value) | **~72k tokens**: the `errors` list is not bounded |
| `add_fmu`, `summarize_fmu`, `get_assembly_json` | < 300 tokens |
| Resources `guide://usage`, `fmi://conventions`, `container://options` | ~1.0k, ~0.5k, ~0.4k, read on demand |

The results are returned twice by FastMCP, as text `content` and as `structuredContent` (about 25 % larger); a
client normally gives one of them to the model.

### Findings

| # | Finding | Location |
|---|---|---|
| C1 | `check_fmu` returns every error and warning: one non-compliant industrial FMU fills a 32k window by itself (72k tokens measured) | `assistant/fmutools.py`, `check_fmu` |
| C2 | A port costs ~50 tokens; the default page (100) costs ~5k tokens and the maximum (`limit` up to 1000) ~49k | `assistant/server.py` (`Limit`, `_as_ports_page`), `models.py` (`DEFAULT_PORT_LIMIT`, `Port`) |
| C3 | Absent attributes are serialized as `null` (`"variability": null`), and the description is returned in full, whatever its length | `models.py`, `Port` |
| C4 | The tool definitions cost ~4.8k tokens at every request: more than a whole 4k window; the port tools repeat long descriptions | `assistant/server.py` |
| C5 | All 21 tools are always exposed, although a session usually needs either the assembly tools (15) or the single-FMU tools (6). *Kept by D4 (a)* | `assistant/server.py` |
| C6 | Nothing tells the user that a local model needs a larger context; a truncated context fails silently (the runtime drops the beginning of the conversation: tools, instructions) | `docs/user-guide/fmucontainer/ai-assistant.md` |
| C7 | No test bounds the size of the definitions or of the results; only `test_the_default_limit_keeps_the_answer_small` checks the number of ports | `tests/unit/test_assistant_server.py` |

---

## 2. Goals

1. No tool result can exceed a fixed budget with its default arguments, whatever the size of the FMU.
2. A complete assembly session fits in a 16k context with a local model; the tool definitions stay below 4k tokens.
3. The information needed to act is kept: totals, `truncated` flags, how to get the rest.
4. Budgets checked by the tests, so that a new tool or a longer description cannot break them silently.

---

## 3. Decisions

Decided on 10 October 2026: **D1 (b)**, **D2 (b)**, **D3 (c)**, **D4 (a)** (no tool subsets: the 21 tools stay
exposed, the cost of the definitions is reduced by phase 3 only), **D5 (a)**. D6 not decided yet: the plan assumes
its recommendation.


| # | Question | Options | Recommendation |
|---|---|---|---|
| D1 | Bounding `check_fmu` (C1) | (a) the first N errors and warnings, with their totals and `truncated`; (b) (a) plus grouping of the messages of the same rule (quoted names replaced) with a count and a few examples each | **(b)**, N = 50: 2500 "start value is required" errors become one line with a count, which is what the user needs; the full list is available with `fmutool -check` |
| D2 | Port page size (C2) | (a) unchanged (100, max 1000); (b) default 50, max 200; (c) default 25, max 100 | **(b)**: ~2k tokens per default page once C3 is done; the filters (`causality`, `name_pattern`) are the intended way to find a port |
| D3 | Port description (C3) | (a) returned in full; (b) only with a new `details=True` argument; (c) truncated (e.g. 80 characters, with `…`) | **(c)**: the description helps the model to match ports by meaning; truncation bounds its cost without an extra argument to learn |
| D4 | Tool subsets (C5) | (a) always the 21 tools; (b) an option (`--tools assembly|fmu|all`, environment variable for the GUI) | **(b)**, default `all`: a client with a small context can drop 6 or 15 tools |
| D5 | Output schemas of the typed tools | (a) kept; (b) removed from the port tools | **(a)**: they let the clients validate and use `structuredContent`; their cost only counts when the client forwards them, and the descriptions are the larger part |
| D6 | Budgets checked by the tests (C7) | values in characters (no tokenizer dependency; ~4 characters per token for this JSON) | tool definitions ≤ 16k characters (~4k tokens); any result with default arguments on the 5000-variable FMU ≤ 12k characters (~3k tokens) |

---

## 4. Plan

### Phase 0 — Measurement and safety net

1. Test fixture: the synthetic 5000-variable FMU (compliant, and a variant with errors), generated in `tmp_path`.
2. Helper measuring, through the in-memory FastMCP client, the size of the tool definitions and of the results
   (characters; tokens with `tiktoken` when installed, for the record only).
3. Record the baseline (§1) in this plan from the helper; budget tests of D6 written and marked
   `xfail(strict=True)` where the current server exceeds them.

*Exit criterion*: the measurements of §1 reproduced by the helper; suite green.

### Phase 1 — Bounded `check_fmu` (C1, D1)

1. `fmutools.check_fmu`: `errors` and `warnings` limited to N entries, with `error_count`, `warning_count`,
   `truncated`; messages of the same rule grouped (`{"message": ..., "count": ..., "examples": [...]}`).
2. Tool description: how to get the full list (`fmutool -check` in a terminal), never to promise completeness when
   `truncated` is true.
3. Same treatment for the other lists that grow with the FMU, if the measurements of phase 0 find any.

*Exit criterion*: `check_fmu` on the broken FMU within the budget; its `xfail` removed; `compliant` and the totals
unchanged.

### Phase 2 — Compact port pages (C2, C3, D2, D3)

1. `DEFAULT_PORT_LIMIT` and the maximum of `limit` (D2); `Port` serialized without `null` fields; description
   truncated (D3), in `_as_ports_page` (shared by `list_fmu_ports`, `inspect_fmu_file` and `fmu://{name}/ports`).
2. Descriptions of the two port tools shortened, the shared parameter descriptions kept in one place.

*Exit criterion*: default page on the 5000-variable FMU within the budget; the paging tests adapted
(`test_assistant_server.py`); their `xfail` removed.

### Phase 3 — Tool definitions (C4, D5)

1. Shorten the longest descriptions (`list_fmu_ports`, `inspect_fmu_file`, `set_container_options`,
   `apply_operation`, `add_fmu`...) without losing the instructions that prevent mistakes (never guess a port name,
   confirm before writing...); parameter descriptions shared between tools defined once.
2. Output schemas kept (D5).

*Exit criterion*: the 21 tool definitions ≤ 16k characters (name, description, input schema); budget test without
`xfail`.

### Phase 4 — User documentation

- `docs/user-guide/fmucontainer/ai-assistant.md`:
  - "Reading port listings": new page size, compact ports, truncated descriptions;
  - `check_fmu`: bounded and grouped report, full list with `fmutool -check`;
  - new section "Local models": minimum context (16k, 32k recommended), how to raise `num_ctx` in Ollama and the
    context length in LM Studio, symptom of a too small context (the assistant forgets its tools).
- `CHANGELOG.md`: `CHANGED` entries (page size, compact ports, bounded `check_fmu`, shorter tool descriptions).

*Exit criterion*: the documentation gives the numbers of the implementation; `mkdocs build` without warning.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| The model misses information that used to be in the results (a port beyond the page, an error beyond N) | Totals and `truncated` always present; tool descriptions explain how to get the rest (filters, `offset`, `fmutool -check`) |
| Clients relying on the former page size or on the full `errors` list | Breaking for the MCP tools only, documented in `CHANGELOG.md`; the Python API and the CLI are unchanged |
| Budgets measured with a proxy (characters) differ from a given tokenizer | Margins in D6; `tiktoken` measurement recorded for reference |
| The GUI bridge (`mcp_bridge.py`) and the headless bridge diverge | Both go through `_as_ports_page` and `fmutools`; the budget tests use the headless bridge, the GUI tests keep checking the bridge |

## 6. Delivery

One PR per phase; phases 1 and 2 bring most of the gain and can be merged first.
