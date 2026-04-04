# Post LinkedIn — FMU Manipulation Toolbox GUI

## Texte du post

```
🚀 FMU Manipulation Toolbox — now with full GUI support!

Manipulating FMUs shouldn't require writing scripts for every task. That's why we've built 3 dedicated graphical interfaces into FMU Manipulation Toolbox — our open-source Python toolkit for analyzing, modifying, and combining Functional Mock-up Units (FMUs).

🖥️ What's new?

🔹 FMU Tool — Load an FMU, inspect its ports, rename variables, remove hierarchy levels, add remoting interfaces, check FMI compliance… all with a few clicks.

🔹 FMU Variable Editor — A spreadsheet-like interface to rename variables, edit descriptions, and adjust simulation experiment settings (start/stop time). Modified cells are highlighted in real-time.

🔹 FMU Container Builder — A visual node-graph editor to assemble multiple FMUs into a single FMU Container. Drag & drop FMUs, draw wires between ports, configure auto-connect, set start values, organize nested sub-containers — and export as FMU or JSON.

All three tools are accessible from a single launcher: just type `fmutoolbox` in your terminal.

📦 Install in one line:
pip install fmu-manipulation-toolbox

✅ FMI 2.0 & 3.0 supported
✅ Windows, Linux, macOS
✅ CLI + Python API + GUI
✅ Open source (BSD-2-Clause)

👉 Swipe through the carousel to see the interfaces in action ➡️

📖 Full documentation: https://grouperenault.github.io/fmu_manipulation_toolbox/
💻 GitHub: https://github.com/grouperenault/fmu_manipulation_toolbox
📦 PyPI: https://pypi.org/project/fmu-manipulation-toolbox/

#FMI #FMU #Simulation #OpenSource #Python #CoSimulation #Automotive #SystemsEngineering #ModelBasedDesign #RenaultGroup
```

---

## Carrousel (4 slides)

Le carrousel LinkedIn est un PDF où chaque page = 1 slide (format recommandé : **1080 × 1350 px**, portrait 4:5).

### Slide 1 — Couverture

- **Titre :** FMU Manipulation Toolbox
- **Sous-titre :** 3 graphical interfaces to analyze, modify & combine FMUs
- **Visuel :** Logo du projet (`fmu_manipulation_toolbox/resources/fmu_manipulation_toolbox.png`)
- **Pied de page :** `pip install fmu-manipulation-toolbox` · Open Source · FMI 2.0 & 3.0

### Slide 2 — FMU Tool (`fmutool-gui`)

- **Titre :** 🔍 FMU Tool — Analyze & Modify
- **Points clés :**
  - Load any FMU and inspect all ports
  - Rename variables, strip hierarchy levels
  - Remove ports by regex or type
  - Add 32↔64-bit remoting interfaces
  - Check FMI compliance (XSD validation)
  - Export port list to CSV
- **Commande :** `fmutool-gui`
- **Capture d'écran :** `docs/user-guide/fmutool/fmutool-gui.png`

### Slide 3 — FMU Variable Editor (`fmueditor`)

- **Titre :** ✏️ Variable Editor — Edit names & descriptions
- **Points clés :**
  - Drag & drop to load an FMU
  - Editable table: rename variables, edit descriptions
  - Modify start/stop time of DefaultExperiment
  - Filter & sort across all columns
  - Modified cells highlighted in orange
  - Save as new FMU (original never modified)
- **Commande :** `fmueditor`
- **Capture d'écran :** `docs/user-guide/fmutool/fmueditor.png`

### Slide 4 — FMU Container Builder (`fmucontainer-gui`)

- **Titre :** 🔗 Container Builder — Visual FMU assembly
- **Points clés :**
  - Drag & drop FMUs onto a node-graph canvas
  - Draw wires to connect outputs → inputs
  - Auto-connect ports by matching names
  - Configure port mappings & start values
  - Nested sub-containers with tree view
  - Set step size, multi-threading, profiling
  - Export as FMU Container or JSON
- **Commande :** `fmucontainer-gui`
- **Capture d'écran :** `docs/user-guide/fmucontainer/fmucontainer-gui.png`

---

## Conseils de mise en forme

| Paramètre | Valeur recommandée |
|---|---|
| **Format PDF** | 1080 × 1350 px (portrait 4:5) |
| **Nombre de slides** | 4 |
| **Police** | Roboto ou Inter, titre 48pt, corps 24pt |
| **Couleurs** | Fond sombre `#2b2b2b`, accent bleu `#4571a4`, texte `#dddddd` |
| **Logo** | En haut à gauche de chaque slide |
| **Pied de page** | URL GitHub + « Open Source — BSD-2-Clause » |

