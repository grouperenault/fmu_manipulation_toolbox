# Version 2.0
- [X] switch to ElementsTree to parse XML
- [X] suppress FMUPort (API break)
- [X] modern packaging
- [X] MCP server
- [X] Support ModelExchange
- [X] support multiple instances of an FMU into an Assembly (GUI)
- [X] Harmonize CMakeList.txt from `container` and `remoting` (C23)
- [X] refactor container.py
- [X] Drop python 3.9 support (which is end-of-life)
- [X] Support python 3.14
- [X] Efficient assistant to connect 2 FMUs
- [X] Reset of embedded FMUs during the simulation (`reset_ports`)

# Version 2.1
- [X] Agent skills: Claude Code plugin, `fmutool-agent`, filters by type and variability, `describe_port`
- [X] FMI-LS-BUS up to 1.3.0-rc.1: LIN, FlexRay, Ethernet, all the time-based clocks
- [ ] FMI-LS-BUS 1.3.0 final
- [ ] Export to Simulink