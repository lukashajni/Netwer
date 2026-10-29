"""Packet Capture page: a Wireshark-style live capture with the assistant built in."""
import socket

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QScrollArea,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QTableView,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.theme import Theme, card_bg, card_border, input_bg, is_dark
from core.capture import MAX_PACKETS, capture_backend, get_capture_service, list_interfaces
from core.display_filter import ALL_NAMES, FilterError, compile_filter
from ui.pages.base_page import BasePage
from ui.widgets.sparkline import Sparkline
from ui.widgets.ui_kit import InsightRow, button, chip, style_button

COLUMNS = ["No.", "Time", "Source", "Destination", "Protocol", "Length", "Info"]
QUICK_FILTERS = [("TLS", "tls"), ("DNS", "dns && !mdns"), ("QUIC", "quic"), ("TCP problems", "tcp.analysis.flags"),
                 ("No broadcast", "!(arp || mdns || ssdp || llmnr || nbns || stp)"), ("HTTP", "http")]

# dark bg, dark fg, light bg, light fg
ROW_COLORS = {
    "tcp": ("#121a30", "#c4cfee", "#e7e6ff", "#12131a"),
    "tcpctl": ("#1b2030", "#97a1bd", "#a0a0a0", "#12131a"),
    "tls": ("#1c1739", "#cdc2ff", "#e9e1ff", "#12131a"),
    "dns": ("#0e2a2d", "#9de6da", "#daeeff", "#12131a"),
    "quic": ("#0e2238", "#a3d2ff", "#e3f1ff", "#12131a"),
    "http": ("#13301f", "#a6efbd", "#e4ffc7", "#12131a"),
    "arp": ("#2c2310", "#f5d48e", "#fafbe0", "#12131a"),
    "icmp": ("#2b1530", "#f2b6ee", "#fce0ff", "#12131a"),
    "udp": ("#10202b", "#b3d9ec", "#daeeff", "#12131a"),
    "mcast": ("#181c28", "#959eb6", "#ececec", "#30323d"),
    "bad": ("#3b0e1c", "#ff93a9", "#12131a", "#f78787"),
    "other": ("#161b2c", "#a6b0cd", "#f4f4f4", "#12131a"),
}
MIX_COLORS = {"TLS": "#a48fff", "QUIC": "#5fb4ff", "DNS": "#3fd0c0", "TCP": "#5b8cff", "HTTP": "#4fd88a",
              "ARP": "#f5b545", "ICMP": "#ee8de6", "ICMPv6": "#ee8de6", "UDP": "#7fc3e0", "Discovery": "#7d86a0"}


def color_class(p) -> str:
    d = p.dis
    if p.tags:
        return "bad"
    name = d.proto
    if name.startswith("TLS"):
        return "tls"
    if name in ("MDNS", "SSDP", "LLMNR", "NBNS", "STP", "LLC", "LLDP"):
        return "mcast"
    if name in ("DNS",):
        return "dns"
    if name == "QUIC":
        return "quic"
    if name in ("HTTP", "FTP", "Telnet", "POP3", "IMAP"):
        return "http"
    if name == "ARP":
        return "arp"
    if name.startswith("ICMP"):
        return "icmp"
    if name == "TCP":
        return "tcpctl" if (d.tcp_flags or 0) & 7 else "tcp"
    if d.l4 == "udp":
        return "udp"
    return "other"


def local_ipv4() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 53))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return ""


class PacketModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []
        self._font = QFont(Theme.FONT_MONO_PRIMARY)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setPointSizeF(9)
        self._dark = is_dark()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        p = self.rows[index.row()]
        col = index.column()
        if role == Qt.ItemDataRole.DisplayRole:
            d = p.dis
            return (str(p.no), f"{p.rel:.6f}", d.src, d.dst, d.proto, str(d.length), d.info)[col]
        if role in (Qt.ItemDataRole.BackgroundRole, Qt.ItemDataRole.ForegroundRole):
            c = ROW_COLORS[color_class(p)]
            bg, fg = (c[0], c[1]) if self._dark else (c[2], c[3])
            return QColor(bg if role == Qt.ItemDataRole.BackgroundRole else fg)
        if role == Qt.ItemDataRole.FontRole:
            return self._font
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (0, 5):
            return Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        return None

    def append(self, packets):
        if not packets:
            return
        n = len(self.rows)
        self.beginInsertRows(QModelIndex(), n, n + len(packets) - 1)
        self.rows.extend(packets)
        self.endInsertRows()

    def reset(self, packets):
        self.beginResetModel()
        self.rows = list(packets)
        self.endResetModel()


