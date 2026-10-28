DARK_THEME_QSS = """
QMainWindow, QDialog {
    background-color: #121216;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, sans-serif;
    font-size: 13px;
}

QWidget {
    background-color: transparent;
    color: #e2e8f0;
    font-family: 'Segoe UI', system-ui, sans-serif;
}

QTabWidget::pane {
    border: 1px solid #272730;
    background-color: #18181f;
    border-radius: 8px;
}

QTabBar::tab {
    background-color: #1e1e26;
    color: #94a3b8;
    padding: 10px 22px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    font-weight: 600;
}

QTabBar::tab:selected {
    background-color: #18181f;
    color: #38bdf8;
    border-bottom: 2px solid #38bdf8;
}

QTabBar::tab:hover {
    color: #f1f5f9;
}

QGroupBox {
    background-color: #1a1a22;
    border: 1px solid #2a2a36;
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 18px;
    padding-left: 14px;
    padding-right: 14px;
    padding-bottom: 14px;
    font-weight: 600;
    color: #38bdf8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    background-color: #1a1a22;
}

QPushButton {
    background-color: #272734;
    color: #f8fafc;
    border: 1px solid #3b3b4f;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
}

QPushButton:hover {
    background-color: #323242;
    border-color: #4b4b66;
}

QPushButton:pressed {
    background-color: #1f1f2b;
}

QPushButton:disabled {
    background-color: #1c1c24;
    color: #64748b;
    border-color: #262633;
}

QPushButton#primaryBtn {
    background-color: #0284c7;
    border-color: #0369a1;
    color: #ffffff;
}

QPushButton#primaryBtn:hover {
    background-color: #0369a1;
    border-color: #075985;
}

QPushButton#successBtn {
    background-color: #059669;
    border-color: #047857;
    color: #ffffff;
}

QPushButton#successBtn:hover {
    background-color: #047857;
}

QPushButton#dangerBtn {
    background-color: #dc2626;
    border-color: #b91c1c;
    color: #ffffff;
}

QPushButton#dangerBtn:hover {
    background-color: #b91c1c;
}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #14141a;
    color: #f1f5f9;
    border: 1px solid #2e2e3d;
    border-radius: 6px;
    padding: 7px 10px;
    selection-background-color: #0284c7;
}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus {
    border: 1px solid #38bdf8;
}

QComboBox::drop-down {
    border: none;
    width: 24px;
}

QComboBox QAbstractItemView {
    background-color: #1a1a24;
    border: 1px solid #38bdf8;
    selection-background-color: #0284c7;
    color: #f8fafc;
}

QListWidget, QTableWidget {
    background-color: #14141a;
    border: 1px solid #262633;
    border-radius: 6px;
    padding: 4px;
    color: #e2e8f0;
}

QListWidget::item {
    padding: 8px;
    border-radius: 4px;
    margin-bottom: 2px;
}

QListWidget::item:selected {
    background-color: #0369a1;
    color: #ffffff;
}

QListWidget::item:hover {
    background-color: #1f1f2e;
}

QScrollBar:vertical {
    background: #14141a;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #333344;
    min-height: 24px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #4b4b63;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}

QProgressBar {
    border: 1px solid #2a2a38;
    border-radius: 6px;
    text-align: center;
    background-color: #121218;
    color: #f8fafc;
    font-weight: 600;
}

QProgressBar::chunk {
    background-color: #0284c7;
    border-radius: 5px;
}

QSlider::groove:horizontal {
    border: 1px solid #2a2a3a;
    height: 6px;
    background: #14141a;
    border-radius: 3px;
}

QSlider::sub-page:horizontal {
    background: #0284c7;
    border-radius: 3px;
}

QSlider::handle:horizontal {
    background: #38bdf8;
    border: 1px solid #0284c7;
    width: 16px;
    margin-top: -5px;
    margin-bottom: -5px;
    border-radius: 8px;
}

QSlider::handle:horizontal:hover {
    background: #7dd3fc;
}

QLabel {
    color: #cbd5e1;
}

QHeaderView::section {
    background-color: #1e1e28;
    color: #94a3b8;
    padding: 6px;
    border: none;
    font-weight: 600;
}
"""
