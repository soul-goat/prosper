import sys
import os
import json
import requests
import re
import time
from datetime import datetime
from PyQt5.QtWidgets import *
from PyQt5.QtCore import QTimer, Qt, QPoint, QRect, QRectF, QSize, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt5.QtGui import QFont, QCursor, QColor, QPainter, QPen, QPainterPath

# =============== 高DPI设置 ===============
if hasattr(Qt, 'AA_EnableHighDpiScaling'):
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

# ==================== 自定义圆角按钮 ====================
class RoundedButton(QPushButton):
    def __init__(self, text="", parent=None, bg_color=None, hover_color=None, pressed_color=None):
        super().__init__(text, parent)
        self._hovered = False
        self._pressed = False
        self.bg_color = bg_color or QColor(59, 130, 246)
        self.hover_color = hover_color or self.bg_color.lighter(110)
        self.pressed_color = pressed_color or QColor(30, 64, 175)
        self.setFlat(True)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect().adjusted(1, 1, -1, -1)
        rectf = QRectF(rect)  # ✅ 修复：QRect → QRectF

        if self._pressed:
            color = self.pressed_color
        elif self._hovered:
            color = self.hover_color
        else:
            color = self.bg_color

        path = QPainterPath()
        radius = min(rect.width(), rect.height()) * 0.15
        path.addRoundedRect(rectf, radius, radius)  # ✅ 使用 rectf
        painter.fillPath(path, color)

        painter.setPen(QColor(255, 255, 255))
        painter.setFont(self.font())
        painter.drawText(rect, Qt.AlignCenter, self.text())

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._pressed = False
            self.update()
        super().mouseReleaseEvent(event)

# ==================== 配置 ====================
DATA_FILE = "watchlist.json"
HISTORY_FILE = "history.json"
REFRESH_INTERVAL = 10000
EDGE_THRESHOLD = 50
MIN_WIDTH = 350
SWITCH_THRESHOLD = 800
FULL_MODE_MAX_WIDTH = 1200
FLOAT_BUTTON_SIZE = 50
DEFAULT_FONT_FAMILY = "Microsoft YaHei UI"
DEFAULT_FONT_SIZE = 10

# ==================== 工具函数 ====================
def get_weather_icon(growth):
    if growth > 3.5:
        return "☀️"
    elif growth > 1.5:
        return "⛅"
    elif growth > -1.5:
        return "☁️"
    else:
        return "⛈️"

def get_app_font(base_size=DEFAULT_FONT_SIZE, size_adjust=0, bold=False):
    point_size = int(round(base_size + size_adjust))
    font = QFont(DEFAULT_FONT_FAMILY, point_size)
    font.setBold(bold)
    return font

# ==================== 数据获取器 ====================
class DataFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.timeout = 10
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def get_fund_estimate(self, code):
        url = f"http://fundgz.1234567.com.cn/js/{code}.js"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            text = resp.text.strip()
            if not text.startswith('jsonpgz('):
                return None
            match = re.search(r'jsonpgz\((.*)\)', text)
            if not match:
                return None
            data = json.loads(match.group(1))
            return {
                "name": data["name"],
                "dwjz": float(data["dwjz"]),
                "gsz": float(data["gsz"]),
                "growth": float(data["gszzl"]),
                "time": data["gztime"]
            }
        except Exception as e:
            print(f"获取基金 {code} 数据失败: {str(e)}")
            return None

# ==================== 历史收益管理 ====================
class HistoryManager:
    def __init__(self):
        self.history = {}
        self.load()

    def load(self):
        if os.path.exists(HISTORY_FILE):
            try:
                with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.history = data if isinstance(data, dict) else {}
            except Exception as e:
                print(f"加载历史记录失败: {str(e)}")
                self.history = {}
        else:
            self.history = {}

    def save(self):
        try:
            with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存历史记录失败: {str(e)}")

    def record_closed_profit(self, code, name, profit, shares, cost, close_time=None):
        if close_time is None:
            close_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if code not in self.history:
            self.history[code] = {"name": name, "closed_positions": []}
        closed_position = {"profit": profit, "shares": shares, "cost": cost, "close_time": close_time}
        self.history[code]["closed_positions"].append(closed_position)
        self.save()

    def get_total_closed_profit(self, code=None):
        total = 0.0
        if code:
            if code in self.history:
                for pos in self.history[code]["closed_positions"]:
                    total += pos["profit"]
        else:
            for fund in self.history.values():
                for pos in fund["closed_positions"]:
                    total += pos["profit"]
        return total

    def get_fund_history(self, code):
        return self.history.get(code, None)

