"""
Link assistant of the FMU container builder.

Non-modal window helping to define, in bulk, the links of a wire between two FMUs having hundreds of ports:

* tab **Rules**: a matching criterion (same name, prefix / suffix, regex, similar names) proposes links, updated
  while typing, reviewed in a table then staged;
* tab **Manual**: two filtered port lists, the selected outputs are paired with the selected inputs;
* the **staged links**, shared by both tabs, are only written into the wire by **Apply**.

The window only knows `PortInfo` lists (see `link_matching`), not the graph items.
"""

import re
import time
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal, QAbstractTableModel, QModelIndex, QSortFilterProxyModel, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QWidget, QLabel, QComboBox, QTabWidget, QSplitter, QVBoxLayout, QHBoxLayout, QGridLayout,
    QTableView, QHeaderView, QAbstractItemView, QPushButton, QLineEdit, QCheckBox, QFrame, QDoubleSpinBox,
    QStackedWidget, QMessageBox,
)

from .link_matching import (
    PortInfo, Status, Checks, Rule, AffixRule, RegexRule, SimilarityRule, RULE_KINDS, Suggestion, suggest,
    staged_statuses, with_overlaps, OK, WARNING, ERROR,
)


_STATUS_COLORS = {OK: QColor("#7fbf6a"), WARNING: QColor("#e0b050"), ERROR: QColor("#F54927")}
_INVALID_FIELD_STYLE = "border: 1px solid #F54927;"

A_TO_B = "a_to_b"
B_TO_A = "b_to_a"


@dataclass
class WireSide:
    """One end of the wire: its node name, its ports, the inputs already fed outside of this wire (other wires,
    inputs exposed by the container), and its FMI-2 array aggregates (name → element names)."""
    name: str
    ports: list[PortInfo]
    fed: set[str]
    aggregates: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class StagedLink:
    direction: str
    output: PortInfo
    input: PortInfo
    origin: str


def _refilter(proxy: QSortFilterProxyModel):
    """Re-apply the row filter (`invalidateFilter` is deprecated since Qt 6.10, its replacement is Qt 6.9+)."""
    if hasattr(proxy, "beginFilterChange"):
        proxy.beginFilterChange()
        proxy.endFilterChange(QSortFilterProxyModel.Direction.Rows)
    else:
        proxy.invalidateFilter()


# ── Models ──────────────────────────────────────────────────────────────

