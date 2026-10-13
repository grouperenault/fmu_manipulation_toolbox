# Reproducible screenshots of the user documentation

## Context

The screenshots of the graphical interfaces were taken by hand (window with the macOS title bar and shadow, one
under Windows). Two of them were outdated after the Link Assistant (`fmucontainer-gui.png` and
`container-vr-gui.png` show **Auto-Connect**), and several sections of the user guide describe an interface
without showing it.

## Decisions (2026-10-13)

| # | Question | Decision |
|---|----------|----------|
| 1 | How to make the screenshots | A reproducible script, rendering the windows without showing them on screen (`WA_DontShowOnScreen`, native style of the platform); no title bar: every interface screenshot is made again by the script, so that they look alike |
| 2 | Location of the script | `tools/screenshots.py` (next to `tools/dist_inventory.py`; not shipped, not run by the tests) |
| 3 | New screenshots | FMU Details panel and wire in red after *Replace FMU*; instances of one FMU and Container Details panel; Configuration menu, context menus of the canvas and of the tree, waypoints; FMU Tool ("Apply only on" menu, result of *Check*); FMU Editor (modified cell, filter) |

Only the interface screenshots are concerned: the diagrams (`FMUContainer.png`, `routing.png`,
`container-json.png`, `container-vr.png`, `ls-bus-container.png`, `datalog.png`, `fmu_manipulation_toolbox.png`)
are kept.

## Step 1 — Script and existing screenshots

`tools/screenshots.py [--only NAME ...] [--list]`: one function per screenshot, run on the FMUs of `tests/data`
copied into a temporary directory (no path of the machine in the images), written at the resolution of the
screen (2× on a Retina display) into `docs/`:

| Screenshot | Scene |
|------------|-------|
| `docs/gui-launcher.png` | Launcher |
| `user-guide/fmutool/fmutool-gui.png` | FMU Tool with `VanDerPol.fmu` |
| `user-guide/fmutool/fmueditor.png` | FMU Editor with `VanDerPol.fmu` |
| `user-guide/fmucontainer/fmucontainer-gui.png` | Container Builder, `arch/hierarchical.json`, a wire selected |
| `user-guide/fmucontainer/container-vr-gui.png` | Container Builder, `VanDerPol/VanDerPol-vr.json`, wire to the `configuration` node |
| `user-guide/fmucontainer/link-assistant-rules.png`, `link-assistant-manual.png` | Link Assistant on the fictitious FMUs of its mockup |

Commit message: `Make the screenshots of the user documentation with a script`

**Result:** `tools/screenshots.py`, one function per screenshot registered with `@shot(name, path)`. Notes:

- the windows calling `show()` in their constructor (launcher, FMU Tool) are built with this call skipped, then
  shown with `WA_DontShowOnScreen`: nothing appears on screen;
- the windows are kept until the end of the script: some install a logging handler writing into one of their
  widgets (the `LogWidget` problem seen in the tests);
- the FMUs are copied into `/tmp/fmutool` (`tempfile.tempdir` set to `/tmp` outside Windows): short, neutral
  paths in the log of FMU Tool;
- the assembly `arch/hierarchical.json` relies on `auto_link`: the script draws its two links (sine → integrate →
  gain) and lays the nodes out in a row, as the former screenshot; for `VanDerPol-vr.json`, the tab B → A
  holding the link to the `configuration` node is shown;
- the Container Builder windows are 1600 × 900 (the canvas is half of it);
- the two Link Assistant screenshots come out identical, byte for byte, to the committed ones.

## Step 2 — New screenshots

| Screenshot | Scene |
|------------|-------|
| `user-guide/fmutool/fmutool-filter.png` | Menu "Apply only on" open, only input and parameter checked (crop) |
| `user-guide/fmutool/fmutool-check.png` | Result of **Check** at the end of the log |
| `user-guide/fmutool/fmueditor-edit.png` | Description of `mu` modified (orange), variables filtered on "m" |
| `user-guide/fmucontainer/fmucontainer-fmu-details.png` | FMU Details of `VanDerPol.fmu`, start value 1.5 on `mu` (crop of the panel) |
| `user-guide/fmucontainer/fmucontainer-invalid-wire.png` | Link to a port `speed` that does not exist: wire and port in red |
| `user-guide/fmucontainer/fmucontainer-instances.png` | Two instances of each bouncing ball FMU, `bb_position-1.fmu` selected |
| `user-guide/fmucontainer/fmucontainer-container-details.png` | Root container selected (crop of the tree and of the panel) |
| `user-guide/fmucontainer/fmucontainer-configuration.png` | Configuration menu open (crop) |
| `user-guide/fmucontainer/fmucontainer-canvas-menu.png` | Context menu of a node (crop of the canvas) |
| `user-guide/fmucontainer/fmucontainer-tree-menu.png` | Context menu of the tree (crop) |
| `user-guide/fmucontainer/fmucontainer-waypoints.png` | Selected wire with a waypoint (crop of the canvas) |

**Result:** the menus built in an event handler and opened by `exec` (canvas, tree) are captured by replacing
`QMenu` in their module by a subclass whose `exec` keeps the menu (replacing `QMenu.exec` itself has no effect
with PySide6); the menus are rendered off screen and drawn over the window at their position. The selection of a
node or of a wire writes the table of the panel into it: the script changes the start values and the links only
once the item is displayed, then reloads the panel. The 18 screenshots are made in 3.5 s (2.9 MB in all).

Commit message: `Add screenshots of the Container Builder, FMU Tool and FMU Editor`

## Step 3 — User documentation

The new screenshots in the pages of the user guide; `mkdocs build --strict`; this plan moved to
`docs/local/done`.

**Result:**

- `fmucontainer/gui-usage.md`: instances (*Adding FMU Nodes*), waypoints, context menus of the canvas and of the
  tree, wire in red (*Replacing an FMU*), FMU Details, Container Details, Configuration menu — whose list now
  gives **AI Assistant On / Off**;
- `fmucontainer/ai-assistant.md`: the Configuration menu; the **Configuration** button is at the bottom left,
  not at the top left as written;
- `fmutool/gui-usage.md`: **Check** and **Apply only on**; `fmutool/fmueditor.md`: modified cell and filter;
- `help/contributing.md`: new section *Screenshots of the documentation*;
- every screenshot of the script is shown by at least one page; `mkdocs build --strict` passes (the notice about
  `#port-style-indicators` was already there).

Seen on the screenshots, not changed: the tabs of the FMU Details panel (Start Values, Input Ports, Output
Ports) have different widths, as the Wire Details ones had before `equal_tabs`.

Commit message: `Show the new screenshots in the user documentation`