# ==================== 自选管理 ====================
class FundManager:
    def __init__(self):
        self.watchlist = []
        self.history_manager = HistoryManager()
        self.load()

    def load(self):
        if os.path.exists(DATA_FILE):
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.watchlist = data.get("funds", [])
                    for fund in self.watchlist:
                        fund.setdefault("last_profit", 0.0)
                        fund.setdefault("is_closed", False)
            except Exception as e:
                print(f"加载自选列表失败: {str(e)}")

    def save(self):
        try:
            with open(DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump({"funds": self.watchlist}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存自选列表失败: {str(e)}")

    def update_fund(self, code, cost=None, shares=None):
        for fund in self.watchlist:
            if fund["code"] == code:
                old_shares = fund.get("shares", 0)
                current_shares = shares if shares is not None else old_shares
                if old_shares > 0 and current_shares == 0:
                    dwjz = fund.get("dwjz", 0)
                    gsz = fund.get("gsz", dwjz)
                    closed_profit = old_shares * (gsz - fund.get("cost", 0))
                    self.history_manager.record_closed_profit(
                        code, fund.get("name", code), closed_profit, old_shares, fund.get("cost", 0)
                    )
                    fund["last_profit"] = closed_profit
                if cost is not None:
                    fund["cost"] = float(cost)
                if shares is not None:
                    fund["shares"] = float(shares)
                if fund.get("is_closed") and shares and shares > 0:
                    fund["is_closed"] = False
                self.save()
                return True
        return False

    def remove_fund(self, code):
        for fund in self.watchlist:
            if fund["code"] == code and fund["shares"] > 0:
                dwjz = fund.get("dwjz", 0)
                gsz = fund.get("gsz", dwjz)
                closed_profit = fund["shares"] * (gsz - fund["cost"])
                self.history_manager.record_closed_profit(
                    code, fund.get("name", code), closed_profit, fund["shares"], fund["cost"]
                )
        self.watchlist = [f for f in self.watchlist if f["code"] != code]
        self.save()

# ==================== 悬浮按钮 ====================
class FloatingButton(QWidget):
    clicked = pyqtSignal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(FLOAT_BUTTON_SIZE, FLOAT_BUTTON_SIZE)
        self.hide()
        self.is_hovered = False

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.is_hovered:
            shadow_color = QColor(0, 0, 0, 60)
            for i in range(3):
                shadow_rect = QRect(i+2, i+2, self.width()-4-i, self.height()-4-i)
                painter.setBrush(shadow_color)
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(shadow_rect)
        bg_color = QColor(37, 99, 235, 230) if not self.is_hovered else QColor(59, 130, 246, 240)
        painter.setBrush(bg_color)
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(5, 5, FLOAT_BUTTON_SIZE - 10, FLOAT_BUTTON_SIZE - 10)
        painter.setPen(QColor(255, 255, 255))
        painter.setFont(get_app_font(DEFAULT_FONT_SIZE, 2, True))
        painter.drawText(self.rect(), Qt.AlignCenter, "📈")

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def enterEvent(self, event):
        self.is_hovered = True
        self.update()
        self.setCursor(Qt.PointingHandCursor)

    def leaveEvent(self, event):
        self.is_hovered = False
        self.update()

# ==================== 可伸缩窗口基类 ====================
class ResizableWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.dragging = False
        self.resizing = False
        self.resize_edge = None
        self.drag_offset = QPoint()
        self.resize_margin = 10
        self.is_hidden = False
        self.hidden_side = None
        self.min_width = MIN_WIDTH
        self.max_width = SWITCH_THRESHOLD
        self.float_button = FloatingButton()
        self.float_button.clicked.connect(self.show_from_hidden)
        self.setMouseTracking(True)

    def get_resize_edge(self, pos):
        rect = self.rect()
        corner_size = self.resize_margin * 2
        if pos.x() <= corner_size and pos.y() <= corner_size:
            return 'top-left'
        elif pos.x() >= rect.width() - corner_size and pos.y() <= corner_size:
            return 'top-right'
        elif pos.x() <= corner_size and pos.y() >= rect.height() - corner_size:
            return 'bottom-left'
        elif pos.x() >= rect.width() - corner_size and pos.y() >= rect.height() - corner_size:
            return 'bottom-right'
        if pos.x() <= self.resize_margin:
            return 'left'
        elif pos.x() >= rect.width() - self.resize_margin:
            return 'right'
        elif pos.y() <= self.resize_margin:
            return 'top'
        elif pos.y() >= rect.height() - self.resize_margin:
            return 'bottom'
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            edge = self.get_resize_edge(event.pos())
            if edge:
                self.resizing = True
                self.resize_edge = edge
                self.drag_offset = event.globalPos()
                self.initial_geometry = self.geometry()
            elif event.pos().y() < 50:
                self.dragging = True
                self.drag_offset = event.pos()

    def mouseMoveEvent(self, event):
        if self.resizing and self.resize_edge:
            delta = event.globalPos() - self.drag_offset
            rect = self.geometry()
            if self.resize_edge == 'right':
                new_width = max(self.min_width, min(self.initial_geometry.width() + delta.x(), self.max_width))
                self.setGeometry(rect.x(), rect.y(), new_width, rect.height())
            elif self.resize_edge == 'left':
                new_width = max(self.min_width, min(self.initial_geometry.width() - delta.x(), self.max_width))
                new_x = self.initial_geometry.x() + (self.initial_geometry.width() - new_width)
                self.setGeometry(new_x, rect.y(), new_width, rect.height())
            elif self.resize_edge == 'bottom':
                new_height = max(400, self.initial_geometry.height() + delta.y())
                self.setGeometry(rect.x(), rect.y(), rect.width(), new_height)
            elif self.resize_edge == 'top':
                new_height = max(400, self.initial_geometry.height() - delta.y())
                new_y = self.initial_geometry.y() + (self.initial_geometry.height() - new_height)
                self.setGeometry(rect.x(), new_y, rect.width(), new_height)
            elif self.resize_edge == 'bottom-right':
                new_w = max(self.min_width, min(self.initial_geometry.width() + delta.x(), self.max_width))
                new_h = max(400, self.initial_geometry.height() + delta.y())
                self.setGeometry(rect.x(), rect.y(), new_w, new_h)
            elif self.resize_edge == 'bottom-left':
                new_w = max(self.min_width, min(self.initial_geometry.width() - delta.x(), self.max_width))
                new_h = max(400, self.initial_geometry.height() + delta.y())
                new_x = self.initial_geometry.x() + (self.initial_geometry.width() - new_w)
                self.setGeometry(new_x, rect.y(), new_w, new_h)
            elif self.resize_edge == 'top-right':
                new_w = max(self.min_width, min(self.initial_geometry.width() + delta.x(), self.max_width))
                new_h = max(400, self.initial_geometry.height() - delta.y())
                new_y = self.initial_geometry.y() + (self.initial_geometry.height() - new_h)
                self.setGeometry(rect.x(), new_y, new_w, new_h)
            elif self.resize_edge == 'top-left':
                new_w = max(self.min_width, min(self.initial_geometry.width() - delta.x(), self.max_width))
                new_h = max(400, self.initial_geometry.height() - delta.y())
                new_x = self.initial_geometry.x() + (self.initial_geometry.width() - new_w)
                new_y = self.initial_geometry.y() + (self.initial_geometry.height() - new_h)
                self.setGeometry(new_x, new_y, new_w, new_h)
        elif self.dragging:
            self.move(self.mapToGlobal(event.pos() - self.drag_offset))
        else:
            edge = self.get_resize_edge(event.pos())
            cursor_map = {
                'left': Qt.SizeHorCursor, 'right': Qt.SizeHorCursor,
                'top': Qt.SizeVerCursor, 'bottom': Qt.SizeVerCursor,
                'top-left': Qt.SizeFDiagCursor, 'bottom-right': Qt.SizeFDiagCursor,
                'top-right': Qt.SizeBDiagCursor, 'bottom-left': Qt.SizeBDiagCursor
            }
            self.setCursor(cursor_map.get(edge, Qt.ArrowCursor))

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            was_resizing = self.resizing
            self.dragging = False
            self.resizing = False
            self.resize_edge = None
            self.setCursor(Qt.ArrowCursor)
            if not was_resizing:
                self.check_edge_snap()

    def check_edge_snap(self):
        screen = QApplication.primaryScreen().geometry()
        x = self.x()
        if x + self.width() > screen.width() - EDGE_THRESHOLD:
            self.hide_to_edge('right')
        elif x < EDGE_THRESHOLD:
            self.hide_to_edge('left')

    def hide_to_edge(self, side):
        if self.is_hidden:
            return
        self.is_hidden = True
        self.hidden_side = side
        screen = QApplication.primaryScreen().geometry()
        animation = QPropertyAnimation(self, b"pos")
        animation.setDuration(300)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        if side == 'right':
            target_x = screen.width() - 5
            button_x = screen.width() - FLOAT_BUTTON_SIZE - 10
        else:
            target_x = -self.width() + 5
            button_x = 10
        y = self.y()
        animation.setEndValue(QPoint(target_x, y))
        animation.finished.connect(lambda: self.on_hide_finished(button_x, y + (self.height() - FLOAT_BUTTON_SIZE) // 2))
        animation.start()
        self.hide_animation = animation

    def on_hide_finished(self, button_x, button_y):
        self.hide()
        self.float_button.move(button_x, button_y)
        self.float_button.show()

    def show_from_hidden(self):
        if not self.is_hidden:
            return
        self.float_button.hide()
        self.show()
        screen = QApplication.primaryScreen().geometry()
        animation = QPropertyAnimation(self, b"pos")
        animation.setDuration(300)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        if self.hidden_side == 'right':
            target_x = screen.width() - self.width() - 20
        else:
            target_x = 20
        animation.setEndValue(QPoint(target_x, self.y()))
        animation.finished.connect(lambda: setattr(self, 'is_hidden', False))
        animation.start()
        self.show_animation = animation
        self.hidden_side = None

# ==================== 极简模式窗口 ====================
class SimpleWindow(ResizableWindow):
    switch_to_full = pyqtSignal()
    def __init__(self, fund_manager, fetcher):
        super().__init__()
        self._switching = False
        self.fund_manager = fund_manager
        self.fetcher = fetcher
        self.timer = None
        self.current_data = []
        self.init_ui()
        QTimer.singleShot(800, self.refresh_data)

    def init_ui(self):
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFont(get_app_font(DEFAULT_FONT_SIZE))
        self.container = QWidget(self)
        self.container.setObjectName("container")
        self.container.setStyleSheet("""
        #container {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 rgba(255, 255, 255, 250),
                stop:1 rgba(248, 250, 252, 250));
            border-radius: 16px;
            border: 2px solid rgba(59, 130, 246, 0.3);
        }
        """)
        layout = QVBoxLayout(self.container)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)
        title_bar = self.create_title_bar()
        layout.addWidget(title_bar)
        self.list_widget = QListWidget()
        self.list_widget.setFont(get_app_font(DEFAULT_FONT_SIZE))
        self.list_widget.setStyleSheet("""
        QListWidget {
            border: none;
            background: transparent;
            outline: none;
        }
        QListWidget::item {
            border-bottom: 1px solid rgba(226, 232, 240, 0.8);
            padding: 8px 6px;
            min-height: 28px;
            border-radius: 6px;
        }
        QListWidget::item:hover {
            background: rgba(219, 234, 254, 120);
        }
        QListWidget::item:selected {
            background: rgba(191, 219, 254, 180);
        }
        """)
        layout.addWidget(self.list_widget)
        self.status_label = QLabel("正在初始化...")
        self.status_label.setFont(get_app_font(DEFAULT_FONT_SIZE, 0, True))
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #64748b; padding: 5px;")
        layout.addWidget(self.status_label)
        self.switch_to_full_btn = QPushButton("⇄ 切换到完整版")
        self.switch_to_full_btn.setFont(get_app_font(DEFAULT_FONT_SIZE, 1, True))
        self.switch_to_full_btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #60a5fa, stop:1 #3b82f6);
            color: white;
            border: none;
            border-radius: 8px;
            padding: 6px 12px;
            font-weight: bold;
        }
        QPushButton:hover {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3b82f6, stop:1 #2563eb);
        }
        """)
        self.switch_to_full_btn.setFixedHeight(35)
        self.switch_to_full_btn.clicked.connect(self.switch_to_full_mode)
        layout.addWidget(self.switch_to_full_btn)
        self.summary_label = QLabel("正在初始化...")
        self.summary_label.setFont(get_app_font(DEFAULT_FONT_SIZE, 1, True))
        self.summary_label.setAlignment(Qt.AlignCenter)
        self.summary_label.setStyleSheet("""
        color: white;
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 rgba(59, 130, 246, 230),
            stop:1 rgba(37, 99, 235, 230));
        padding: 14px;
        border-radius: 10px;
        font-weight: bold;
        """)
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.container)
        self.resize(320, 450)
        self.setMinimumSize(MIN_WIDTH, 400)
        self.setMaximumWidth(SWITCH_THRESHOLD)
        screen = QApplication.primaryScreen().geometry()
        x = max(0, screen.width() - self.width() - 30)
        y = max(0, (screen.height() - self.height()) // 2)
        self.move(x, y)

    def switch_to_full_mode(self):
        if self._switching:
            return
        self._switching = True
        self.switch_to_full.emit()

    def create_title_bar(self):
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(10)
        title = QLabel("📈 基金助手")
        title.setFont(get_app_font(DEFAULT_FONT_SIZE, 2, True))
        title.setStyleSheet("color: #1e40af;")
        title.setCursor(Qt.SizeAllCursor)
        layout.addWidget(title, 1)
        hide_btn = QPushButton("📌")
        hide_btn.setFont(get_app_font(DEFAULT_FONT_SIZE))
        hide_btn.setToolTip("隐藏到边缘")
        hide_btn.clicked.connect(self.manual_hide)
        hide_btn.setFixedSize(28, 28)
        hide_btn.setStyleSheet(self.get_button_style("#dbeafe", "#bfdbfe"))
        refresh_btn = QPushButton("🔄")
        refresh_btn.setFont(get_app_font(DEFAULT_FONT_SIZE))
        refresh_btn.setToolTip("立即刷新")
        refresh_btn.clicked.connect(self.refresh_data)
        refresh_btn.setFixedSize(28, 28)
        refresh_btn.setStyleSheet(self.get_button_style("#dbeafe", "#bfdbfe"))
        close_btn = QPushButton("×")
        close_btn.setFont(get_app_font(DEFAULT_FONT_SIZE, 2, True))
        close_btn.setToolTip("退出")
        close_btn.clicked.connect(self.close)
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(self.get_button_style("#fee2e2", "#fecaca", "#dc2626"))
        layout.addWidget(hide_btn)
        layout.addWidget(refresh_btn)
        layout.addWidget(close_btn)
        return title_bar

    def get_button_style(self, bg_color, hover_color, text_color=""):
        text_style = f"color: {text_color};" if text_color else ""
        return f"""
        QPushButton {{
            border: none;
            background: {bg_color};
            {text_style}
            border-radius: 14px;
            font-size: {DEFAULT_FONT_SIZE}px;
        }}
        QPushButton:hover {{
            background: {hover_color};
        }}
        """

    def manual_hide(self):
        screen = QApplication.primaryScreen().geometry()
        if self.pos().x() > screen.width() // 2:
            self.hide_to_edge('right')
        else:
            self.hide_to_edge('left')

    def setup_timer(self):
        if self.timer is None:
            self.timer = QTimer()
            self.timer.timeout.connect(self.refresh_data)
            self.timer.start(REFRESH_INTERVAL)

    def refresh_data(self):
        if self.timer is None:
            self.setup_timer()
        self.status_label.setText("🔄 正在刷新...")
        self.status_label.setStyleSheet("color: #2563eb;")
        QApplication.processEvents()
        self.update_data()

    def update_data(self):
        try:
            funds = self.fund_manager.watchlist
            if not funds:
                self.list_widget.clear()
                self.summary_label.setText("暂无持仓数据\n点击完整版添加基金")
                self.status_label.setText("无数据")
                self.status_label.setStyleSheet("color: #64748b;")
                return
            self.list_widget.clear()
            total_today_profit = 0
            total_yesterday_value = 0
            total_value = 0
            total_cost = 0
            total_closed_profit = self.fund_manager.history_manager.get_total_closed_profit()
            for fund in funds:
                est = self.fetcher.get_fund_estimate(fund["code"])
                if est:
                    name = fund.get("name", est["name"])
                    growth = est["growth"]
                    shares = fund["shares"]
                    dwjz = est["dwjz"]
                    gsz = est["gsz"]
                    today_profit = shares * (gsz - dwjz)
                    name_display = name[:8] + ".." if len(name) > 10 else name
                    item_text = f"{name_display}  {growth:+.2f}%  {today_profit:+.2f}元"
                    item = QListWidgetItem(item_text)
                    item.setFont(get_app_font(DEFAULT_FONT_SIZE))
                    if growth > 0:
                        item.setForeground(QColor(220, 38, 38))
                    elif growth < 0:
                        item.setForeground(QColor(21, 128, 61))
                    else:
                        item.setForeground(QColor(75, 85, 99))
                    item.setData(Qt.UserRole, {
                        "code": fund["code"],
                        "name": name,
                        "growth": growth,
                        "today_profit": today_profit
                    })
                    self.list_widget.addItem(item)
                    total_yesterday_value += shares * dwjz
                    total_today_profit += today_profit
                    total_value += shares * gsz
                    total_cost += shares * fund["cost"]
            total_profit = (total_value - total_cost) + total_closed_profit
            total_rate = (total_profit / (total_cost + 1e-6)) * 100
            today_rate = (total_today_profit / (total_yesterday_value + 1e-6)) * 100
            today_icon = get_weather_icon(today_rate)
            total_icon = get_weather_icon(total_rate)
            summary_text = f"{today_icon} 今日: {total_today_profit:+.2f}元 ({today_rate:+.2f}%)\n{total_icon} 累计: {total_profit:+.2f}元 ({total_rate:+.2f}%)"
            if total_closed_profit > 0:
                summary_text += f"\n(历史收益: +{total_closed_profit:.2f}元)"
            elif total_closed_profit < 0:
                summary_text += f"\n(历史收益: {total_closed_profit:.2f}元)"
            self.summary_label.setText(summary_text)
            current_time = datetime.now().strftime("%H:%M:%S")
            self.status_label.setText(f"已更新: {current_time}")
            self.status_label.setStyleSheet("color: #047857;")
        except Exception as e:
            print(f"更新数据失败: {str(e)}")
            self.status_label.setText(f"❌ 更新失败: {str(e)}")
            self.status_label.setStyleSheet("color: #dc2626;")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'container'):
            self.container.setGeometry(0, 0, self.width(), self.height())
        if self._switching or not self.isVisible():
            return
        if self.width() >= SWITCH_THRESHOLD - 5:
            self._switching = True
            self.switch_to_full.emit()

    def closeEvent(self, event):
        if self.timer and self.timer.isActive():
            self.timer.stop()
        self.float_button.close()
        event.accept()

# ==================== 完整模式窗口 ====================
class FullWindow(ResizableWindow):
    switch_to_simple = pyqtSignal()
    def __init__(self, fund_manager, fetcher):
        super().__init__()
        self.fund_manager = fund_manager
        self.fetcher = fetcher
        self.timer = None
        self.show_search_panel = True
        self.last_search_text = ""
        self.min_width = SWITCH_THRESHOLD
        self.max_width = FULL_MODE_MAX_WIDTH
        self.base_font_size = DEFAULT_FONT_SIZE
        self.dynamic_font_size = self.base_font_size
        self.init_ui()
        self.setup_timer()

    def init_ui(self):
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.FramelessWindowHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.container = QWidget(self)
        self.container.setObjectName("container")
        main_layout = QVBoxLayout(self.container)
        main_layout.setContentsMargins(18, 18, 18, 18)
        main_layout.setSpacing(14)
        title_bar = self.create_title_bar()
        main_layout.addWidget(title_bar)
        self.search_panel = QWidget()
        search_panel_layout = QVBoxLayout(self.search_panel)
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("输入基金代码（如 001186）")
        self.search_input.setFixedHeight(42)
        self.search_input.returnPressed.connect(self.search_fund)
        self.search_btn = QPushButton("🔍 搜索")
        self.search_btn.setFixedHeight(42)
        self.search_btn.clicked.connect(self.search_fund)
        search_layout.addWidget(self.search_input, 4)
        search_layout.addWidget(self.search_btn, 1)
        search_panel_layout.addLayout(search_layout)
        self.search_result_label = QLabel("")
        self.search_result_label.setWordWrap(True)
        self.search_result_label.hide()
        search_panel_layout.addWidget(self.search_result_label)
        self.add_group = QGroupBox("买入基金设置")
        self.add_group.setFont(get_app_font(self.dynamic_font_size, 1, True))
        self.add_group.setVisible(False)
        add_layout = QVBoxLayout()
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignRight)
        self.cost_input = QLineEdit()
        self.cost_input.setPlaceholderText("自动填充昨日净值")
        self.cost_input.setFixedHeight(38)
        self.shares_input = QLineEdit()
        self.shares_input.setPlaceholderText("输入购买份额")
        self.shares_input.setFixedHeight(38)
        self.amount_input = QLineEdit()
        self.amount_input.setPlaceholderText("输入买入金额")
        self.amount_input.setFixedHeight(38)
        self.amount_input.textChanged.connect(self.amount_to_shares)
        self.shares_input.textChanged.connect(self.shares_to_amount)
        add_btn = QPushButton("🔥 添加到自选")
        add_btn.setFont(get_app_font(self.dynamic_font_size, 0, True))
        add_btn.setFixedHeight(40)
        add_btn.clicked.connect(self.add_new_fund)
        form_layout.addRow("成本价 (元):", self.cost_input)
        form_layout.addRow("份额:", self.shares_input)
        form_layout.addRow("金额 (元):", self.amount_input)
        form_layout.addRow("", add_btn)
        add_layout.addLayout(form_layout)
        self.add_group.setLayout(add_layout)
        search_panel_layout.addWidget(self.add_group)
        main_layout.addWidget(self.search_panel)
        self.table = QTableWidget()
        self.table.setColumnCount(9)
        self.table.setHorizontalHeaderLabels([
            "代码", "名称", "成本价", "份额", "预估净值",
            "今日涨幅", "今日收益", "累计收益", "操作"
        ])
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(True)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(8, QHeaderView.Fixed)
        header.resizeSection(8, 120)
        self.table.cellDoubleClicked.connect(self.on_cell_double_clicked)
        main_layout.addWidget(self.table)
        self.summary_box = QWidget()
        summary_layout = QHBoxLayout(self.summary_box)
        summary_layout.setSpacing(30)
        self.today_label = QLabel("今日: +0.00元 (+0.00%)")
        self.today_label.setFont(get_app_font(self.dynamic_font_size, 2, True))
        self.total_label = QLabel("累计: +0.00元 (+0.00%)")
        self.total_label.setFont(get_app_font(self.dynamic_font_size, 2, True))
        self.history_label = QLabel("历史: +0.00元")
        self.history_label.setFont(get_app_font(self.dynamic_font_size, 2, True))
        summary_layout.addWidget(self.today_label)
        summary_layout.addWidget(self.total_label)
        summary_layout.addWidget(self.history_label)
        summary_layout.addStretch()
        main_layout.addWidget(self.summary_box)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.container)
        self.resize(SWITCH_THRESHOLD + 100, 400)
        self.setMinimumSize(SWITCH_THRESHOLD, 500)
        self.setMaximumWidth(FULL_MODE_MAX_WIDTH)
        screen = QApplication.primaryScreen().geometry()
        x = max(0, (screen.width() - self.width()) // 2)
        y = max(0, (screen.height() - self.height()) // 2)
        self.move(x, y)
        self.update_font_sizes()

    def get_dynamic_font_size(self):
        base_size = DEFAULT_FONT_SIZE
        min_size = 9
        max_size = 16
        width_factor = min(2.0, max(0.8, self.width() / 800))
        dynamic_size = base_size * width_factor
        return max(min_size, min(max_size, dynamic_size))

    def update_font_sizes(self):
        self.dynamic_font_size = self.get_dynamic_font_size()
        self.setFont(get_app_font(self.dynamic_font_size))
        self.update_stylesheet()
        self.update_table_style()
        self.update_summary_style()
        self.search_input.setFont(get_app_font(self.dynamic_font_size))
        self.search_btn.setFont(get_app_font(self.dynamic_font_size, 0, True))
        self.search_result_label.setFont(get_app_font(self.dynamic_font_size))
        self.cost_input.setFont(get_app_font(self.dynamic_font_size))
        self.shares_input.setFont(get_app_font(self.dynamic_font_size))
        self.amount_input.setFont(get_app_font(self.dynamic_font_size))
        self.add_group.setFont(get_app_font(self.dynamic_font_size, 1, True))
        self.table.setFont(get_app_font(self.dynamic_font_size))
        header = self.table.horizontalHeader()
        if header:
            header.setFont(get_app_font(self.dynamic_font_size, 0, True))
        row_height = max(30, int(self.dynamic_font_size * 3.5))
        self.table.verticalHeader().setDefaultSectionSize(row_height)
        self.today_label.setFont(get_app_font(self.dynamic_font_size, 2, True))
        self.total_label.setFont(get_app_font(self.dynamic_font_size, 2, True))
        self.history_label.setFont(get_app_font(self.dynamic_font_size, 2, True))
        self.update_title_bar_buttons()

    def update_title_bar_buttons(self):
        btn_height = int(self.dynamic_font_size * 2.2)
        for btn in [self.toggle_search_btn, self.hide_btn, self.refresh_btn, self.minimize_btn, self.close_btn]:
            if btn.objectName() != "close_btn":
                btn.setFixedHeight(btn_height)
            else:
                btn.setFixedSize(btn_height, btn_height)

    def update_stylesheet(self):
        font_size = self.dynamic_font_size
        self.container.setStyleSheet(f"""
        #container {{
            background: white;
            border-radius: 16px;
            border: 2px solid rgba(59, 130, 246, 0.3);
        }}
        QLineEdit {{
            padding: {int(font_size * 0.8)}px {int(font_size * 1.2)}px;
            border: 2px solid #e2e8f0;
            border-radius: 8px;
            background: white;
            font-size: {font_size}px;
        }}
        QLineEdit:focus {{
            border: 2px solid #3b82f6;
        }}
        QPushButton {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3b82f6, stop:1 #2563eb);
            color: white;
            border: none;
            border-radius: 8px;
            padding: {int(font_size * 0.8)}px {int(font_size * 1.5)}px;
            font-weight: bold;
            font-size: {font_size}px;
        }}
        QPushButton:hover {{
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #2563eb, stop:1 #1d4ed8);
        }}
        QPushButton:pressed {{
            background: #1e40af;
        }}
        QGroupBox {{
            font-weight: bold;
            border: 2px solid #dbeafe;
            border-radius: 10px;
            margin-top: 14px;
            padding-top: 14px;
            font-size: {font_size + 1}px;
            color: #1e40af;
        }}
        QGroupBox::title {{
            subcontrol-origin: margin;
            left: 14px;
            padding: 0 10px;
        }}
        QLabel {{
            font-size: {font_size}px;
        }}
        """)

    def update_table_style(self):
        font_size = self.dynamic_font_size
        self.table.setStyleSheet(f"""
        QTableWidget {{
            border: 1px solid #e2e8f0;
            border-radius: 8px;
            gridline-color: #f1f5f9;
            font-size: {font_size}px;
        }}
        QTableWidget::item {{
            padding: 8px 6px;
        }}
        QHeaderView::section {{
            background-color: #f8fafc;
            padding: 10px;
            border: none;
            font-size: {font_size}px;
            font-weight: bold;
            color: #1e293b;
        }}
        QScrollBar:vertical {{
            border: none;
            background: #f1f5f9;
            width: {max(12, int(font_size * 1.2))}px;
            margin: 0px 0px 0px 0px;
        }}
        QScrollBar::handle:vertical {{
            background: #cbd5e1;
            min-height: {max(20, int(font_size * 2))}px;
            border-radius: {max(6, int(font_size * 0.6))}px;
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
        }}
        """)

    def update_summary_style(self):
        font_size = self.dynamic_font_size
        self.summary_box.setStyleSheet(f"""
        QWidget {{
            background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                stop:0 #3b82f6, stop:1 #2563eb);
            border-radius: 12px;
            padding: {int(font_size * 1.2)}px;
        }}
        QLabel {{
            color: white;
            font-size: {font_size + 1}px;
            font-weight: bold;
        }}
        """)

    def create_title_bar(self):
        title_bar = QWidget()
        title_bar.setFixedHeight(50)
        title_bar.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(title_bar)
        layout.setContentsMargins(10, 0, 10, 0)
        layout.setSpacing(12)
        title = QLabel("📈 基金助手 - 完整版")
        title.setFont(get_app_font(self.dynamic_font_size, 3, True))
        title.setStyleSheet("color: #1e40af;")
        title.setCursor(Qt.SizeAllCursor)
        layout.addWidget(title, 1)

        self.toggle_search_btn = RoundedButton("-", self,
            bg_color=QColor(219, 234, 254),
            hover_color=QColor(191, 219, 254),
            pressed_color=QColor(147, 197, 253)
        )
        self.toggle_search_btn.setToolTip("隐藏搜索面板")
        self.toggle_search_btn.clicked.connect(self.toggle_search_panel)
        self.toggle_search_btn.setFixedSize(34, 34)

        self.hide_btn = RoundedButton("📌 隐藏", self,
            bg_color=QColor(219, 234, 254),
            hover_color=QColor(191, 219, 254),
            pressed_color=QColor(147, 197, 253)
        )
        self.hide_btn.setToolTip("隐藏到边缘")
        self.hide_btn.clicked.connect(self.manual_hide)
        self.hide_btn.setFixedHeight(34)

        self.refresh_btn = RoundedButton("🔄 刷新", self,
            bg_color=QColor(219, 234, 254),
            hover_color=QColor(191, 219, 254),
            pressed_color=QColor(147, 197, 253)
        )
        self.refresh_btn.setToolTip("立即刷新")
        self.refresh_btn.clicked.connect(self.refresh_data)
        self.refresh_btn.setFixedHeight(34)

        self.minimize_btn = RoundedButton("⇄ 简洁版", self,
            bg_color=QColor(254, 243, 199),
            hover_color=QColor(253, 230, 138),
            pressed_color=QColor(180, 83, 9)
        )
        self.minimize_btn.setToolTip("切换到极简版")
        self.minimize_btn.clicked.connect(self.switch_to_simple.emit)
        self.minimize_btn.setFixedHeight(34)

        self.close_btn = RoundedButton("×", self,
            bg_color=QColor(255, 226, 226),
            hover_color=QColor(254, 204, 204),
            pressed_color=QColor(220, 38, 38)
        )
        self.close_btn.setToolTip("退出")
        self.close_btn.clicked.connect(self.close)
        self.close_btn.setFixedSize(34, 34)

        layout.addWidget(self.toggle_search_btn)
        layout.addWidget(self.hide_btn)
        layout.addWidget(self.refresh_btn)
        layout.addWidget(self.minimize_btn)
        layout.addWidget(self.close_btn)
        return title_bar

    def toggle_search_panel(self):
        self.show_search_panel = not self.show_search_panel
        self.search_panel.setVisible(self.show_search_panel)
        self.toggle_search_btn.setText("-" if self.show_search_panel else "+")
        self.toggle_search_btn.setToolTip("隐藏搜索面板" if self.show_search_panel else "显示搜索面板")

    def manual_hide(self):
        screen = QApplication.primaryScreen().geometry()
        if self.pos().x() > screen.width() // 2:
            self.hide_to_edge('right')
        else:
            self.hide_to_edge('left')

    def setup_timer(self):
        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_data)
        self.timer.start(REFRESH_INTERVAL)
        QTimer.singleShot(500, self.refresh_data)

    def search_fund(self):
        code = self.search_input.text().strip()
        if not code:
            self.show_message("⚠️ 请输入基金代码", "error")
            return
        if code == self.last_search_text:
            return
        self.last_search_text = code
        self.search_btn.setEnabled(False)
        self.search_btn.setText("搜索中...")
        self.search_result_label.setText("🔍 正在搜索基金数据...")
        self.search_result_label.show()
        QApplication.processEvents()
        est = self.fetcher.get_fund_estimate(code)
        self.search_btn.setEnabled(True)
        self.search_btn.setText("🔍 搜索")
        if est:
            self.code_input = code
            self.name_input = est["name"]
            self.cost_input.setText(f"{est['dwjz']:.4f}")
            result_text = f"✅ 找到基金: {est['name']}\n昨日净值: {est['dwjz']:.4f}元  预估净值: {est['gsz']:.4f}元  涨幅: {est['growth']:+.2f}%"
            self.search_result_label.setText(result_text)
            self.add_group.setVisible(True)
            self.cost_input.setFocus()
        else:
            self.search_result_label.setText(f"❌ 未找到基金代码: {code}")
            self.add_group.setVisible(False)

    def amount_to_shares(self):
        try:
            amount = float(self.amount_input.text())
            cost = float(self.cost_input.text())
            shares = amount / cost
            self.shares_input.blockSignals(True)
            self.shares_input.setText(f"{shares:.2f}")
            self.shares_input.blockSignals(False)
        except:
            pass

    def shares_to_amount(self):
        try:
            shares = float(self.shares_input.text())
            cost = float(self.cost_input.text())
            amount = shares * cost
            self.amount_input.blockSignals(True)
            self.amount_input.setText(f"{amount:.2f}")
            self.amount_input.blockSignals(False)
        except:
            pass

    def add_new_fund(self):
        code = getattr(self, 'code_input', None)
        name = getattr(self, 'name_input', None)
        try:
            cost = float(self.cost_input.text())
            shares = float(self.shares_input.text())
            if cost <= 0 or shares <= 0:
                self.show_message("⚠️ 成本价和份额必须大于0", "warning")
                return
        except ValueError:
            self.show_message("⚠️ 请输入有效的数字", "warning")
            return
        if not code or not name:
            self.show_message("⚠️ 请先搜索基金", "warning")
            return
        existing = [f for f in self.fund_manager.watchlist if f["code"] == code]
        if existing:
            self.show_message("⚠️ 该基金已在自选列表中", "warning")
            return
        new_fund = {
            "code": code,
            "name": name,
            "cost": cost,
            "shares": shares,
            "is_closed": False,
            "last_profit": 0.0
        }
        self.fund_manager.watchlist.append(new_fund)
        self.fund_manager.save()
        self.show_message(f"✅ 已添加 {name}", "info")
        self.clear_search_form()
        self.refresh_data()

    def clear_search_form(self):
        self.search_input.clear()
        self.cost_input.clear()
        self.shares_input.clear()
        self.amount_input.clear()
        self.search_result_label.hide()
        self.add_group.setVisible(False)
        self.last_search_text = ""

    def show_message(self, text, msg_type="info"):
        style_map = {
            "info": "#dbeafe",
            "warning": "#fee2e2",
            "error": "#fee2e2"
        }
        color_map = {
            "info": "#1e40af",
            "warning": "#b91c1c",
            "error": "#dc2626"
        }
        self.search_result_label.setStyleSheet(f"""
            color: {color_map[msg_type]};
            padding: {int(self.dynamic_font_size * 0.8)}px;
            background: {style_map[msg_type]};
            border-radius: 8px;
            font-size: {self.dynamic_font_size}px;
        """)
        self.search_result_label.setText(text)
        self.search_result_label.show()

    def on_cell_double_clicked(self, row, col):
        if col in (2, 3):  # 成本价 or 份额
            self.start_inline_edit(row, col)

    def start_inline_edit(self, row, col):
        item = self.table.item(row, col)
        if not item:
            return
        original_text = item.text()
        line_edit = QLineEdit(original_text)
        line_edit.setFont(get_app_font(self.dynamic_font_size))
        line_edit.setAlignment(Qt.AlignCenter)
        line_edit.setFixedHeight(self.table.rowHeight(row) - 8)
        line_edit.editingFinished.connect(lambda: self.finish_inline_edit(row, col, line_edit, original_text))
        self.table.setCellWidget(row, col, line_edit)
        line_edit.setFocus()
        line_edit.selectAll()

    def finish_inline_edit(self, row, col, editor, original_text):
        new_text = editor.text().strip()
        self.table.removeCellWidget(row, col)
        try:
            new_val = float(new_text)
            if col == 2:  # 成本价
                if new_val <= 0:
                    raise ValueError("成本价必须 > 0")
                cost = new_val
                shares = float(self.table.item(row, 3).text())
            else:  # 份额
                if new_val < 0:
                    raise ValueError("份额不能为负")
                shares = new_val
                cost = float(self.table.item(row, 2).text())
            code = self.table.item(row, 0).text()
            if self.fund_manager.update_fund(code, cost=cost, shares=shares):
                self.table.setItem(row, 2, QTableWidgetItem(f"{cost:.4f}"))
                self.table.setItem(row, 3, QTableWidgetItem(f"{shares:.2f}"))
                self.refresh_data()
            else:
                raise ValueError("更新失败")
        except Exception as e:
            self.table.setItem(row, col, QTableWidgetItem(original_text))
            QMessageBox.warning(self, "输入错误", f"无效输入:\n{str(e)}")

    def show_history(self, code, name):
        history = self.fund_manager.history_manager.get_fund_history(code)
        if not history:
            QMessageBox.information(self, "历史记录", f"基金 {name} 暂无历史记录")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{name} 历史记录")
        dialog.setMinimumSize(800, 400)
        layout = QVBoxLayout(dialog)
        table = QTableWidget()
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["时间", "份额", "成本价", "收益金额", "操作"])
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        positions = history["closed_positions"]
        table.setRowCount(len(positions))
        total_profit = 0
        for row, pos in enumerate(positions):
            table.setItem(row, 0, QTableWidgetItem(pos["close_time"]))
            table.setItem(row, 1, QTableWidgetItem(f"{pos['shares']:.2f}"))
            table.setItem(row, 2, QTableWidgetItem(f"{pos['cost']:.4f}"))
            profit = pos["profit"]
            total_profit += profit
            profit_item = QTableWidgetItem(f"{profit:+.2f}")
            if profit > 0:
                profit_item.setForeground(QColor(220, 38, 38))
            elif profit < 0:
                profit_item.setForeground(QColor(21, 128, 61))
            table.setItem(row, 3, profit_item)
            btn_widget = QWidget()
            btn_layout = QHBoxLayout(btn_widget)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setAlignment(Qt.AlignCenter)
            detail_btn = QPushButton("详情")
            detail_btn.setFixedSize(60, 25)
            detail_btn.setStyleSheet("""
            QPushButton {
                background: #dbeafe;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover {
                background: #bfdbfe;
            }
            """)
            detail_btn.clicked.connect(lambda checked, p=pos: self.show_position_detail(p))
            btn_layout.addWidget(detail_btn)
            table.setCellWidget(row, 4, btn_widget)
        header = table.horizontalHeader()
        for i in range(5):
            header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        layout.addWidget(table)
        total_label = QLabel(f"累计历史收益: {total_profit:+.2f}元")
        total_label.setFont(get_app_font(DEFAULT_FONT_SIZE, 1, True))
        total_label.setStyleSheet("color: #1e40af; font-weight: bold; padding: 10px;")
        layout.addWidget(total_label)
        close_btn = QPushButton("关闭")
        close_btn.setFixedHeight(35)
        close_btn.setStyleSheet("""
        QPushButton {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #3b82f6, stop:1 #2563eb);
            color: white;
            border: none;
            border-radius: 8px;
            font-weight: bold;
        }
        """)
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn)
        dialog.exec_()

    def show_position_detail(self, position):
        detail_text = (
            f"清仓详情:\n"
            f"收益金额: {position['profit']:+.2f}元\n"
            f"清仓份额: {position['shares']:.2f}\n"
            f"成本价格: {position['cost']:.4f}元\n"
            f"清仓时间: {position['close_time']}"
        )
        QMessageBox.information(self, "清仓详情", detail_text)

    def refresh_data(self):
        try:
            funds = self.fund_manager.watchlist
            if not funds:
                self.table.setRowCount(0)
                self.today_label.setText("今日: 暂无数据")
                self.total_label.setText("累计: 暂无数据")
                self.history_label.setText("历史: 0.00元")
                return
            self.table.setRowCount(len(funds))
            total_today_profit = 0
            total_yesterday_value = 0
            total_value = 0
            total_cost = 0
            total_closed_profit = self.fund_manager.history_manager.get_total_closed_profit()
            for row, fund in enumerate(funds):
                est = self.fetcher.get_fund_estimate(fund["code"])
                if not est:
                    name = fund.get("name", fund["code"])
                    dwjz = fund.get("dwjz", 0)
                    gsz = fund.get("gsz", dwjz)
                    growth = fund.get("growth", 0)
                else:
                    name = fund.get("name", est["name"])
                    dwjz = est["dwjz"]
                    gsz = est["gsz"]
                    growth = est["growth"]
                    fund["dwjz"] = dwjz
                    fund["gsz"] = gsz
                    fund["growth"] = growth
                code = fund["code"]
                cost = fund["cost"]
                shares = fund["shares"]
                today_profit = shares * (gsz - dwjz)
                total_profit = shares * (gsz - cost)
                self.table.setItem(row, 0, QTableWidgetItem(code))
                name_item = QTableWidgetItem(name)
                name_item.setToolTip(name)
                self.table.setItem(row, 1, name_item)
                self.table.setItem(row, 2, QTableWidgetItem(f"{cost:.4f}"))
                self.table.setItem(row, 3, QTableWidgetItem(f"{shares:.2f}"))
                self.table.setItem(row, 4, QTableWidgetItem(f"{gsz:.4f}"))
                growth_item = QTableWidgetItem(f"{growth:+.2f}%")
                if growth > 0:
                    growth_item.setForeground(QColor(220, 38, 38))
                elif growth < 0:
                    growth_item.setForeground(QColor(21, 128, 61))
                self.table.setItem(row, 5, growth_item)
                today_item = QTableWidgetItem(f"{today_profit:+.2f}")
                if today_profit > 0:
                    today_item.setForeground(QColor(220, 38, 38))
                elif today_profit < 0:
                    today_item.setForeground(QColor(21, 128, 61))
                self.table.setItem(row, 6, today_item)
                total_item = QTableWidgetItem(f"{total_profit:+.2f}")
                if total_profit > 0:
                    total_item.setForeground(QColor(220, 38, 38))
                elif total_profit < 0:
                    total_item.setForeground(QColor(21, 128, 61))
                self.table.setItem(row, 7, total_item)
                action_widget = QWidget()
                action_layout = QHBoxLayout(action_widget)
                action_layout.setContentsMargins(0, 0, 0, 0)
                action_layout.setSpacing(4)
                action_layout.setAlignment(Qt.AlignCenter)
                del_btn = QPushButton("DEL")
                del_btn.setFont(get_app_font(self.dynamic_font_size))
                del_btn.setToolTip("删除")
                del_btn.clicked.connect(lambda checked, c=code: self.remove_fund(c))
                history_btn = QPushButton("HIS")
                history_btn.setFont(get_app_font(self.dynamic_font_size))
                history_btn.setToolTip("查看历史")
                history_btn.clicked.connect(lambda checked, c=code, n=name: self.show_history(c, n))
                action_layout.addWidget(del_btn)
                action_layout.addWidget(history_btn)
                action_layout.addStretch(1)
                self.table.setCellWidget(row, 8, action_widget)
                total_yesterday_value += shares * dwjz
                total_today_profit += today_profit
                total_value += shares * gsz
                total_cost += shares * cost
            current_profit = total_value - total_cost
            total_profit = current_profit + total_closed_profit
            total_rate = (total_profit / (total_cost + 1e-6)) * 100
            today_rate = (total_today_profit / (total_yesterday_value + 1e-6)) * 100
            today_icon = get_weather_icon(today_rate)
            total_icon = get_weather_icon(total_rate)
            self.today_label.setText(f"{today_icon} 今日: {total_today_profit:+.2f}元 ({today_rate:+.2f}%)")
            self.total_label.setText(f"{total_icon} 当前: {current_profit:+.2f}元 ({(current_profit/(total_cost+1e-6))*100:+.2f}%)")
            self.history_label.setText(f"历史: {total_closed_profit:+.2f}元")
        except Exception as e:
            print(f"刷新数据失败: {str(e)}")

    def remove_fund(self, code):
        reply = QMessageBox.question(
            self, "确认删除",
            "确定要删除这只基金吗？\n注意：如果还有持仓，将记录为清仓并保留历史收益",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.fund_manager.remove_fund(code)
            self.refresh_data()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'container'):
            self.container.setGeometry(0, 0, self.width(), self.height())
        QTimer.singleShot(50, self.update_font_sizes)
        if hasattr(self, 'table') and self.table.columnCount() > 0:
            header = self.table.horizontalHeader()
            header.setSectionResizeMode(1, QHeaderView.Stretch)

    def closeEvent(self, event):
        if self.timer and self.timer.isActive():
            self.timer.stop()
        self.float_button.close()
        event.accept()

# ==================== 主应用 ====================
class FundApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.fund_manager = FundManager()
        self.fetcher = DataFetcher()
        self.simple_window = SimpleWindow(self.fund_manager, self.fetcher)
        self.full_window = None
        self.simple_window.switch_to_full.connect(self.switch_to_full_mode)
        self.simple_window.show()

    def switch_to_full_mode(self):
        if self.full_window is None:
            self.full_window = FullWindow(self.fund_manager, self.fetcher)
            self.full_window.switch_to_simple.connect(self.switch_to_simple_mode)
        pos = self.simple_window.pos()
        self.simple_window.hide()
        self.simple_window.float_button.hide()
        screen = QApplication.primaryScreen().geometry()
        x = max(0, min(pos.x(), screen.width() - self.full_window.width()))
        y = max(0, min(pos.y(), screen.height() - self.full_window.height()))
        self.full_window.move(x, y)
        self.full_window.show()
        self.full_window.activateWindow()
        self.full_window.raise_()

    def switch_to_simple_mode(self):
        pos = self.full_window.pos()
        self.full_window.hide()
        self.full_window.float_button.hide()
        screen = QApplication.primaryScreen().geometry()
        simple_width = min(self.simple_window.width(), SWITCH_THRESHOLD - 20)
        self.simple_window.resize(simple_width, self.simple_window.height())
        x = max(0, min(pos.x(), screen.width() - simple_width))
        y = max(0, min(pos.y(), screen.height() - self.simple_window.height()))
        self.simple_window.move(x, y)
        self.simple_window._switching = False
        self.simple_window.show()
        self.simple_window.activateWindow()
        self.simple_window.raise_()

# ==================== 程序入口 ====================
def main():
    app = FundApp(sys.argv)
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()