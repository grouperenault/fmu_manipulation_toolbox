"""
Mockup of the link assistant with two fictitious FMUs, to try its behaviour without real FMUs.

    python -m fmu_manipulation_toolbox.gui.fmucontainer.details.link_assistant_demo [--ports N] [--seed S]

The FMUs are generated in memory (no `.fmu` file); the names cover the cases the assistant must handle: same name,
case and separators, prefix to replace, regex rewrite, similar names, lossy or impossible type conversion,
different units, arrays, inputs already fed by another wire, parameters, and ports without counterpart.
**Apply** prints the new links on the console and adds them to the table of the main window.
"""

import argparse
import random
import sys

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView,
)

from fmu_manipulation_toolbox.gui.helper import Application
from .link_assistant import LinkAssistantDialog, WireSide
from .link_matching import PortInfo


SUBSYSTEMS = ("intake", "exhaust", "turbo", "injection", "cooling", "lube", "crank", "cam", "egr", "throttle",
              "fuel", "ignition", "knock", "lambda", "boost", "clutch", "gearbox", "alternator")
QUANTITIES = (("speed", "rpm"), ("torque", "N.m"), ("pressure", "bar"), ("temperature", "degC"),
              ("mass_flow", "kg/s"), ("position", "%"), ("voltage", "V"), ("current", "A"), ("angle", "deg"),
              ("ratio", "1"))
ABBREVIATIONS = {"pressure": "press", "temperature": "temp", "position": "pos", "mass_flow": "massflow",
                 "voltage": "volt", "current": "curr"}
OTHER_UNITS = {"degC": "K", "rpm": "rad/s", "bar": "Pa", "deg": "rad"}

NAME_A = "engine.fmu"
NAME_B = "ecu.fmu"


def _signals(count: int, rng: random.Random) -> list[tuple[str, str, str]]:
    """`count` distinct (subsystem, quantity, unit), shuffled."""
    signals = []
    index = 0
    while len(signals) < count:
        for subsystem in SUBSYSTEMS:
            for quantity, unit in QUANTITIES:
                suffix = str(index) if index else ""
                signals.append((subsystem + suffix, quantity, unit))
        index += 1
    rng.shuffle(signals)
    return signals[:count]


