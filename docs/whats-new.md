---
title: What's new in 2.0
description: FMU Manipulation Toolbox 2.0 - AI Assistant, Model-Exchange FMUs in containers, Link Assistant, compilation of the sources and more
---

# What's new in 2.0

Version 2.0 is the biggest release of FMU Manipulation Toolbox so far.

<div class="carousel" markdown>
<div class="carousel-track" markdown>

![Version 2.0: the open-source toolbox to analyse, modify and combine FMUs](assets/release-2.0/slide-01.webp)

![Three tools, one toolbox: FMU Tool, FMU Editor and FMU Container Builder](assets/release-2.0/slide-02.webp){ loading=lazy }

![AI Assistant: let an AI agent build your containers](assets/release-2.0/slide-03.webp){ loading=lazy }

![Model-Exchange FMUs inside containers, advanced by an embedded solver](assets/release-2.0/slide-04.webp){ loading=lazy }

![Link Assistant: link hundreds of ports by rule](assets/release-2.0/slide-05.webp){ loading=lazy }

![The same FMU, several times in one container](assets/release-2.0/slide-06.webp){ loading=lazy }

![No binary for your platform? Compile the sources of the FMU](assets/release-2.0/slide-07.webp){ loading=lazy }

![Safer edits, stricter checks](assets/release-2.0/slide-08.webp){ loading=lazy }

![Install only what you need](assets/release-2.0/slide-09.webp){ loading=lazy }

![Try 2.0 and tell us what you think](assets/release-2.0/slide-10.webp){ loading=lazy }

</div>
</div>

## Highlights

- :material-robot: **AI Assistant** — an [MCP server](user-guide/fmucontainer/ai-assistant.md) lets an AI agent
  (GitHub Copilot, Claude, local models…) inspect FMUs and build containers, in the Container Builder or standalone
  (`fmutool-mcp`).
- :material-cog-sync: **Model-Exchange FMUs in containers** — they are [advanced by an embedded fixed-step
  solver](user-guide/fmucontainer/container.md#model-exchange-support), and can be mixed with Co-Simulation FMUs.
- :material-content-duplicate: **Several instances of the same FMU** in one container, each with
  [its own name](user-guide/fmucontainer/container.md#embedding-the-same-fmu-several-times).
- :material-link-variant: **Link Assistant** — [connect FMUs with hundreds of ports by
  rule](user-guide/fmucontainer/gui-usage.md#link-assistant): same name, prefix or suffix, regular expression,
  similar names; review the proposals, then apply.
- :material-hammer-wrench: **Compilation of the sources** — no binary for your platform? FMU Tool
  [compiles the C sources](user-guide/fmutool/cli-usage.md#compile-sources) embedded in the FMU.
- :material-shield-check: **Safer edits, stricter checks** — `modelDescription.xml` is edited in place, a
  [semantic checker](user-guide/fmutool/checker.md) verifies the rules of FMI 2.0 and 3.0, and the exit codes suit
  continuous integration.
- :material-language-python: **Python 3.10 to 3.14**, and a command line that no longer needs the GUI toolkit.

```bash
pip install "fmu-manipulation-toolbox[gui]"
```

See the [Installation Guide](installation.md) for the other extras.

!!! warning "Breaking changes"
    2.0 contains breaking changes, marked 🔴 **BREAKING** in the changelog: read them before updating your
    scripts, custom operations or checkers.

The full list of changes is in the
[changelog](https://github.com/grouperenault/fmu_manipulation_toolbox/blob/main/CHANGELOG.md){:target="_blank"}.