class _RowDelegate(QStyledItemDelegate):

    def paint(self, painter, option, index):
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        bg = QColor(Theme.ACCENT) if selected else index.data(Qt.ItemDataRole.BackgroundRole)
        fg = QColor("#ffffff") if selected else index.data(Qt.ItemDataRole.ForegroundRole)
        painter.save()
        painter.fillRect(option.rect, bg)
        painter.setFont(index.data(Qt.ItemDataRole.FontRole))
        painter.setPen(fg)
        align = index.data(Qt.ItemDataRole.TextAlignmentRole) or (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        rect = option.rect.adjusted(8, 0, -8, 0)
        text = painter.fontMetrics().elidedText(index.data() or "", Qt.TextElideMode.ElideRight, rect.width())
        painter.drawText(rect, align, text)
        painter.restore()


class HexView(QWidget):
    byte_clicked = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._data = b""
        self._sel = (0, 0)
        self._font = QFont(Theme.FONT_MONO_PRIMARY)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setPointSizeF(9.5)
        self.setMouseTracking(False)
        self._measure()

    def _measure(self):
        from PyQt6.QtGui import QFontMetrics
        fm = QFontMetrics(self._font)
        self._cw = fm.horizontalAdvance("0")
        self._lh = fm.height() + 3
        self._hex_x = self._cw * 6
        self._asc_x = self._hex_x + self._cw * (16 * 3 + 2)

    def set_data(self, data: bytes):
        self._data = data or b""
        self._sel = (0, 0)
        rows = (len(self._data) + 15) // 16
        self.setFixedSize(QSize(int(self._asc_x + self._cw * 17 + 12), int(rows * self._lh + 12)))
        self.update()

    def set_selection(self, off, length):
        self._sel = (off or 0, length or 0)
        self.update()

    def row_y(self, off):
        return int(6 + (off // 16) * self._lh)

    def _byte_x(self, i):
        col = i % 16
        return self._hex_x + self._cw * (col * 3 + (1 if col >= 8 else 0))

    def mousePressEvent(self, e):
        x, y = e.position().x(), e.position().y()
        row = int((y - 6) // self._lh)
        if x >= self._asc_x:
            col = int((x - self._asc_x) // self._cw)
        else:
            rel = (x - self._hex_x) / self._cw
            col = int((rel - (1 if rel >= 24 else 0)) // 3)
        if 0 <= col < 16 and row >= 0:
            off = row * 16 + col
            if off < len(self._data):
                self.byte_clicked.emit(off)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setFont(self._font)
        a, n = self._sel
        hl = QColor(Theme.ACCENT)
        fg, dim, faint = QColor(Theme.TEXT_BODY), QColor(Theme.TEXT_MUTED), QColor(Theme.TEXT_FAINT)
        for r in range(0, len(self._data), 16):
            y = 6 + (r // 16) * self._lh
            p.setPen(faint)
            p.drawText(QRectF(0, y, self._hex_x, self._lh), Qt.AlignmentFlag.AlignVCenter, f"{r:04x}")
            for i in range(r, min(r + 16, len(self._data))):
                b = self._data[i]
                x = self._byte_x(i)
                ax = self._asc_x + self._cw * (i - r)
                on = a <= i < a + n
                if on:
                    p.fillRect(QRectF(x - 2, y, self._cw * 2 + 4, self._lh), hl)
                    p.fillRect(QRectF(ax, y, self._cw, self._lh), hl)
                p.setPen(QColor("#ffffff") if on else (faint if b == 0 else fg))
                p.drawText(QRectF(x, y, self._cw * 2, self._lh), Qt.AlignmentFlag.AlignVCenter, f"{b:02x}")
                p.setPen(QColor("#ffffff") if on else dim)
                ch = chr(b) if 32 <= b < 127 else "·"
                p.drawText(QRectF(ax, y, self._cw, self._lh), Qt.AlignmentFlag.AlignVCenter, ch)
        p.end()


class MixBar(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(7)
        self._parts = []

    def set_parts(self, parts):
        self._parts = parts
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(Theme.BORDER))
        p.drawRoundedRect(r, 3.5, 3.5)
        total = sum(v for _, v in self._parts) or 1
        x = 0.0
        for name, v in self._parts:
            w = r.width() * v / total
            p.setBrush(QColor(MIX_COLORS.get(name, Theme.TEXT_MUTED)))
            p.drawRect(QRectF(x, 0, w, r.height()))
            x += w
        p.end()


class _Panel(QFrame):
    def __init__(self, title, parent=None):
        super().__init__(parent)
        self.setObjectName("CapPanel")
        self.setStyleSheet(f"#CapPanel {{ background: {card_bg()}; border: 1px solid {card_border()};"
                           f"border-radius: {Theme.RADIUS_CONTROL}px; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        head = QWidget()
        self.head = QHBoxLayout(head)
        self.head.setContentsMargins(12, 6, 8, 6)
        t = QLabel(title)
        t.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-weight: 600; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self.head.addWidget(t)
        self.note = QLabel("")
        self.note.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-family: {Theme.FONT_MONO}; font-size: {Theme.FONT_SIZE_TINY}px;")
        self.head.addWidget(self.note)
        self.head.addStretch()
        head.setFixedHeight(40)
        lay.addWidget(head)
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"background: {card_border()};")
        lay.addWidget(line)
        self.body = lay


class CapturePage(BasePage):
    PAGE_TITLE = "Packet Capture"
    PAGE_SUBTITLE = "Capture and inspect the packets on your network, with Netwer AI explaining them"

    def __init__(self, core, parent=None):
        super().__init__(core, parent)
        self.svc = get_capture_service()
        self._seen = 0
        self._filter_text = ""
        self._pred = lambda p: True
        self._follow = True
        self._scrolling = False
        self._tick_n = 0
        self._items = []
        self._limit_shown = False

        self._root.setSpacing(10)
        self._build_toolbar()
        self._build_filter_row()
        self._build_stats()
        self._build_watch()
        self._build_panes()

        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._tick)
        self._fill_interfaces()
        self._update_controls()

    def _build_toolbar(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.iface = QComboBox()
        self.iface.setMinimumWidth(260)
        self.iface.setStyleSheet(
            f"QComboBox {{ background: {input_bg()}; color: {Theme.TEXT_BODY}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: {Theme.RADIUS_CONTROL - 3}px; padding: 5px 10px; font-size: {Theme.FONT_SIZE_SMALL}px; }}"
            f"QComboBox QAbstractItemView {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_BODY};"
            f"selection-background-color: {Theme.ACCENT}; }}")
        row.addWidget(self.iface)
        self.btn_start = button("Start", "play", "primary", "Start capturing on the selected interface")
        self.btn_start.clicked.connect(self._toggle_capture)
        row.addWidget(self.btn_start)
        self.btn_clear = button("", "refresh", tip="Clear the packet list")
        self.btn_clear.clicked.connect(self._clear)
        row.addWidget(self.btn_clear)
        self.btn_follow = button("Follow", "chevron_down", tip="Keep the newest packet in view")
        self.btn_follow.setCheckable(True)
        self.btn_follow.setChecked(True)
        self.btn_follow.toggled.connect(self._set_follow)
        row.addWidget(self.btn_follow)
        self.bpf = QLineEdit()
        self.bpf.setPlaceholderText("Capture filter, e.g. port 53 or host 1.1.1.1")
        self.bpf.setToolTip("BPF syntax. Only matching packets are captured at all.")
        self.bpf.setMinimumWidth(260)
        self.bpf.returnPressed.connect(self._toggle_capture)
        self.bpf.setStyleSheet(
            f"QLineEdit {{ background: {input_bg()}; color: {Theme.TEXT_PRIMARY}; border: 1px solid {Theme.GLASS_BORDER};"
            f"border-radius: {Theme.RADIUS_CONTROL - 3}px; padding: 5px 10px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }} QLineEdit:disabled {{ color: {Theme.TEXT_MUTED}; }}")
        row.addWidget(self.bpf)
        row.addStretch()
        self.btn_stats = button("Statistics", "monitor", tip="Conversations and endpoints")
        self.btn_stats.clicked.connect(self._show_stats)
        row.addWidget(self.btn_stats)
        self.btn_open = button("Open", "export", tip="Open a .pcap or .pcapng file")
        self.btn_open.clicked.connect(self._open_file)
        row.addWidget(self.btn_open)
        self.btn_save = button("Save .pcap", "save", tip="Save the displayed packets")
        self.btn_save.clicked.connect(self._save_file)
        row.addWidget(self.btn_save)
        self.btn_ai = button("Summarize capture", "ai", "ai")
        self.btn_ai.clicked.connect(lambda: self._ask("Summarize what is happening in my packet capture."))
        row.addWidget(self.btn_ai)
        self._root.addLayout(row)

        self.banner = QLabel("")
        self.banner.setWordWrap(True)
        self.banner.setStyleSheet(
            f"background: {input_bg()}; color: {Theme.WARNING}; border: 1px solid {Theme.WARNING};"
            f"border-radius: 8px; padding: 8px 12px; font-size: {Theme.FONT_SIZE_SMALL}px;")
        self.banner.hide()
        self._root.addWidget(self.banner)

    def _build_filter_row(self):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText("Display filter, e.g.  tls && ip.addr == 140.82.121.4   (Enter to apply)")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._validate)
        self.filter.returnPressed.connect(self._apply_filter)
        from PyQt6.QtWidgets import QCompleter
        comp = QCompleter(ALL_NAMES, self.filter)
        comp.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        comp.setFilterMode(Qt.MatchFlag.MatchContains)
        self.filter.setCompleter(comp)
        row.addWidget(self.filter, 1)
        self.filter_err = QLabel("")
        self.filter_err.setStyleSheet(f"color: {Theme.DANGER}; font-size: {Theme.FONT_SIZE_TINY}px;")
        row.addWidget(self.filter_err)
        for label, expr in QUICK_FILTERS:
            c = chip(label, expr)
            c.clicked.connect(lambda _=False, e=expr: self.set_filter(e))
            row.addWidget(c)
        self._root.addLayout(row)
        self._style_filter("")

    def _build_stats(self):
        box = QFrame()
        box.setObjectName("CapStats")
        box.setStyleSheet(f"#CapStats {{ background: {card_bg()}; border: 1px solid {card_border()};"
                          f"border-radius: {Theme.RADIUS_CONTROL}px; }} QLabel {{ background: transparent; }}")
        lay = QHBoxLayout(box)
        lay.setContentsMargins(14, 8, 14, 8)
        lay.setSpacing(22)
        self._stat = {}
        for key, label in (("packets", "PACKETS"), ("shown", "DISPLAYED"), ("bytes", "DATA"), ("rate", "RATE")):
            col = QVBoxLayout()
            col.setSpacing(0)
            t = QLabel(label)
            t.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px; letter-spacing: 1px;")
            v = QLabel("0")
            v.setStyleSheet(f"color: {Theme.TEXT_PRIMARY}; font-family: {Theme.FONT_MONO}; font-size: 15px; font-weight: 600;")
            col.addWidget(t)
            col.addWidget(v)
            self._stat[key] = v
            lay.addLayout(col)
        self.spark = Sparkline(Theme.ACCENT, max_points=40, transparent=True)
        self.spark.setFixedWidth(110)
        lay.addWidget(self.spark)
        mix = QVBoxLayout()
        mix.setSpacing(4)
        t = QLabel("PROTOCOL MIX")
        t.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: 10px; letter-spacing: 1px;")
        mix.addWidget(t)
        self.mixbar = MixBar()
        mix.addWidget(self.mixbar)
        self.mixleg = QLabel("")
        self.mixleg.setTextFormat(Qt.TextFormat.RichText)
        self.mixleg.setStyleSheet(f"color: {Theme.TEXT_SECONDARY}; font-size: {Theme.FONT_SIZE_TINY}px;")
        mix.addWidget(self.mixleg)
        lay.addLayout(mix, 1)
        self._root.addWidget(box)

    def _build_watch(self):
        self.watch = InsightRow(self._ask, "AI WATCH")
        self._root.addWidget(self.watch)

    def _build_panes(self):
        split = QSplitter(Qt.Orientation.Vertical)
        split.setHandleWidth(8)
        split.setStyleSheet("QSplitter::handle { background: transparent; }")

        self.model = PacketModel(self)
        self.table = QTableView()
        self.table.setModel(self.model)
        self.table.setItemDelegate(_RowDelegate(self.table))
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        self.table.verticalHeader().setDefaultSectionSize(22)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for i, w in enumerate((70, 100, 150, 150, 80, 64)):
            self.table.setColumnWidth(i, w)
        hh.setStretchLastSection(True)
        self.table.setStyleSheet(
            f"QTableView {{ background: {card_bg()}; border: 1px solid {card_border()};"
            f"border-radius: {Theme.RADIUS_CONTROL}px; outline: none; }}"
            f"QHeaderView::section {{ background: {Theme.BG_ELEVATED}; color: {Theme.TEXT_MUTED}; border: none;"
            f"border-bottom: 1px solid {card_border()}; padding: 5px 8px; font-size: {Theme.FONT_SIZE_TINY}px; }}")
        self.table.selectionModel().currentRowChanged.connect(self._on_row)
        self.table.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.table.clicked.connect(lambda _: self.btn_follow.setChecked(False))
        split.addWidget(self.table)

        self.empty = QLabel(self.table.viewport())
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setStyleSheet(f"color: {Theme.TEXT_MUTED}; font-size: {Theme.FONT_SIZE_BODY}px; background: transparent;")

        lower = QSplitter(Qt.Orientation.Horizontal)
        lower.setHandleWidth(8)
        lower.setStyleSheet("QSplitter::handle { background: transparent; }")
        self.details = _Panel("Packet details")
        self.btn_explain = button("Explain packet", "ai", "ai")
        self.btn_explain.clicked.connect(self._explain_selected)
        self.btn_stream = button("Follow stream", "list")
        self.btn_stream.clicked.connect(self._follow_stream)
        self.details.head.addWidget(self.btn_stream)
        self.details.head.addWidget(self.btn_explain)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setIndentation(16)
        self.tree.setStyleSheet(
            f"QTreeWidget {{ background: transparent; border: none; color: {Theme.TEXT_BODY};"
            f"font-family: {Theme.FONT_MONO}; font-size: {Theme.FONT_SIZE_TINY + 1}px; }}"
            f"QTreeWidget::item {{ padding: 1px 0; }}"
            f"QTreeWidget::item:selected {{ background: {Theme.ACCENT}; color: #ffffff; }}")
        self.tree.currentItemChanged.connect(self._on_tree_item)
        self.details.body.addWidget(self.tree, 1)
        lower.addWidget(self.details)

        self.bytes_panel = _Panel("Bytes")
        self.hex = HexView()
        self.hex.byte_clicked.connect(self._on_byte)
        self.hex_scroll = QScrollArea()
        self.hex_scroll.setWidget(self.hex)
        self.hex_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.hex_scroll.setStyleSheet("QScrollArea { background: transparent; }")
        self.bytes_panel.body.addWidget(self.hex_scroll, 1)
        lower.addWidget(self.bytes_panel)
        lower.setSizes([560, 480])

        split.addWidget(lower)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([420, 290])
        self._root.addWidget(split, 1)
        self._update_empty()

    def on_enter(self):
        self._sync_all()
        self._timer.start()

    def on_leave(self):
        # capture keeps running in the background
        self._timer.stop()
        super().on_leave()

    def shutdown(self):
        self.svc.stop()

    def _fill_interfaces(self):
        ok, msg = capture_backend()
        self.iface.clear()
        if not ok:
            self.banner.setText(msg + "  You can still open a saved .pcap file.")
            self.banner.show()
            self.iface.addItem("Live capture unavailable")
            self.iface.setEnabled(False)
            return
        mine = local_ipv4()
        best = 0
        for i, it in enumerate(list_interfaces()):
            text = it["name"] + (f"  —  {it['ip']}" if it["ip"] else "")
            self.iface.addItem(text, it["name"])
            self.iface.setItemData(i, it["description"], Qt.ItemDataRole.ToolTipRole)
            if mine and it["ip"] == mine:
                best = i
        self.iface.setCurrentIndex(best)

    def _toggle_capture(self):
        if self.svc.running:
            self.svc.stop()
        else:
            name = self.iface.currentData()
            if not name:
                return
            try:
                self.svc.start(name, self.bpf.text().strip())
            except Exception as exc:
                self.banner.setText(f"Could not start the capture: {exc}")
                self.banner.show()
                return
            self.banner.hide()
            self._limit_shown = False
            self._sync_all()
            self.btn_follow.setChecked(True)
        self._update_controls()

    def _update_controls(self):
        on = self.svc.running
        self.btn_start.setText("  Stop" if on else "  Start")
        style_button(self.btn_start, "danger" if on else "primary", "stop" if on else "play")
        self.iface.setEnabled(not on and self.iface.count() > 0 and self.iface.currentData() is not None)
        self.bpf.setEnabled(not on)
        win = self._window
        if win is not None and hasattr(win, "set_capture_state"):
            win.set_capture_state(on)

    def _clear(self):
        running = self.svc.running
        if running:
            self._toggle_capture()
            self._toggle_capture()
        else:
            self.svc.reset()
            self._sync_all()

    def _tick(self):
        if self.svc.truncated and not self._limit_shown:
            self._limit_shown = True
            self.banner.setText(f"The capture stopped at {MAX_PACKETS:,} packets to keep memory in check. "
                                "Save it, then clear and start again, or use a capture filter.")
            self.banner.show()
            self._update_controls()
        err = self.svc.poll_error()
        if err:
            self.banner.setText(f"The capture stopped: {err}")
            self.banner.show()
            self._update_controls()
        if self.svc.count() < self._seen:
            self._sync_all()
            return
        new = self.svc.since(self._seen)
        if new:
            self._seen += len(new)
            shown = [p for p in new if self._pred(p)]
            self.model.append(shown)
            if self._follow and shown:
                self._scrolling = True
                self.table.scrollToBottom()
                self._scrolling = False
            self._update_empty()
        self._tick_n += 1
        if self._tick_n % 4 == 0:
            self._update_stats()
        if self._tick_n % 7 == 0:
            self._update_watch()
        if not self.svc.running and self.btn_start.text().strip() == "Stop":
            self._update_controls()

    def _sync_all(self):
        pkts = self.svc.since(0)
        self._seen = len(pkts)
        self.model.reset([p for p in pkts if self._pred(p)])
        self._show_packet(None)
        if self._follow:
            self.table.scrollToBottom()
        self._update_empty()
        self._update_stats()
        self._update_watch()

    def _update_empty(self):
        n = self.model.rowCount()
        if n:
            self.empty.hide()
            return
        if self.svc.count():
            self.empty.setText("No packets match this filter yet.")
        elif self.svc.running:
            self.empty.setText("Waiting for packets…")
        else:
            name = self.iface.currentData() or "an interface"
            self.empty.setText(f"Press Start to capture on {name}, or open a saved .pcap file.")
        self.empty.setGeometry(self.table.viewport().rect())
        self.empty.show()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.empty.setGeometry(self.table.viewport().rect())

    def _update_stats(self):
        s = self.svc
        n = s.count()
        self._stat["packets"].setText(f"{n:,}")
        shown = self.model.rowCount()
        self._stat["shown"].setText(f"{shown:,}" + (f"  ({shown * 100 // n}%)" if n else ""))
        b = s.total_bytes
        self._stat["bytes"].setText(f"{b / 1048576:.2f} MB" if b >= 1048576 else f"{b / 1024:.1f} KB")
        last = int(s.packets[-1].rel) if n else 0
        rate = s.per_sec.get(last - 1, 0) if s.running else 0
        self._stat["rate"].setText(f"{rate} pkt/s")
        self.spark.push(rate)
        parts = s.proto_mix.most_common(8)
        self.mixbar.set_parts(parts)
        tot = sum(v for _, v in parts) or 1
        self.mixleg.setText("&nbsp;&nbsp;".join(
            f"<span style='color:{MIX_COLORS.get(k, Theme.TEXT_MUTED)}'>■</span> {k} "
            f"<span style='color:{Theme.TEXT_MUTED}'>{v * 100 / tot:.0f}%</span>" for k, v in parts[:6]))
        s.displayed = shown
        s.view_filter = self._filter_text

    def _update_watch(self):
        self.watch.set_items([{**i, "before": lambda i=i: self._apply_insight(i)} for i in self.svc.insights()])

    def _apply_insight(self, it):
        self.set_filter(it["filter"])
        if it.get("frame"):
            self.select_packet(it["frame"])

    def _style_filter(self, state):
        border = {"ok": Theme.SUCCESS, "err": Theme.DANGER}.get(state, Theme.GLASS_BORDER)
        self.filter.setStyleSheet(
            f"QLineEdit {{ background: {input_bg()}; color: {Theme.TEXT_PRIMARY}; border: 1px solid {border};"
            f"border-radius: {Theme.RADIUS_CONTROL - 3}px; padding: 6px 10px; font-family: {Theme.FONT_MONO};"
            f"font-size: {Theme.FONT_SIZE_SMALL}px; }}")

    def _validate(self, text):
        if not text.strip():
            self._style_filter("")
            self.filter_err.setText("")
            return
        try:
            compile_filter(text)
            self._style_filter("ok")
            self.filter_err.setText("")
        except FilterError as exc:
            self._style_filter("err")
            self.filter_err.setText(str(exc))

    def _apply_filter(self):
        text = self.filter.text().strip()
        try:
            self._pred = compile_filter(text)
        except FilterError as exc:
            self.filter_err.setText(str(exc))
            return
        self._filter_text = text
        self.btn_follow.setChecked(True)
        self._sync_all()

    def set_filter(self, text):
        self.filter.setText(text)
        self._apply_filter()

    def _set_follow(self, on):
        self._follow = on
        if on:
            self.table.scrollToBottom()

    def _on_scroll(self, value):
        bar = self.table.verticalScrollBar()
        if not self._scrolling and self._follow and value < bar.maximum() - 2:
            self.btn_follow.setChecked(False)

    def _on_row(self, current, _prev):
        self._show_packet(self.model.rows[current.row()] if current.isValid() else None)

    def select_packet(self, no):
        for i, p in enumerate(self.model.rows):
            if p.no == no:
                self.btn_follow.setChecked(False)
                idx = self.model.index(i, 0)
                self.table.setCurrentIndex(idx)
                self.table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)
                return

    def _show_packet(self, p):
        self.tree.clear()
        self._items = []
        self.svc.selected_no = p.no if p else None
        if p is None:
            self.details.note.setText("")
            self.bytes_panel.note.setText("")
            self.hex.set_data(b"")
            self.btn_explain.setEnabled(False)
            self.btn_stream.setEnabled(False)
            return
        self.btn_explain.setEnabled(True)
        self.btn_stream.setEnabled(p.stream is not None)
        d = p.dis
        self.details.note.setText(f"#{p.no} · {d.proto}")
        self.hex.set_data(p.data)
        frame = QTreeWidgetItem([f"Frame {p.no}: {d.length} bytes on wire ({d.length * 8} bits), "
                                 f"captured {p.rel:.6f} s after the first frame"])
        frame.setData(0, Qt.ItemDataRole.UserRole, (0, d.length))
        frame.addChild(QTreeWidgetItem([f"[Protocols in frame: {':'.join(d.protos)}]"]))
        if p.tags:
            frame.addChild(QTreeWidgetItem([f"[TCP analysis: {', '.join(sorted(p.tags))}]"]))
        self.tree.addTopLevelItem(frame)
        self._items.append(frame)
        last = None
        for node in p.tree():
            last = self._add_node(None, node)
        target = last
        if d.fields.get("tls.handshake.extensions_server_name"):
            target = self._find_item(lambda t: t.startswith("Server Name: ")) or last
        if target is not None:
            parent = target.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            target.setExpanded(True)
            self.tree.setCurrentItem(target)

    def _add_node(self, parent, node):
        item = QTreeWidgetItem([node.title])
        item.setData(0, Qt.ItemDataRole.UserRole, (node.off, node.length) if node.off is not None else None)
        if node.off is None:
            item.setForeground(0, QColor(Theme.TEXT_MUTED))
        if parent is None:
            self.tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        self._items.append(item)
        for c in node.children:
            self._add_node(item, c)
        return item

    def _find_item(self, pred):
        return next((it for it in self._items if pred(it.text(0))), None)

    def _on_tree_item(self, item, _prev):
        rng = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not rng:
            self.hex.set_selection(0, 0)
            self.bytes_panel.note.setText("")
            return
        off, n = rng
        self.hex.set_selection(off, n)
        self.bytes_panel.note.setText(f"{n} byte{'s' if n != 1 else ''} at 0x{off:04x}")
        self.hex_scroll.ensureVisible(0, self.hex.row_y(off), 0, 40)

    def _on_byte(self, off):
        best, size = None, None
        for it in self._items[1:]:
            rng = it.data(0, Qt.ItemDataRole.UserRole)
            if rng and rng[0] <= off < rng[0] + rng[1] and (size is None or rng[1] <= size):
                best, size = it, rng[1]
        if best is not None:
            parent = best.parent()
            while parent is not None:
                parent.setExpanded(True)
                parent = parent.parent()
            self.tree.setCurrentItem(best)

    def _ask(self, question):
        win = self._window or self.window()
        if hasattr(win, "ask_ai"):
            win.ask_ai(question)

    def _follow_stream(self):
        p = self.svc.packet(self.svc.selected_no)
        if p is not None and p.stream is not None:
            from ui.components.capture_dialogs import FollowStreamDialog
            FollowStreamDialog(self.svc, p.stream, self.set_filter, self).exec()

    def _show_stats(self):
        from ui.components.capture_dialogs import StatisticsDialog
        StatisticsDialog(self.svc, self.set_filter, self).exec()

    def _explain_selected(self):
        p = self.svc.packet(self.svc.selected_no)
        if p is not None:
            self._ask(f"Explain packet #{p.no} from my capture ({p.dis.proto}: {p.dis.info[:80]}).")

    def _open_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open capture", "", "Captures (*.pcap *.pcapng *.cap);;All files (*)")
        if not path:
            return
        try:
            n = self.svc.load_file(path)
        except Exception as exc:
            self.banner.setText(f"Could not open the file: {exc}")
            self.banner.show()
            return
        self.banner.hide()
        self.btn_follow.setChecked(False)
        self._update_controls()
        self._sync_all()
        if not n:
            self.empty.setText("The file has no Ethernet frames.")

    def _save_file(self):
        if not self.model.rowCount():
            return
        path, _ = QFileDialog.getSaveFileName(self, "Save capture", "netwer-capture.pcap", "pcap (*.pcap)")
        if not path:
            return
        try:
            n = self.svc.save_pcap(path, self.model.rows)
        except OSError as exc:
            self.banner.setText(f"Could not save: {exc}")
            self.banner.show()
            return
        from app.notifications import notifications
        notifications.push("Capture saved", f"{n:,} packets written to {path}", "success")