def generate(ports: int = 400, seed: int = 1) -> tuple[WireSide, WireSide, list[tuple]]:
    """Two fictitious FMUs: A (`engine.fmu`, FMI 2) and B (`ecu.fmu`, FMI 3), and the existing links of the wire."""
    rng = random.Random(seed)
    a: list[PortInfo] = []
    b: list[PortInfo] = []
    fed_b: set[str] = set()
    fed_a: set[str] = set()

    def out_a(name, unit, description, size=1):
        a.append(PortInfo(name, "output", "Real", 2, unit, description, size))

    def in_b(name, unit, description, fmi_type="Float64", causality="input", size=1):
        b.append(PortInfo(name, causality, fmi_type, 3, unit, description, size))

    signals = iter(_signals(ports * 2, rng))
    shares = {"exact": 0.10, "case": 0.10, "prefix": 0.45, "regex": 0.05, "similar": 0.05}
    counts = {key: max(1, int(ports * share)) for key, share in shares.items()}

    for _ in range(counts["exact"]):
        subsystem, quantity, unit = next(signals)
        name = f"vehicle.{subsystem}_{quantity}"
        out_a(name, unit, f"{quantity} of the {subsystem}")
        in_b(name, unit, f"{quantity} of the {subsystem}")

    for _ in range(counts["case"]):
        subsystem, quantity, unit = next(signals)
        words = [subsystem] + quantity.split("_")
        out_a("Ctrl_" + "_".join(word.capitalize() for word in words), unit, f"{quantity} request of the {subsystem}")
        in_b("ctrl." + ".".join(words), unit, f"{quantity} request of the {subsystem}")

    for k in range(counts["prefix"]):
        subsystem, quantity, unit = next(signals)
        signal = f"{subsystem}_{quantity}"
        out_a(f"engine.out.{signal}", unit, f"{quantity} of the {subsystem} (engine model)")
        fmi_type, unit_b, causality = "Float64", unit, "input"
        if k % 29 == 7:
            fmi_type = "String"
        elif k % 13 == 5:
            fmi_type = "Int32"
        if k % 17 == 3 and unit in OTHER_UNITS:
            unit_b = OTHER_UNITS[unit]
        if k % 23 == 11:
            causality = "parameter"
        name_b = f"ecu.in.engine_{signal}"
        in_b(name_b, unit_b, f"measured {quantity} of the {subsystem}", fmi_type, causality)
        if k % 19 == 2:
            fed_b.add(name_b)

    for _ in range(counts["regex"]):
        subsystem, quantity, unit = next(signals)
        out_a(f"sensor.{subsystem}.{quantity}", unit, f"{quantity} sensor of the {subsystem}")
        in_b(f"sensor_{quantity}_{subsystem}", unit, f"{quantity} sensor of the {subsystem}")

    for _ in range(counts["similar"]):
        subsystem, quantity, unit = next(signals)
        out_a(f"chassis.{subsystem}_{quantity}", unit, f"{quantity} of the {subsystem} (chassis)")
        short = ABBREVIATIONS.get(quantity, quantity[:-1])
        in_b(f"chassis.{subsystem}_{short}", unit, f"{quantity} of the {subsystem} (chassis)")

    # Arrays: A is FMI 2, its arrays are aggregates of scalar ports; B is FMI 3.
    out_a("wheel.speed", "rad/s", "Array aggregate of 4 scalar ports (wheel.speed[1], ...)", size=4)
    in_b("wheel_speed", "rad/s", "speed of the 4 wheels", size=4)
    out_a("wheel.torque", "N.m", "Array aggregate of 4 scalar ports (wheel.torque[1], ...)", size=4)
    in_b("wheel_torque", "N.m", "torque of the front wheels", size=2)

    # Without counterpart.
    remaining = ports - len(a)
    for _ in range(max(remaining, ports // 10)):
        subsystem, quantity, unit = next(signals)
        out_a(f"diag.{subsystem}_{quantity}", unit, f"diagnostic {quantity} of the {subsystem}")
    for _ in range(ports // 10):
        subsystem, quantity, unit = next(signals)
        in_b(f"ecu.cal.{subsystem}_{quantity}", unit, f"calibration of the {quantity} of the {subsystem}",
             causality="parameter")
        in_b(f"ecu.aux.{subsystem}_{quantity}", unit, f"auxiliary {quantity} of the {subsystem}")

    # Direction B → A: commands of the ECU.
    for k in range(ports // 4):
        subsystem, quantity, unit = next(signals)
        signal = f"{subsystem}_{quantity}"
        b.append(PortInfo(f"ecu.out.{signal}_cmd", "output", "Float64", 3, unit, f"{quantity} command"))
        a.append(PortInfo(f"engine.in.{signal}_cmd", "input", "Real", 2, unit, f"{quantity} command"))
        if k % 11 == 4:
            fed_a.add(f"engine.in.{signal}_cmd")

    rng.shuffle(a)
    rng.shuffle(b)
    exact = sorted(port.name for port in a if port.name.startswith("vehicle."))[:3]
    existing = [(NAME_A, name, NAME_B, name) for name in exact]
    return WireSide(NAME_A, a, fed_a), WireSide(NAME_B, b, fed_b), existing


class DemoWindow(QMainWindow):
    """Stands for the Wire Details panel: the links of the wire, and the **Assistant…** button."""

    def __init__(self, side_a: WireSide, side_b: WireSide, existing: list[tuple]):
        super().__init__()
        self._a, self._b = side_a, side_b
        self._mappings = list(existing)
        self._dialog: LinkAssistantDialog | None = None
        self.setWindowTitle("Link assistant mockup")
        self.resize(900, 500)

        title = QLabel(f"{side_a.name} (A) ↔ {side_b.name} (B) — "
                       f"{len(side_a.ports)} ports in A, {len(side_b.ports)} ports in B")
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(["FMU From", "Port From", "FMU To", "Port To"])
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        assistant = QPushButton("Assistant…")
        assistant.setProperty("class", "info")
        assistant.setMinimumWidth(150)
        assistant.clicked.connect(self._on_assistant)
        buttons = QHBoxLayout()
        buttons.addWidget(assistant)
        buttons.addStretch(1)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.addWidget(title)
        lay.addWidget(self._table, 1)
        lay.addLayout(buttons)
        self.setCentralWidget(central)
        self._fill_table()

    def _fill_table(self):
        self._table.setRowCount(len(self._mappings))
        for row, mapping in enumerate(self._mappings):
            for column, value in enumerate(mapping):
                self._table.setItem(row, column, QTableWidgetItem(value))

    def _on_assistant(self):
        if self._dialog is None or not self._dialog.isVisible():
            self._dialog = LinkAssistantDialog(self._a, self._b, self._mappings, self)
            self._dialog.applied.connect(self._on_applied)
            self._dialog.show()
        self._dialog.raise_()
        self._dialog.activateWindow()

    def _on_applied(self, mappings: list[tuple]):
        print(f"Apply: {len(mappings)} links")
        for mapping in mappings:
            print("   ", " ; ".join(mapping))
        self._mappings.extend(mappings)
        self._fill_table()


def main():
    parser = argparse.ArgumentParser(description="Mockup of the link assistant with two fictitious FMUs.")
    parser.add_argument("--ports", type=int, default=400, help="approximate number of ports per FMU (default 400)")
    parser.add_argument("--seed", type=int, default=1, help="random seed of the generated names (default 1)")
    args = parser.parse_args()

    application = Application(sys.argv[:1])
    side_a, side_b, existing = generate(args.ports, args.seed)
    application.window = DemoWindow(side_a, side_b, existing)
    application.window.show()
    sys.exit(application.exec())


if __name__ == "__main__":
    main()