class _PortsModel(QAbstractTableModel):
    """Ports of one side: Name, Type, Unit, Description. Parameters in italics, arrays in bold."""
    HEADERS = ("Name", "Type", "Unit", "Description")
    ROLE_PORT = Qt.ItemDataRole.UserRole + 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ports: list[PortInfo] = []

    def set_ports(self, ports: list[PortInfo]):
        self.beginResetModel()
        self._ports = list(ports)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._ports)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        port = self._ports[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            if column == 0:
                return f"{port.name} [{port.size}]" if port.size > 1 else port.name
            return (None, port.fmi_type, port.unit, port.description)[column]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{port.name}\n{port.causality}, {port.fmi_type} {port.unit}\n{port.description}"
        if role == Qt.ItemDataRole.FontRole and column == 0:
            if port.causality == "parameter" or port.size > 1:
                font = QFont()
                font.setItalic(port.causality == "parameter")
                font.setBold(port.size > 1)
                return font
        if role == self.ROLE_PORT:
            return port
        return None


class _PortsFilter(QSortFilterProxyModel):
    """Filter on the name / description, the type, the free ports, the parameters, and the ports without a
    suggestion in the Rules tab."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ""
        self.fmi_type = ""
        self.only_free = True
        self.show_parameters = False
        self.only_unsuggested = False
        self.busy: set[str] = set()
        self.suggested: set[str] = set()

    def refresh(self):
        _refilter(self)

    def filterAcceptsRow(self, source_row, source_parent):
        port: PortInfo = self.sourceModel().index(source_row, 0, source_parent).data(_PortsModel.ROLE_PORT)
        if port.causality == "parameter" and not self.show_parameters:
            return False
        if self.only_free and port.name in self.busy:
            return False
        if self.only_unsuggested and port.name in self.suggested:
            return False
        if self.fmi_type and port.fmi_type != self.fmi_type:
            return False
        if self.text:
            text = self.text.lower()
            return text in port.name.lower() or text in port.description.lower()
        return True


class _SuggestionsModel(QAbstractTableModel):
    HEADERS = ("", "Output", "Type", "Input", "Type", "Unit", "Status")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.suggestions: list[Suggestion] = []

    def set_suggestions(self, suggestions: list[Suggestion]):
        self.beginResetModel()
        self.suggestions = list(suggestions)
        self.endResetModel()

    def refresh(self):
        if self.suggestions:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.suggestions) - 1, len(self.HEADERS) - 1))

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.suggestions)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def flags(self, index):
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.column() == 0:
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        suggestion = self.suggestions[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.CheckStateRole and column == 0:
            return Qt.CheckState.Checked if suggestion.checked else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.DisplayRole:
            output, input = suggestion.output, suggestion.input
            if column == 1:
                return output.name
            if column == 2:
                return output.fmi_type
            if column == 3:
                return input.name
            if column == 4:
                return input.fmi_type
            if column == 5:
                return output.unit if output.unit == input.unit else f"{output.unit or '-'} → {input.unit or '-'}"
            if column == 6:
                return str(suggestion.status)
        if role == Qt.ItemDataRole.ForegroundRole and column == 6:
            return _STATUS_COLORS[suggestion.status.level]
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"{suggestion.output.description}\n→ {suggestion.input.description}\n{suggestion.status}"
        return None

    def setData(self, index, value, role=Qt.ItemDataRole.EditRole):
        if role == Qt.ItemDataRole.CheckStateRole and index.column() == 0:
            self.suggestions[index.row()].checked = Qt.CheckState(value) == Qt.CheckState.Checked
            self.dataChanged.emit(index, index)
            return True
        return False


class _StagedModel(QAbstractTableModel):
    HEADERS = ("Direction", "Output", "Input", "Origin", "Status")

    def __init__(self, parent=None):
        super().__init__(parent)
        self.links: list[StagedLink] = []
        self.statuses: list[Status] = []

    def set_links(self, links: list[StagedLink], statuses: list[Status]):
        self.beginResetModel()
        self.links = links
        self.statuses = statuses
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.links)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.HEADERS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADERS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        link = self.links[index.row()]
        status = self.statuses[index.row()]
        column = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            return ("A → B" if link.direction == A_TO_B else "B → A",
                    link.output.name, link.input.name, link.origin, str(status))[column]
        if role == Qt.ItemDataRole.ForegroundRole and column == 4:
            return _STATUS_COLORS[status.level]
        return None


class _LevelFilter(QSortFilterProxyModel):
    """Text filter on every column, and filter on the status level (None = all)."""

    def __init__(self, level_of, parent=None):
        super().__init__(parent)
        self._level_of = level_of
        self.text = ""
        self.level: int | None = None

    def refresh(self):
        _refilter(self)

    def filterAcceptsRow(self, source_row, source_parent):
        if self.level is not None and self._level_of(source_row) != self.level:
            return False
        if self.text:
            model = self.sourceModel()
            text = self.text.lower()
            return any(text in str(model.index(source_row, column, source_parent).data() or "").lower()
                       for column in range(1, model.columnCount()))
        return True


def _level_combo() -> QComboBox:
    combo = QComboBox()
    combo.addItem("All", None)
    combo.addItem("✔ OK", OK)
    combo.addItem("⚠ Warnings", WARNING)
    combo.addItem("✖ Errors", ERROR)
    return combo


def _table(model) -> QTableView:
    table = QTableView()
    table.setModel(model)
    table.setSortingEnabled(True)
    table.sortByColumn(-1, Qt.SortOrder.AscendingOrder)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setAlternatingRowColors(True)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(table.fontMetrics().height() + 8)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
    return table


def _button(text: str, css_class: str) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("class", css_class)
    button.setMinimumWidth(max(button.sizeHint().width() + 16, 120))
    return button


# ── Criterion editor ────────────────────────────────────────────────────

class _CriterionEditor(QWidget):
    """The matching criterion: its kind, its parameters, and the option "ignore case and separators" shared by every
    kind. One rule per kind is kept for the session of the application, so that the parameters of a kind survive a
    switch to another kind and the next opening of the assistant; the editor always opens on "Same name"."""
    changed = Signal()

    _session_rules: list[Rule] | None = None
    _session_ignore_case = True

    def __init__(self, parent=None):
        super().__init__(parent)
        if _CriterionEditor._session_rules is None:
            _CriterionEditor._session_rules = [kind() for kind in RULE_KINDS]
        self._rules = _CriterionEditor._session_rules
        self._kind = QComboBox()
        for rule in self._rules:
            self._kind.addItem(rule.kind)
        self._ignore_case = QCheckBox("ignore case and separators ( . _ - [ ] )")
        self._ignore_case.setChecked(_CriterionEditor._session_ignore_case)
        self._ignore_case.toggled.connect(lambda value: setattr(_CriterionEditor, "_session_ignore_case", value))
        self._pages = QStackedWidget()
        for rule in self._rules:
            self._pages.addWidget(self._parameters(rule))
        self._kind.currentIndexChanged.connect(self._pages.setCurrentIndex)
        self._kind.currentIndexChanged.connect(self.changed)
        self._ignore_case.toggled.connect(self.changed)

        header = QHBoxLayout()
        header.addWidget(QLabel("Match by"))
        header.addWidget(self._kind)
        header.addSpacing(30)
        header.addWidget(self._ignore_case)
        header.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(header)
        lay.addWidget(self._pages)

    def rule(self) -> Rule:
        return self._rules[self._kind.currentIndex()]

    def set_kind(self, kind: type):
        self._kind.setCurrentIndex(RULE_KINDS.index(kind))

    @property
    def ignore_case(self) -> bool:
        return self._ignore_case.isChecked()

    def _parameters(self, rule: Rule) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        if isinstance(rule, AffixRule):
            fields = {}
            for attribute, placeholder in (("from_prefix", "A prefix"), ("from_suffix", "A suffix"),
                                           ("to_prefix", "B prefix"), ("to_suffix", "B suffix")):
                field = QLineEdit(getattr(rule, attribute))
                field.setPlaceholderText(placeholder)
                field.textChanged.connect(lambda text, a=attribute: self._set(rule, a, text))
                fields[attribute] = field
            lay.addWidget(QLabel("A:"))
            lay.addWidget(fields["from_prefix"], 2)
            lay.addWidget(QLabel("…"))
            lay.addWidget(fields["from_suffix"], 1)
            lay.addWidget(QLabel("→  B:"))
            lay.addWidget(fields["to_prefix"], 2)
            lay.addWidget(QLabel("…"))
            lay.addWidget(fields["to_suffix"], 1)
            self.affix_fields = fields
        elif isinstance(rule, RegexRule):
            pattern = QLineEdit(rule.pattern)
            pattern.setPlaceholderText(r"A regex, e.g. ^engine\.out\.(.*)$")
            pattern.textChanged.connect(lambda text: self._on_pattern(rule, pattern, text))
            replacement = QLineEdit(rule.replacement)
            replacement.setPlaceholderText(r"B name, e.g. ecu.in.engine_\1")
            replacement.textChanged.connect(lambda text: self._set(rule, "replacement", text))
            lay.addWidget(QLabel("A:"))
            lay.addWidget(pattern, 3)
            lay.addWidget(QLabel("→  B:"))
            lay.addWidget(replacement, 3)
            self.regex_fields = (pattern, replacement)
        elif isinstance(rule, SimilarityRule):
            threshold = QDoubleSpinBox()
            threshold.setRange(0.5, 1.0)
            threshold.setSingleStep(0.05)
            threshold.setValue(rule.threshold)
            threshold.valueChanged.connect(lambda value: self._set(rule, "threshold", value))
            lay.addWidget(QLabel("score ≥"))
            lay.addWidget(threshold)
            lay.addStretch(1)
        else:
            lay.addWidget(QLabel("An output and an input having the same name."))
            lay.addStretch(1)
        return page

    def _set(self, rule, attribute, value):
        setattr(rule, attribute, value)
        self.changed.emit()

    def _on_pattern(self, rule, field, text):
        try:
            re.compile(text)
            field.setStyleSheet("")
        except re.error:
            field.setStyleSheet(_INVALID_FIELD_STYLE)
        self._set(rule, "pattern", text)


# ── Dialog ──────────────────────────────────────────────────────────────

class LinkAssistantDialog(QDialog):
    """Assistant to define in bulk the links of the wire between *side_a* and *side_b*.

    *existing* holds the current mappings of the wire (4-tuples, as `WireItem.mappings`); they are kept.
    `applied` is emitted with the new 4-tuples (from_fmu, output, to_fmu, input) when the user clicks **Apply**.
    """
    applied = Signal(list)
    #: A search longer than this (seconds) stops the update while typing: the **Run** button is shown instead.
    AUTO_RUN_LIMIT = 0.3

    def __init__(self, side_a: WireSide, side_b: WireSide, existing: list[tuple], parent=None):
        super().__init__(parent)
        self._a = side_a
        self._b = side_b
        self._existing = [tuple(m) for m in existing if len(m) >= 4]
        self._staged: list[StagedLink] = []
        self._statuses: list[Status] = []
        self._checks = Checks()
        self._show_parameters = False
        self._direction = A_TO_B
        self._auto_run = True
        self._suggestions_origin = ""
        self._run_timer = QTimer(self)
        self._run_timer.setSingleShot(True)
        self._run_timer.setInterval(250)
        self._run_timer.timeout.connect(self._on_run)

        self.setWindowTitle(f"Link assistant — {side_a.name} (A) ↔ {side_b.name} (B)")
        self.setModal(False)
        self.resize(1200, 860)

        # -- Header --
        self._direction_combo = QComboBox()
        self._direction_combo.addItem("A → B", A_TO_B)
        self._direction_combo.addItem("B → A", B_TO_A)
        self._direction_combo.currentIndexChanged.connect(self._on_direction_changed)
        self._counter_source = QLabel()
        self._counter_target = QLabel()
        header = QHBoxLayout()
        header.addWidget(QLabel("Direction"))
        header.addWidget(self._direction_combo)
        header.addSpacing(30)
        header.addWidget(self._counter_source)
        header.addSpacing(30)
        header.addWidget(self._counter_target)
        header.addStretch(1)

        # -- Tabs --
        self._tabs = QTabWidget()
        self._tabs.addTab(self._build_rules_tab(), "Rules")
        self._tabs.addTab(self._build_manual_tab(), "Manual")

        # -- Staged links --
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._tabs)
        splitter.addWidget(self._build_staged_panel())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        lay = QVBoxLayout(self)
        lay.addLayout(header)
        lay.addWidget(splitter, 1)

        self._on_direction_changed()

    # ── Building ────────────────────────────────────────────────────

    def _build_rules_tab(self) -> QWidget:
        self._criterion = _CriterionEditor()
        self._criterion.changed.connect(self._schedule_run)

        self._check_type = QCheckBox("compatible type")
        self._check_type.setChecked(self._checks.compatible_type)
        self._check_unit = QCheckBox("same unit")
        self._check_unit.setChecked(self._checks.same_unit)
        self._check_type.toggled.connect(self._on_checks_changed)
        self._check_unit.toggled.connect(self._on_checks_changed)
        self._rules_parameters = QCheckBox("parameters as targets")
        self._rules_parameters.toggled.connect(self._on_show_parameters)
        self._run_button = _button("Run ▶", "quit")
        self._run_button.setToolTip("The last search was too long to be updated while typing")
        self._run_button.clicked.connect(self._on_run)
        self._run_button.hide()

        options = QHBoxLayout()
        options.addWidget(QLabel("Errors (✖):"))
        options.addWidget(self._check_type)
        options.addWidget(self._check_unit)
        options.addSpacing(30)
        options.addWidget(self._rules_parameters)
        options.addStretch(1)
        options.addWidget(self._run_button)

        self._suggestions_model = _SuggestionsModel(self)
        self._suggestions_filter = _LevelFilter(
            lambda row: self._suggestions_model.suggestions[row].status.level, self)
        self._suggestions_filter.setSourceModel(self._suggestions_model)
        self._suggestions_table = _table(self._suggestions_filter)
        self._suggestions_table.setColumnWidth(0, 30)
        for column, width in ((1, 280), (2, 70), (3, 280), (4, 70), (5, 90)):
            self._suggestions_table.setColumnWidth(column, width)
        self._suggestions_table.doubleClicked.connect(self._on_suggestion_double_clicked)

        self._suggestions_summary = QLabel()
        self._unmatched_link = QLabel()
        self._unmatched_link.setTextFormat(Qt.TextFormat.RichText)
        self._unmatched_link.setToolTip("Show these ports in the Manual tab")
        self._unmatched_link.linkActivated.connect(self._on_unmatched_clicked)
        suggestions_level = _level_combo()
        suggestions_level.currentIndexChanged.connect(
            lambda: self._set_filter(self._suggestions_filter, level=suggestions_level.currentData()))
        suggestions_text = QLineEdit()
        suggestions_text.setPlaceholderText("Filter")
        suggestions_text.textChanged.connect(lambda text: self._set_filter(self._suggestions_filter, text=text))
        suggestions_header = QHBoxLayout()
        suggestions_header.addWidget(self._suggestions_summary)
        suggestions_header.addSpacing(20)
        suggestions_header.addWidget(self._unmatched_link)
        suggestions_header.addStretch(1)
        suggestions_header.addWidget(QLabel("Show"))
        suggestions_header.addWidget(suggestions_level)
        suggestions_header.addWidget(suggestions_text)

        check_all = _button("Check all ✔", "info")
        check_all.clicked.connect(lambda: self._check_suggestions(True))
        uncheck_all = _button("Uncheck all", "removal")
        uncheck_all.clicked.connect(lambda: self._check_suggestions(False))
        stage = _button("Stage checked links ⇩", "save")
        stage.clicked.connect(self._on_stage_checked)
        suggestions_buttons = QHBoxLayout()
        suggestions_buttons.addWidget(check_all)
        suggestions_buttons.addWidget(uncheck_all)
        suggestions_buttons.addStretch(1)
        suggestions_buttons.addWidget(stage)

        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)

        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(self._criterion)
        lay.addLayout(options)
        lay.addWidget(separator)
        lay.addLayout(suggestions_header)
        lay.addWidget(self._suggestions_table, 1)
        lay.addLayout(suggestions_buttons)
        return tab

    def _build_port_list(self, title: str, with_parameters: bool):
        model = _PortsModel(self)
        proxy = _PortsFilter(self)
        proxy.setSourceModel(model)
        table = _table(proxy)
        table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        table.setColumnWidth(0, 240)
        table.setColumnWidth(1, 70)
        table.setColumnWidth(2, 60)
        table.selectionModel().selectionChanged.connect(self._update_preview)

        text = QLineEdit()
        text.setPlaceholderText("Filter name / description")
        text.textChanged.connect(lambda value: self._set_filter(proxy, text=value))
        types = QComboBox()
        types.addItem("All types", "")
        types.currentIndexChanged.connect(lambda: self._set_filter(proxy, fmi_type=types.currentData()))
        only_free = QCheckBox("only free ports")
        only_free.setChecked(True)
        only_free.toggled.connect(lambda value: self._set_filter(proxy, only_free=value))

        grid = QGridLayout()
        grid.addWidget(QLabel(title), 0, 0, 1, 2)
        grid.addWidget(text, 1, 0)
        grid.addWidget(types, 1, 1)
        options = QHBoxLayout()
        options.addWidget(only_free)
        parameters = None
        if with_parameters:
            parameters = QCheckBox("show parameters")
            parameters.toggled.connect(self._on_show_parameters)
            options.addWidget(parameters)
        options.addStretch(1)
        grid.addLayout(options, 2, 0, 1, 2)
        grid.addWidget(table, 3, 0, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setContentsMargins(0, 0, 0, 0)
        widget = QWidget()
        widget.setLayout(grid)
        return widget, model, proxy, table, types, parameters

    def _build_manual_tab(self) -> QWidget:
        (outputs_widget, self._outputs_model, self._outputs_filter, self._outputs_table, self._outputs_types,
         _) = self._build_port_list("Outputs", with_parameters=False)
        (inputs_widget, self._inputs_model, self._inputs_filter, self._inputs_table, self._inputs_types,
         self._manual_parameters) = self._build_port_list("Inputs", with_parameters=True)
        self._outputs_title = outputs_widget.layout().itemAtPosition(0, 0).widget()
        self._inputs_title = inputs_widget.layout().itemAtPosition(0, 0).widget()

        lists = QSplitter(Qt.Orientation.Horizontal)
        lists.addWidget(outputs_widget)
        lists.addWidget(inputs_widget)

        self._only_unsuggested = QCheckBox("only ports without a suggestion in the Rules tab")
        self._only_unsuggested.toggled.connect(
            lambda value: [self._set_filter(proxy, only_unsuggested=value)
                           for proxy in (self._outputs_filter, self._inputs_filter)])

        self._preview = QLabel()
        self._preview.setTextFormat(Qt.TextFormat.PlainText)
        self._link_selection = _button("Link selection ⇩", "save")
        self._link_selection.clicked.connect(self._on_link_selection)
        bottom = QHBoxLayout()
        bottom.addWidget(self._preview, 1)
        bottom.addWidget(self._link_selection, 0, Qt.AlignmentFlag.AlignBottom)

        tab = QWidget()
        lay = QVBoxLayout(tab)
        lay.addWidget(self._only_unsuggested)
        lay.addWidget(lists, 1)
        lay.addLayout(bottom)
        return tab

    def _build_staged_panel(self) -> QWidget:
        self._staged_model = _StagedModel(self)
        self._staged_filter = _LevelFilter(lambda row: self._staged_model.statuses[row].level, self)
        self._staged_filter.setSourceModel(self._staged_model)
        self._staged_table = _table(self._staged_filter)
        for column, width in ((0, 80), (1, 300), (2, 300), (3, 130)):
            self._staged_table.setColumnWidth(column, width)

        self._staged_summary = QLabel()
        staged_level = _level_combo()
        staged_level.currentIndexChanged.connect(
            lambda: self._set_filter(self._staged_filter, level=staged_level.currentData()))
        staged_text = QLineEdit()
        staged_text.setPlaceholderText("Filter")
        staged_text.textChanged.connect(lambda text: self._set_filter(self._staged_filter, text=text))
        header = QHBoxLayout()
        header.addWidget(self._staged_summary)
        header.addStretch(1)
        header.addWidget(QLabel("Show"))
        header.addWidget(staged_level)
        header.addWidget(staged_text)

        remove = _button("Remove selected", "removal")
        remove.clicked.connect(self._on_remove_staged)
        clear = _button("Clear", "removal")
        clear.clicked.connect(self._on_clear_staged)
        self._existing_label = QLabel()
        cancel = _button("Cancel", "removal")
        cancel.clicked.connect(self.reject)
        self._apply = _button("Apply", "info")
        self._apply.clicked.connect(self._on_apply)
        buttons = QHBoxLayout()
        buttons.addWidget(remove)
        buttons.addWidget(clear)
        buttons.addSpacing(20)
        buttons.addWidget(self._existing_label)
        buttons.addStretch(1)
        buttons.addWidget(cancel)
        buttons.addWidget(self._apply)

        self._staged_table.setMinimumHeight(6 * self._staged_table.verticalHeader().defaultSectionSize())
        panel = QWidget()
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(header)
        lay.addWidget(self._staged_table, 1)
        lay.addLayout(buttons)
        return panel

    # ── Direction dependent data ──────────────────────────────────────

    def _sides(self, direction=None) -> tuple[WireSide, WireSide]:
        direction = direction or self._direction
        return (self._a, self._b) if direction == A_TO_B else (self._b, self._a)

    def _outputs(self) -> list[PortInfo]:
        source, _ = self._sides()
        return [port for port in source.ports if port.causality == "output"]

    def _inputs(self) -> list[PortInfo]:
        _, target = self._sides()
        causalities = ("input", "parameter") if self._show_parameters else ("input",)
        return [port for port in target.ports if port.causality in causalities]

    def _existing_links(self, direction=None) -> list[tuple]:
        source, target = self._sides(direction)
        return [m for m in self._existing if m[0] == source.name and m[2] == target.name]

    def _fed(self, direction=None) -> set[str]:
        """Inputs of the target already fed: outside of this wire, or by an existing link of this wire."""
        _, target = self._sides(direction)
        return with_overlaps(set(target.fed) | {m[3] for m in self._existing_links(direction)}, target.aggregates)

    def _busy_outputs(self) -> set[str]:
        return ({m[1] for m in self._existing_links()}
                | {link.output.name for link in self._staged if link.direction == self._direction})

    def _busy_inputs(self) -> set[str]:
        _, target = self._sides()
        staged = {link.input.name for link in self._staged if link.direction == self._direction}
        return self._fed() | with_overlaps(staged, target.aggregates)

    # ── Refresh ─────────────────────────────────────────────────────

    def _on_direction_changed(self):
        self._direction = self._direction_combo.currentData()
        source, target = self._sides()
        self._outputs_title.setText(f"Outputs of {source.name}")
        self._inputs_title.setText(f"Inputs of {target.name}")
        self._outputs_model.set_ports(self._outputs())
        self._inputs_model.set_ports([port for port in target.ports if port.causality in ("input", "parameter")])
        for combo, ports in ((self._outputs_types, self._outputs()), (self._inputs_types, target.ports)):
            combo.blockSignals(True)
            combo.clear()
            combo.addItem("All types", "")
            for fmi_type in sorted({port.fmi_type for port in ports}):
                combo.addItem(fmi_type, fmi_type)
            combo.blockSignals(False)
        self._outputs_filter.fmi_type = self._inputs_filter.fmi_type = ""
        self._suggestions_model.set_suggestions([])
        self._update_suggestions_summary()
        self._suggestions_summary.setText("Suggestions: searching…")
        self._refresh()
        self._schedule_run()

    def _refresh(self):
        """Recompute what depends on the staged links: statuses, free ports, counters."""
        statuses = []
        for direction in (A_TO_B, B_TO_A):
            links = [(link.output, link.input) for link in self._staged if link.direction == direction]
            _, target = self._sides(direction)
            statuses.append(iter(staged_statuses(links, self._fed(direction), self._checks, target.aggregates)))
        self._statuses = [next(statuses[0] if link.direction == A_TO_B else statuses[1]) for link in self._staged]
        self._staged_model.set_links(self._staged, self._statuses)
        self._staged_filter.refresh()

        self._outputs_filter.busy = self._busy_outputs()
        self._inputs_filter.busy = self._busy_inputs()
        self._outputs_filter.show_parameters = True
        self._inputs_filter.show_parameters = self._show_parameters
        self._outputs_filter.refresh()
        self._inputs_filter.refresh()

        source, target = self._sides()
        outputs, inputs = self._outputs(), self._inputs()
        busy_outputs, busy_inputs = self._busy_outputs(), self._busy_inputs()
        free_outputs = sum(1 for port in outputs if port.name not in busy_outputs)
        free_inputs = sum(1 for port in inputs if port.name not in busy_inputs)
        self._counter_source.setText(f"{source.name}: {len(outputs)} outputs, {len(outputs) - free_outputs} linked")
        self._counter_target.setText(f"{target.name}: {len(inputs)} inputs, {len(inputs) - free_inputs} fed")
        self._tabs.setTabText(1, f"Manual ({free_outputs} │ {free_inputs})")

        levels = [status.level for status in self._statuses]
        self._staged_summary.setText(
            f"Staged links: {len(self._staged)}   ✔ {levels.count(OK)}  ⚠ {levels.count(WARNING)}  "
            f"✖ {levels.count(ERROR)}")
        self._existing_label.setText(f"The {len(self._existing)} existing links of the wire are kept.")
        self._apply.setText(f"Apply {len(self._staged)} links")
        self._apply.setEnabled(bool(self._staged) and ERROR not in levels)
        self._apply.setToolTip("Remove or fix the ✖ links first" if ERROR in levels else "")
        self._update_preview()
        self._drop_taken_suggestions()

    @staticmethod
    def _set_filter(proxy, **values):
        for name, value in values.items():
            setattr(proxy, name, value)
        proxy.refresh()

    def _on_checks_changed(self):
        self._checks = Checks(compatible_type=self._check_type.isChecked(), same_unit=self._check_unit.isChecked())
        self._refresh()
        self._schedule_run()

    def _on_show_parameters(self, value: bool):
        self._show_parameters = value
        for checkbox in (self._rules_parameters, self._manual_parameters):
            checkbox.blockSignals(True)
            checkbox.setChecked(value)
            checkbox.blockSignals(False)
        self._refresh()
        self._schedule_run()

    # ── Rules tab ───────────────────────────────────────────────────

    def _schedule_run(self):
        """Update the suggestions shortly after the last change, unless the last search was too long."""
        if self._auto_run:
            self._run_timer.start()
        else:
            self._suggestions_summary.setText("The criterion changed: press Run")

    def _on_run(self):
        self._run_timer.stop()
        rule = self._criterion.rule()
        start = time.perf_counter()
        suggestions = suggest(self._outputs(), self._inputs(), rule, self._criterion.ignore_case, fed=self._fed(),
                              excluded_outputs=self._busy_outputs(),
                              excluded_inputs=self._busy_inputs() - self._fed(), checks=self._checks)
        elapsed = time.perf_counter() - start
        self._suggestions_origin = rule.short
        self._suggestions_model.set_suggestions(suggestions)
        self._suggestions_filter.refresh()
        self._auto_run = elapsed <= self.AUTO_RUN_LIMIT
        self._run_button.setVisible(not self._auto_run)
        self._update_suggestions_summary(elapsed)

    def _update_suggestions_summary(self, elapsed: float | None = None):
        suggestions = self._suggestions_model.suggestions
        levels = [suggestion.status.level for suggestion in suggestions]
        _, target = self._sides()
        matched_outputs = {s.output.name for s in suggestions}
        matched_inputs = with_overlaps({s.input.name for s in suggestions}, target.aggregates)
        busy_outputs, busy_inputs = self._busy_outputs(), self._busy_inputs()
        unmatched_outputs = sum(1 for port in self._outputs()
                                if port.name not in matched_outputs and port.name not in busy_outputs)
        unmatched_inputs = sum(1 for port in self._inputs()
                               if port.name not in matched_inputs and port.name not in busy_inputs)
        text = (f"Suggestions: {len(levels)}   ✔ {levels.count(OK)}  ⚠ {levels.count(WARNING)}  "
                f"✖ {levels.count(ERROR)}")
        if elapsed is not None:
            text += f"     ({elapsed:.2f} s)"
        self._suggestions_summary.setText(text)
        self._unmatched_link.setText(f'<a href="manual" style="color: #88bbff;">unmatched: {unmatched_outputs} outputs'
                                     f' / {unmatched_inputs} inputs</a>')
        # The Manual tab can hide the ports having a suggestion.
        self._outputs_filter.suggested = matched_outputs
        self._inputs_filter.suggested = matched_inputs
        self._outputs_filter.refresh()
        self._inputs_filter.refresh()

    def _on_unmatched_clicked(self, _link: str = ""):
        """Show the ports without a suggestion in the Manual tab, to link the leftovers by hand."""
        self._only_unsuggested.setChecked(True)
        self._tabs.setCurrentIndex(1)

    def _drop_taken_suggestions(self):
        """Remove the suggestions whose output or input has just been staged, keeping the check boxes of the
        others (the suggestions are not searched again after a staging)."""
        busy_outputs = self._busy_outputs()
        _, target = self._sides()
        staged_inputs = with_overlaps({link.input.name for link in self._staged if link.direction == self._direction},
                                      target.aggregates)
        suggestions = self._suggestions_model.suggestions
        kept = [s for s in suggestions if s.output.name not in busy_outputs and s.input.name not in staged_inputs]
        if len(kept) != len(suggestions):
            self._suggestions_model.set_suggestions(kept)
            self._suggestions_filter.refresh()
            self._update_suggestions_summary()

    def _check_suggestions(self, checked: bool):
        for row in range(self._suggestions_filter.rowCount()):
            source_row = self._suggestions_filter.mapToSource(self._suggestions_filter.index(row, 0)).row()
            self._suggestions_model.suggestions[source_row].checked = checked
        self._suggestions_model.refresh()

    def _stage_suggestions(self, staged: list[Suggestion]):
        if not staged:
            return
        for suggestion in staged:
            self._staged.append(StagedLink(self._direction, suggestion.output, suggestion.input,
                                           self._suggestions_origin))
        self._refresh()

    def _on_stage_checked(self):
        self._stage_suggestions([s for s in self._suggestions_model.suggestions if s.checked])

    def _on_suggestion_double_clicked(self, index):
        row = self._suggestions_filter.mapToSource(index).row()
        self._stage_suggestions([self._suggestions_model.suggestions[row]])

    # ── Manual tab ──────────────────────────────────────────────────

    @staticmethod
    def _selected_ports(table: QTableView) -> list[PortInfo]:
        rows = sorted(index.row() for index in table.selectionModel().selectedRows())
        return [table.model().index(row, 0).data(_PortsModel.ROLE_PORT) for row in rows]

    def _pairs(self) -> list[tuple[PortInfo, PortInfo]]:
        outputs = self._selected_ports(self._outputs_table)
        inputs = self._selected_ports(self._inputs_table)
        if len(outputs) == 1 and inputs:
            return [(outputs[0], input) for input in inputs]
        if outputs and len(outputs) == len(inputs):
            return list(zip(outputs, inputs))
        return []

    def _update_preview(self):
        outputs = self._selected_ports(self._outputs_table)
        inputs = self._selected_ports(self._inputs_table)
        pairs = self._pairs()
        if pairs:
            lines = [f"{output.name}  →  {input.name}" for output, input in pairs[:4]]
            if len(pairs) > 4:
                lines.append(f"… and {len(pairs) - 4} more")
            how = "fan-out of one output" if len(outputs) == 1 and len(inputs) > 1 else "paired in display order"
            lines.append(f"{len(outputs)} output(s) ↔ {len(inputs)} input(s): {how}")
        elif outputs or inputs:
            lines = [f"{len(outputs)} output(s) ↔ {len(inputs)} input(s): select as many inputs as outputs, "
                     f"or one output and several inputs"]
        else:
            lines = ["Select outputs and inputs (Shift / Ctrl for several)"]
        self._preview.setText("\n".join(lines))
        self._link_selection.setEnabled(bool(pairs))

    def _on_link_selection(self):
        pairs = self._pairs()
        for output, input in pairs:
            self._staged.append(StagedLink(self._direction, output, input, "manual"))
        self._outputs_table.clearSelection()
        self._inputs_table.clearSelection()
        self._refresh()

    # ── Staged links ────────────────────────────────────────────────

    def _on_remove_staged(self):
        rows = {self._staged_filter.mapToSource(index).row()
                for index in self._staged_table.selectionModel().selectedRows()}
        self._staged = [link for row, link in enumerate(self._staged) if row not in rows]
        self._refresh()

    def _on_clear_staged(self):
        self._staged = []
        self._refresh()

    def staged_mappings(self) -> list[tuple]:
        result = []
        for link in self._staged:
            source, target = self._sides(link.direction)
            result.append((source.name, link.output.name, target.name, link.input.name))
        return result

    def _on_apply(self):
        self.applied.emit(self.staged_mappings())
        self._existing.extend(self.staged_mappings())
        self._staged = []
        self._refresh()
        self.accept()

    def reject(self):
        if self._staged:
            answer = QMessageBox.question(self, "Link assistant",
                                          f"Discard the {len(self._staged)} staged links?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._staged = []
        super().reject()

    def closeEvent(self, event):
        if self._staged:
            event.ignore()
            self.reject()
            return
        super().closeEvent(event)
