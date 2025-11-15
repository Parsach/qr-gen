import sys
import os
import json
import segno
import zipfile
import io
import tempfile
import shutil
from datetime import datetime
import gc
import platform
import re
import base64
from collections import Counter
import threading
import webbrowser
import time
from dataclasses import asdict

from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from PIL.ImageQt import ImageQt

from app_state import AssetPaths, TextSettings, GenerationOptions
from config_manager import AppPaths, ConfigManager, resolve_base_dir

# 尝试导入reportlab用于PDF生成
try:
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.platypus import SimpleDocTemplate, Image as RLImage, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    PDF_SUPPORT = True
except ImportError:
    PDF_SUPPORT = False

# 尝试导入colorthief用于颜色提取
try:
    from colorthief import ColorThief
    COLOR_THIEF_SUPPORT = True
except ImportError:
    COLOR_THIEF_SUPPORT = False

# 尝试导入cryptography用于加密
try:
    from cryptography.fernet import Fernet
    CRYPTO_SUPPORT = True
except ImportError:
    CRYPTO_SUPPORT = False


class ModernQRGenerator(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("QR Code Generator Pro")
        self.setGeometry(100, 100, 1400, 900)
        
        # 主题相关变量
        self.dark_theme = True
        self.auto_theme = False
        self.theme_presets = {
            "Blue Ocean": [(0, 119, 190), (0, 180, 216), (144, 224, 239)],
            "Cyber Night": [(25, 0, 51), (102, 0, 153), (153, 51, 255)],
            "Pastel Style": [(255, 179, 186), (255, 223, 186), (186, 255, 201)],
            "Sunset": [(255, 94, 77), (255, 154, 0), (237, 117, 57)],
            "Forest": [(34, 139, 34), (107, 142, 35), (124, 252, 0)]
        }
        self.current_theme_preset = "Custom"
        
        # 快速预览模式
        self.quick_preview_mode = True
        self.preview_quality = 0.7  # 快速预览的质量
        
        # 线程池
        self.thread_pool = QThreadPool.globalInstance()
        self.thread_pool.setMaxThreadCount(4)  # 最多4个线程
        
        # 变量
        self.assets = AssetPaths()
        self.generation_options = GenerationOptions()
        self.text_settings = TextSettings()
        self.selected_template = 1
        self.theme_colors = [(26, 35, 126), (74, 0, 224), (138, 43, 226)]
        self.custom_colors = [None, None, None]
        self.color_buttons = []
        self.use_custom_colors = False
        
        # 输出格式
        self.storage_paths = AppPaths()
        self.config_storage = ConfigManager(resolve_base_dir(), self.storage_paths)
        self.history = []
        self.custom_templates = []
        self.presets = []
        
        # 预览
        self.preview_img = None
        self.preview_pixmap = None
        self.preview_scale = 1.0
        self.preview_rotation = 0
        self.last_qr_preview_size = (0, 0)
        
        # 加载数据
        self.load_config()
        self.load_history()
        self.load_custom_templates()
        self.load_presets()
        
        # 设置UI
        self.setup_ui()
        
        # 初始预览
        QTimer.singleShot(500, self.update_preview)
        
        # 自动主题检查
        if self.auto_theme:
            self.check_auto_theme()
            # 每分钟检查一次
            self.theme_timer = QTimer(self)
            self.theme_timer.timeout.connect(self.check_auto_theme)
            self.theme_timer.start(60000)
    
    def setup_ui(self):
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # 左侧面板
        left_panel = self.create_left_panel()
        left_panel.setMaximumWidth(550)
        main_layout.addWidget(left_panel)
        
        # 右侧面板
        right_panel = self.create_right_panel()
        main_layout.addWidget(right_panel)
        
        # 创建菜单栏
        self.create_menu_bar()
        
        # 创建状态栏
        self.create_status_bar()
        
        # 设置拖放
        self.setAcceptDrops(True)
    
    def create_menu_bar(self):
        menubar = self.menuBar()
        
        # 文件菜单
        file_menu = menubar.addMenu("File")
        
        open_action = QAction("📁 Open Input File", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.browse_input_file)
        file_menu.addAction(open_action)
        
        file_menu.addSeparator()
        
        save_config_action = QAction("💾 Save Configuration", self)
        save_config_action.setShortcut("Ctrl+S")
        save_config_action.triggered.connect(self.save_config)
        file_menu.addAction(save_config_action)
        
        file_menu.addSeparator()
        
        exit_action = QAction("🚪 Exit", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        
        # 视图菜单
        view_menu = menubar.addMenu("View")
        
        theme_action = QAction("🌓 Toggle Theme", self)
        theme_action.setShortcut("Ctrl+T")
        theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(theme_action)
        
        auto_theme_action = QAction("🌗 Auto Theme", self)
        auto_theme_action.setCheckable(True)
        auto_theme_action.setChecked(self.auto_theme)
        auto_theme_action.triggered.connect(self.toggle_auto_theme)
        view_menu.addAction(auto_theme_action)
        
        quick_preview_action = QAction("⚡ Quick Preview", self)
        quick_preview_action.setCheckable(True)
        quick_preview_action.setChecked(self.quick_preview_mode)
        quick_preview_action.triggered.connect(self.toggle_quick_preview)
        view_menu.addAction(quick_preview_action)
        
        # 工具菜单
        tools_menu = menubar.addMenu("Tools")
        
        history_action = QAction("📋 History", self)
        history_action.triggered.connect(self.show_history)
        tools_menu.addAction(history_action)
        
        settings_action = QAction("⚙️ Settings", self)
        settings_action.triggered.connect(self.show_settings)
        tools_menu.addAction(settings_action)
        
        # 帮助菜单
        help_menu = menubar.addMenu("Help")
        
        about_action = QAction("ℹ️ About", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)
    
    def create_status_bar(self):
        self.statusBar = self.statusBar()
        self.statusBar.showMessage("🚀 Ready to generate QR codes!")
        
        # 添加永久部件显示模板信息
        self.template_label = QLabel()
        self.statusBar.addPermanentWidget(self.template_label)
        self.update_template_label()
        
        # 添加进度指示器
        self.progress_indicator = QLabel()
        self.statusBar.addPermanentWidget(self.progress_indicator)
    
    def create_left_panel(self):
        panel = QFrame()
        panel.setProperty("class", "card")
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        
        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(15)
        
        # 文件选择组
        file_group = QGroupBox("📁 File Selection")
        file_layout = QVBoxLayout(file_group)
        
        # 输入文件 - 支持拖放
        input_frame = QFrame()
        input_frame.setAcceptDrops(True)
        input_frame.setStyleSheet("QFrame { border: 2px dashed #555; border-radius: 6px; padding: 10px; }")
        input_layout = QVBoxLayout(input_frame)
        
        self.input_label = QLabel("Input File:")
        self.input_label.setProperty("class", "card-title")
        input_layout.addWidget(self.input_label)
        
        self.input_path = QLineEdit()
        self.input_path.setPlaceholderText("📄 Select input file or drag & drop...")
        input_layout.addWidget(self.input_path)
        
        self.browse_input_btn = QPushButton("Browse")
        self.browse_input_btn.setProperty("class", "primary")
        self.browse_input_btn.clicked.connect(self.browse_input_file)
        input_layout.addWidget(self.browse_input_btn)
        
        file_layout.addWidget(input_frame)
        
        # 输出目录
        output_layout = QHBoxLayout()
        self.output_label = QLabel("Output Directory:")
        self.output_label.setProperty("class", "card-title")
        output_layout.addWidget(self.output_label)
        
        self.output_path = QLineEdit()
        self.output_path.setText(self.output_dir)
        self.output_path.textChanged.connect(lambda: setattr(self, 'output_dir', self.output_path.text()))
        output_layout.addWidget(self.output_path)
        
        self.browse_output_btn = QPushButton("Browse")
        self.browse_output_btn.setProperty("class", "primary")
        self.browse_output_btn.clicked.connect(self.browse_output_dir)
        output_layout.addWidget(self.browse_output_btn)
        
        file_layout.addLayout(output_layout)
        
        # Logo文件 - 支持拖放
        logo_frame = QFrame()
        logo_frame.setAcceptDrops(True)
        logo_frame.setStyleSheet("QFrame { border: 2px dashed #555; border-radius: 6px; padding: 10px; }")
        logo_layout = QVBoxLayout(logo_frame)
        
        self.logo_label = QLabel("Logo (Optional):")
        self.logo_label.setProperty("class", "card-title")
        logo_layout.addWidget(self.logo_label)
        
        self.logo_path = QLineEdit()
        self.logo_path.setPlaceholderText("🖼️ Select logo file or drag & drop...")
        logo_layout.addWidget(self.logo_path)
        
        self.browse_logo_btn = QPushButton("Browse")
        self.browse_logo_btn.setProperty("class", "primary")
        self.browse_logo_btn.clicked.connect(self.browse_logo_file)
        logo_layout.addWidget(self.browse_logo_btn)
        
        file_layout.addWidget(logo_frame)
        scroll_layout.addWidget(file_group)
        
        # 模板选择组
        template_group = QGroupBox("🎨 Template Selection")
        template_layout = QVBoxLayout(template_group)
        
        self.template_combo = QComboBox()
        self.template_combo.setMinimumHeight(30)
        self.update_template_list()
        self.template_combo.currentTextChanged.connect(self.on_template_changed)
        template_layout.addWidget(self.template_combo)
        
        # 主题预设
        theme_preset_layout = QHBoxLayout()
        theme_preset_layout.addWidget(QLabel("Theme Preset:"))
        
        self.theme_preset_combo = QComboBox()
        self.theme_preset_combo.addItems(list(self.theme_presets.keys()) + ["Custom"])
        if self.current_theme_preset in self.theme_presets:
            self.theme_preset_combo.setCurrentText(self.current_theme_preset)
        else:
            self.theme_preset_combo.setCurrentText("Custom")
        self.theme_preset_combo.currentTextChanged.connect(self.on_theme_preset_changed)
        theme_preset_layout.addWidget(self.theme_preset_combo)
        
        template_layout.addLayout(theme_preset_layout)
        
        # 模板管理按钮
        template_btn_layout = QHBoxLayout()
        
        self.add_template_btn = QPushButton("➕ Add Template")
        self.add_template_btn.setProperty("class", "success")
        self.add_template_btn.clicked.connect(self.add_template_dialog)
        template_btn_layout.addWidget(self.add_template_btn)
        
        self.edit_template_btn = QPushButton("✏️ Edit Template")
        self.edit_template_btn.setProperty("class", "warning")
        self.edit_template_btn.clicked.connect(self.edit_template_dialog)
        template_btn_layout.addWidget(self.edit_template_btn)
        
        template_layout.addLayout(template_btn_layout)
        scroll_layout.addWidget(template_group)
        
        # 预设管理组
        preset_group = QGroupBox("💾 Presets")
        preset_layout = QVBoxLayout(preset_group)
        
        preset_btn_layout = QHBoxLayout()
        
        self.save_preset_btn = QPushButton("💾 Save Preset")
        self.save_preset_btn.setProperty("class", "success")
        self.save_preset_btn.clicked.connect(self.save_preset_dialog)
        preset_btn_layout.addWidget(self.save_preset_btn)
        
        self.load_preset_btn = QPushButton("📂 Load Preset")
        self.load_preset_btn.setProperty("class", "primary")
        self.load_preset_btn.clicked.connect(self.load_preset_dialog)
        preset_btn_layout.addWidget(self.load_preset_btn)
        
        preset_layout.addLayout(preset_btn_layout)
        scroll_layout.addWidget(preset_group)
        
        # 文本自定义组
        text_group = QGroupBox("✏️ Text Customization")
        text_layout = QFormLayout(text_group)
        
        self.title_edit = QLineEdit(self.title_text)
        self.title_edit.textChanged.connect(lambda: setattr(self, 'title_text', self.title_edit.text()) or self.update_preview())
        text_layout.addRow("Title Text:", self.title_edit)
        
        self.subtitle_edit = QLineEdit(self.subtitle_text)
        self.subtitle_edit.textChanged.connect(lambda: setattr(self, 'subtitle_text', self.subtitle_edit.text()) or self.update_preview())
        text_layout.addRow("Subtitle Text:", self.subtitle_edit)
        
        self.name_prefix_edit = QLineEdit(self.name_prefix)
        self.name_prefix_edit.textChanged.connect(lambda: setattr(self, 'name_prefix', self.name_prefix_edit.text()))
        text_layout.addRow("Name Prefix:", self.name_prefix_edit)
        
        # 字体大小
        self.title_font_spin = QSpinBox()
        self.title_font_spin.setRange(20, 50)
        self.title_font_spin.setValue(self.title_font_size)
        self.title_font_spin.valueChanged.connect(lambda v: setattr(self, 'title_font_size', v) or self.update_preview())
        text_layout.addRow("Title Font Size:", self.title_font_spin)
        
        self.subtitle_font_spin = QSpinBox()
        self.subtitle_font_spin.setRange(12, 30)
        self.subtitle_font_spin.setValue(self.subtitle_font_size)
        self.subtitle_font_spin.valueChanged.connect(lambda v: setattr(self, 'subtitle_font_size', v) or self.update_preview())
        text_layout.addRow("Subtitle Font Size:", self.subtitle_font_spin)
        
        self.name_font_spin = QSpinBox()
        self.name_font_spin.setRange(16, 40)
        self.name_font_spin.setValue(self.name_font_size)
        self.name_font_spin.valueChanged.connect(lambda v: setattr(self, 'name_font_size', v) or self.update_preview())
        text_layout.addRow("Name Font Size:", self.name_font_spin)
        
        # 文本颜色
        color_layout = QHBoxLayout()
        self.text_color_btn = QPushButton()
        self.text_color_btn.setStyleSheet(f"background-color: {self.text_color}; border: 2px solid #555; border-radius: 6px;")
        self.text_color_btn.setFixedSize(60, 30)
        self.text_color_btn.clicked.connect(self.choose_text_color)
        color_layout.addWidget(self.text_color_btn)
        
        color_layout.addWidget(QLabel("Text Color"))
        color_layout.addStretch()
        
        text_layout.addRow(color_layout)
        scroll_layout.addWidget(text_group)
        
        # 质量设置组
        quality_group = QGroupBox("⚙️ Quality Settings")
        quality_layout = QFormLayout(quality_group)
        
        self.qr_scale_slider = QSlider(Qt.Orientation.Horizontal)
        self.qr_scale_slider.setRange(10, 25)
        self.qr_scale_slider.setValue(self.qr_scale)
        self.qr_scale_slider.valueChanged.connect(lambda v: setattr(self, 'qr_scale', v) or self.update_preview())
        self.qr_scale_label = QLabel(str(self.qr_scale))
        self.qr_dimensions_label = QLabel("QR Pixels: --")
        self.qr_dimensions_label.setStyleSheet("color: #888; font-size: 11px;")
        
        scale_layout = QHBoxLayout()
        scale_layout.addWidget(self.qr_scale_slider)
        scale_layout.addWidget(self.qr_scale_label)
        quality_layout.addRow("QR Scale:", scale_layout)
        quality_layout.addRow("", self.qr_dimensions_label)
        
        self.dpi_spin = QSpinBox()
        self.dpi_spin.setRange(200, 600)
        self.dpi_spin.setSingleStep(50)
        self.dpi_spin.setValue(self.output_dpi)
        self.dpi_spin.valueChanged.connect(lambda v: setattr(self, 'output_dpi', v))
        quality_layout.addRow("Output DPI:", self.dpi_spin)
        
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(80, 100)
        self.quality_spin.setValue(self.output_quality)
        self.quality_spin.valueChanged.connect(lambda v: setattr(self, 'output_quality', v))
        quality_layout.addRow("JPEG Quality:", self.quality_spin)
        
        # 输出格式
        self.format_combo = QComboBox()
        self.format_combo.addItems(["PNG", "JPG", "WEBP"])
        if PDF_SUPPORT:
            self.format_combo.addItem("PDF")
        self.format_combo.currentTextChanged.connect(lambda t: setattr(self, 'output_format', t))
        quality_layout.addRow("Output Format:", self.format_combo)
        
        scroll_layout.addWidget(quality_group)
        
        # 输出选项组
        output_options_group = QGroupBox("📦 Output Options")
        output_options_layout = QVBoxLayout(output_options_group)
        
        self.create_zip_check = QCheckBox("Create ZIP Archive")
        self.create_zip_check.toggled.connect(lambda v: setattr(self, 'create_zip', v))
        output_options_layout.addWidget(self.create_zip_check)
        
        self.create_pdf_check = QCheckBox("Create PDF Document")
        self.create_pdf_check.setEnabled(PDF_SUPPORT)
        self.create_pdf_check.toggled.connect(lambda v: setattr(self, 'create_pdf', v))
        output_options_layout.addWidget(self.create_pdf_check)
        
        self.transparent_bg_check = QCheckBox("Transparent Background (PNG only)")
        self.transparent_bg_check.toggled.connect(self.update_preview)
        output_options_layout.addWidget(self.transparent_bg_check)
        
        scroll_layout.addWidget(output_options_group)
        
        # 颜色设置组
        color_group = QGroupBox("🎨 Color Settings")
        color_layout = QVBoxLayout(color_group)
        
        self.custom_colors_check = QCheckBox("Use Custom Colors")
        self.custom_colors_check.toggled.connect(self.toggle_custom_colors)
        color_layout.addWidget(self.custom_colors_check)
        
        # 颜色按钮
        self.color_buttons_layout = QHBoxLayout()
        self.color_buttons = []
        
        for i in range(3):
            btn = QPushButton(f"Color {i+1}")
            btn.setFixedSize(100, 50)
            color = self.custom_colors[i] if self.custom_colors[i] else self.theme_colors[i]
            btn.setStyleSheet(f"background-color: rgb{color}; border: 2px solid #555; border-radius: 6px; color: white;")
            btn.clicked.connect(lambda checked, idx=i: self.choose_color(idx))
            self.color_buttons.append(btn)
            self.color_buttons_layout.addWidget(btn)
        
        color_layout.addLayout(self.color_buttons_layout)
        self.custom_colors_check.setChecked(self.use_custom_colors)
        self.toggle_custom_colors(self.use_custom_colors)
        scroll_layout.addWidget(color_group)
        
        # 生成按钮
        self.generate_btn = QPushButton("🚀 Generate QR Codes")
        self.generate_btn.setProperty("class", "success")
        self.generate_btn.setFixedHeight(60)
        self.generate_btn.clicked.connect(self.start_generation)
        scroll_layout.addWidget(self.generate_btn)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setFixedHeight(25)
        scroll_layout.addWidget(self.progress_bar)
        
        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        
        # 连接拖放事件
        input_frame.dragEnterEvent = self.input_drag_enter_event
        input_frame.dropEvent = self.input_drop_event
        logo_frame.dragEnterEvent = self.logo_drag_enter_event
        logo_frame.dropEvent = self.logo_drop_event
        
        return panel
    
    def create_right_panel(self):
        panel = QFrame()
        panel.setProperty("class", "card")
        layout = QVBoxLayout(panel)
        layout.setSpacing(15)
        
        # 创建选项卡
        tabs = QTabWidget()
        
        # 预览选项卡
        preview_tab = QWidget()
        preview_layout = QVBoxLayout(preview_tab)
        
        # 预览组
        preview_group = QGroupBox("👁️ Live Preview")
        preview_group_layout = QVBoxLayout(preview_group)
        
        # 预览控制
        preview_controls_layout = QHBoxLayout()
        
        self.zoom_in_btn = QPushButton("🔍+")
        self.zoom_in_btn.setProperty("class", "primary")
        self.zoom_in_btn.clicked.connect(self.zoom_in)
        preview_controls_layout.addWidget(self.zoom_in_btn)
        
        self.zoom_out_btn = QPushButton("🔍-")
        self.zoom_out_btn.setProperty("class", "primary")
        self.zoom_out_btn.clicked.connect(self.zoom_out)
        preview_controls_layout.addWidget(self.zoom_out_btn)
        
        self.rotate_btn = QPushButton("🔄")
        self.rotate_btn.setProperty("class", "primary")
        self.rotate_btn.clicked.connect(self.rotate_preview)
        preview_controls_layout.addWidget(self.rotate_btn)
        
        self.reset_view_btn = QPushButton("🔄 Reset")
        self.reset_view_btn.setProperty("class", "warning")
        self.reset_view_btn.clicked.connect(self.reset_preview_view)
        preview_controls_layout.addWidget(self.reset_view_btn)
        
        preview_controls_layout.addStretch()
        preview_group_layout.addLayout(preview_controls_layout)
        
        # 预览画布
        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_label.setMinimumHeight(400)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #1e1e1e;
                border: 3px dashed #555;
                border-radius: 10px;
                color: #b0b0b0;
                font-size: 16px;
                font-weight: bold;
            }
        """)
        self.preview_label.setText("🔄 Preview will appear here...\n\nConfigure settings and see live preview!")
        
        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidget(self.preview_label)
        self.preview_scroll.setWidgetResizable(True)
        preview_group_layout.addWidget(self.preview_scroll)
        
        # 预览控制按钮
        controls_layout = QHBoxLayout()
        
        self.refresh_btn = QPushButton("🔄 Refresh")
        self.refresh_btn.setProperty("class", "primary")
        self.refresh_btn.clicked.connect(self.update_preview)
        controls_layout.addWidget(self.refresh_btn)
        
        self.save_preview_btn = QPushButton("💾 Save Preview")
        self.save_preview_btn.setProperty("class", "warning")
        self.save_preview_btn.clicked.connect(self.save_preview)
        controls_layout.addWidget(self.save_preview_btn)
        
        self.test_qr_btn = QPushButton("🔗 Test QR")
        self.test_qr_btn.setProperty("class", "primary")
        self.test_qr_btn.clicked.connect(self.test_qr)
        controls_layout.addWidget(self.test_qr_btn)
        
        self.open_output_btn = QPushButton("📂 Open Output")
        self.open_output_btn.setProperty("class", "primary")
        self.open_output_btn.clicked.connect(self.open_output_folder)
        controls_layout.addWidget(self.open_output_btn)
        
        controls_layout.addStretch()
        preview_group_layout.addLayout(controls_layout)
        preview_layout.addWidget(preview_group)
        tabs.addTab(preview_tab, "👁️ Preview")
        
        # 历史记录选项卡
        history_tab = QWidget()
        history_layout = QVBoxLayout(history_tab)
        
        # 搜索栏
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Search:"))
        self.history_search = QLineEdit()
        self.history_search.setPlaceholderText("Search history...")
        self.history_search.textChanged.connect(self.filter_history)
        search_layout.addWidget(self.history_search)
        
        self.clear_search_btn = QPushButton("Clear")
        self.clear_search_btn.clicked.connect(lambda: self.history_search.clear())
        search_layout.addWidget(self.clear_search_btn)
        
        history_layout.addLayout(search_layout)
        
        # 历史记录表格
        self.history_table = QTableWidget()
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels(["📅 Date", "🎨 Template", "📊 Count", "📁 Output Directory"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setAlternatingRowColors(True)
        self.history_table.itemDoubleClicked.connect(self.open_history_output)
        
        self.update_history_table()
        history_layout.addWidget(self.history_table)
        
        # 历史记录按钮
        history_btn_layout = QHBoxLayout()
        
        self.export_history_btn = QPushButton("📤 Export History")
        self.export_history_btn.setProperty("class", "primary")
        self.export_history_btn.clicked.connect(self.export_history)
        history_btn_layout.addWidget(self.export_history_btn)
        
        self.clear_history_btn = QPushButton("🗑️ Clear History")
        self.clear_history_btn.setProperty("class", "danger")
        self.clear_history_btn.clicked.connect(self.clear_history)
        history_btn_layout.addWidget(self.clear_history_btn)
        
        history_layout.addLayout(history_btn_layout)
        tabs.addTab(history_tab, "📋 History")
        
        layout.addWidget(tabs)
        return panel
    
    def apply_theme(self):
        if self.dark_theme:
            # 深色主题
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #2b2b2b;
                    color: #ffffff;
                }
                QWidget {
                    background-color: #2b2b2b;
                    color: #ffffff;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    font-size: 12px;
                }
                QLabel {
                    color: #ffffff;
                    background-color: transparent;
                    padding: 5px;
                }
                QLabel[class="title"] {
                    font-size: 16px;
                    font-weight: bold;
                    color: #4fc3f7;
                    padding: 10px;
                    background-color: #1e1e1e;
                    border-radius: 5px;
                }
                QLabel[class="card-title"] {
                    font-size: 14px;
                    font-weight: bold;
                    color: #81c784;
                    margin-bottom: 5px;
                }
                QLabel[class="subtitle"] {
                    font-size: 11px;
                    color: #b0b0b0;
                }
                QPushButton {
                    background-color: #4fc3f7;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 20px;
                    font-weight: bold;
                    font-size: 12px;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background-color: #29b6f6;                }
                QPushButton:pressed {
                    background-color: #0288d1;
                }
                QPushButton[class="success"] {
                    background-color: #66bb6a;
                }
                QPushButton[class="success"]:hover {
                    background-color: #4caf50;
                }
                QPushButton[class="warning"] {
                    background-color: #ffb74d;
                }
                QPushButton[class="warning"]:hover {
                    background-color: #ffa726;
                }
                QPushButton[class="danger"] {
                    background-color: #ef5350;
                }
                QPushButton[class="danger"]:hover {
                    background-color: #f44336;
                }
                QPushButton[class="primary"] {
                    background-color: #42a5f5;
                }
                QPushButton[class="primary"]:hover {
                    background-color: #2196f3;
                }
                QLineEdit {
                    background-color: #3c3c3c;
                    color: white;
                    border: 2px solid #555;
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 12px;
                }
                QLineEdit:focus {
                    border: 2px solid #4fc3f7;
                    background-color: #404040;
                }
                QTextEdit {
                    background-color: #3c3c3c;
                    color: white;
                    border: 2px solid #555;
                    border-radius: 6px;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                }
                QTextEdit:focus {
                    border: 2px solid #4fc3f7;
                }
                QSpinBox, QComboBox {
                    background-color: #3c3c3c;
                    color: white;
                    border: 2px solid #555;
                    border-radius: 6px;
                    padding: 5px;
                    min-height: 20px;
                }
                QSpinBox:focus, QComboBox:focus {
                    border: 2px solid #4fc3f7;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 30px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 5px solid #b0b0b0;
                }
                QComboBox QAbstractItemView {
                    background-color: #3c3c3c;
                    color: white;
                    selection-background-color: #4fc3f7;
                }
                QSlider::groove:horizontal {
                    border: 1px solid #555;
                    height: 8px;
                    background: #3c3c3c;
                    border-radius: 4px;
                }
                QSlider::handle:horizontal {
                    background: #4fc3f7;
                    border: 1px solid #29b6f6;
                    width: 18px;
                    margin: -5px 0;
                    border-radius: 9px;
                }
                QCheckBox {
                    spacing: 10px;
                    color: white;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border: 2px solid #555;
                    border-radius: 4px;
                    background-color: #3c3c3c;
                }
                QCheckBox::indicator:checked {
                    background-color: #4fc3f7;
                    border-color: #29b6f6;
                    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTAiIHZpZXdCb3g9IjAgMCAxMiAxMCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEgNEw0LjUgOC41TDExIDEiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
                }
                QProgressBar {
                    border: 2px solid #555;
                    border-radius: 6px;
                    text-align: center;
                    background-color: #3c3c3c;
                    color: white;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #4fc3f7;
                    border-radius: 4px;
                }
                QTabWidget::pane {
                    border: 2px solid #555;
                    background-color: #2b2b2b;
                    border-radius: 6px;
                }
                QTabBar::tab {
                    background-color: #3c3c3c;
                    padding: 10px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    color: #b0b0b0;
                }
                QTabBar::tab:selected {
                    background-color: #4fc3f7;
                    color: white;
                }
                QTabBar::tab:hover {
                    background-color: #404040;
                    color: white;
                }
                QScrollArea {
                    border: none;
                    background-color: transparent;
                }
                QFrame[frameShape="0"] {
                    border: none;
                    background-color: transparent;
                }
                QFrame[class="card"] {
                    background-color: #3c3c3c;
                    border: 2px solid #555;
                    border-radius: 10px;
                    margin: 5px;
                }
                QGroupBox {
                    background-color: #3c3c3c;
                    border: 2px solid #555;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    font-weight: bold;
                    color: #4fc3f7;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                QMenuBar {
                    background-color: #1e1e1e;
                    color: white;
                    border-bottom: 2px solid #555;
                }
                QMenuBar::item {
                    background-color: transparent;
                    padding: 8px 16px;
                }
                QMenuBar::item:selected {
                    background-color: #4fc3f7;
                }
                QMenu {
                    background-color: #3c3c3c;
                    color: white;
                    border: 2px solid #555;
                }
                QMenu::item:selected {
                    background-color: #4fc3f7;
                }
                QStatusBar {
                    background-color: #1e1e1e;
                    color: white;
                    border-top: 2px solid #555;
                }
                QTableWidget {
                    background-color: #3c3c3c;
                    color: white;
                    border: 2px solid #555;
                    gridline-color: #555;
                    selection-background-color: #4fc3f7;
                }
                QHeaderView::section {
                    background-color: #4fc3f7;
                    color: white;
                    padding: 8px;
                    border: 1px solid #555;
                }
            """)
        else:
            # 浅色主题
            self.setStyleSheet("""
                QMainWindow {
                    background-color: #f5f5f5;
                    color: #333333;
                }
                QWidget {
                    background-color: #f5f5f5;
                    color: #333333;
                    font-family: 'Segoe UI', Arial, sans-serif;
                    font-size: 12px;
                }
                QLabel {
                    color: #333333;
                    background-color: transparent;
                    padding: 5px;
                }
                QLabel[class="title"] {
                    font-size: 16px;
                    font-weight: bold;
                    color: #1976d2;
                    padding: 10px;
                    background-color: #ffffff;
                    border-radius: 5px;
                }
                QLabel[class="card-title"] {
                    font-size: 14px;
                    font-weight: bold;
                    color: #388e3c;
                    margin-bottom: 5px;
                }
                QLabel[class="subtitle"] {
                    font-size: 11px;
                    color: #757575;
                }
                QPushButton {
                    background-color: #2196f3;
                    color: white;
                    border: none;
                    border-radius: 6px;
                    padding: 10px 20px;
                    font-weight: bold;
                    font-size: 12px;
                    min-height: 20px;
                }
                QPushButton:hover {
                    background-color: #1e88e5;
                }
                QPushButton:pressed {
                    background-color: #1565c0;
                }
                QPushButton[class="success"] {
                    background-color: #4caf50;
                }
                QPushButton[class="success"]:hover {
                    background-color: #43a047;
                }
                QPushButton[class="warning"] {
                    background-color: #ff9800;
                }
                QPushButton[class="warning"]:hover {
                    background-color: #fb8c00;
                }
                QPushButton[class="danger"] {
                    background-color: #f44336;
                }
                QPushButton[class="danger"]:hover {
                    background-color: #e53935;
                }
                QPushButton[class="primary"] {
                    background-color: #2196f3;
                }
                QPushButton[class="primary"]:hover {
                    background-color: #1e88e5;
                }
                QLineEdit {
                    background-color: #ffffff;
                    color: #333333;
                    border: 2px solid #bdbdbd;
                    border-radius: 6px;
                    padding: 8px 12px;
                    font-size: 12px;
                }
                QLineEdit:focus {
                    border: 2px solid #2196f3;
                    background-color: #f5f5f5;
                }
                QTextEdit {
                    background-color: #ffffff;
                    color: #333333;
                    border: 2px solid #bdbdbd;
                    border-radius: 6px;
                    font-family: 'Consolas', 'Courier New', monospace;
                    font-size: 11px;
                }
                QTextEdit:focus {
                    border: 2px solid #2196f3;
                }
                QSpinBox, QComboBox {
                    background-color: #ffffff;
                    color: #333333;
                    border: 2px solid #bdbdbd;
                    border-radius: 6px;
                    padding: 5px;
                    min-height: 20px;
                }
                QSpinBox:focus, QComboBox:focus {
                    border: 2px solid #2196f3;
                }
                QComboBox::drop-down {
                    border: none;
                    width: 30px;
                }
                QComboBox::down-arrow {
                    image: none;
                    border-left: 5px solid transparent;
                    border-right: 5px solid transparent;
                    border-top: 5px solid #757575;
                }
                QComboBox QAbstractItemView {
                    background-color: #ffffff;
                    color: #333333;
                    selection-background-color: #2196f3;
                }
                QSlider::groove:horizontal {
                    border: 1px solid #bdbdbd;
                    height: 8px;
                    background: #e0e0e0;
                    border-radius: 4px;
                }
                QSlider::handle:horizontal {
                    background: #2196f3;
                    border: 1px solid #1976d2;
                    width: 18px;
                    margin: -5px 0;
                    border-radius: 9px;
                }
                QCheckBox {
                    spacing: 10px;
                    color: #333333;
                }
                QCheckBox::indicator {
                    width: 20px;
                    height: 20px;
                    border: 2px solid #bdbdbd;
                    border-radius: 4px;
                    background-color: #ffffff;
                }
                QCheckBox::indicator:checked {
                    background-color: #2196f3;
                    border-color: #1976d2;
                    image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTAiIHZpZXdCb3g9IjAgMCAxMiAxMCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHBhdGggZD0iTTEgNEw0LjUgOC41TDExIDEiIHN0cm9rZT0id2hpdGUiIHN0cm9rZS13aWR0aD0iMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBzdHJva2UtbGluZWpvaW49InJvdW5kIi8+Cjwvc3ZnPgo=);
                }
                QProgressBar {
                    border: 2px solid #bdbdbd;
                    border-radius: 6px;
                    text-align: center;
                    background-color: #e0e0e0;
                    color: #333333;
                    font-weight: bold;
                }
                QProgressBar::chunk {
                    background-color: #2196f3;
                    border-radius: 4px;
                }
                QTabWidget::pane {
                    border: 2px solid #bdbdbd;
                    background-color: #f5f5f5;
                    border-radius: 6px;
                }
                QTabBar::tab {
                    background-color: #e0e0e0;
                    padding: 10px 20px;
                    margin-right: 2px;
                    border-top-left-radius: 6px;
                    border-top-right-radius: 6px;
                    color: #757575;
                }
                QTabBar::tab:selected {
                    background-color: #2196f3;
                    color: white;
                }
                QTabBar::tab:hover {
                    background-color: #f5f5f5;
                    color: #333333;
                }
                QScrollArea {
                    border: none;
                    background-color: transparent;
                }
                QFrame[frameShape="0"] {
                    border: none;
                    background-color: transparent;
                }
                QFrame[class="card"] {
                    background-color: #ffffff;
                    border: 2px solid #e0e0e0;
                    border-radius: 10px;
                    margin: 5px;
                }
                QGroupBox {
                    background-color: #ffffff;
                    border: 2px solid #e0e0e0;
                    border-radius: 8px;
                    margin-top: 10px;
                    padding-top: 10px;
                    font-weight: bold;
                    color: #1976d2;
                }
                QGroupBox::title {
                    subcontrol-origin: margin;
                    left: 10px;
                    padding: 0 5px 0 5px;
                }
                QMenuBar {
                    background-color: #ffffff;
                    color: #333333;
                    border-bottom: 2px solid #e0e0e0;
                }
                QMenuBar::item {
                    background-color: transparent;
                    padding: 8px 16px;
                }
                QMenuBar::item:selected {
                    background-color: #2196f3;
                }
                QMenu {
                    background-color: #ffffff;
                    color: #333333;
                    border: 2px solid #e0e0e0;
                }
                QMenu::item:selected {
                    background-color: #2196f3;
                }
                QStatusBar {
                    background-color: #ffffff;
                    color: #333333;
                    border-top: 2px solid #e0e0e0;
                }
                QTableWidget {
                    background-color: #ffffff;
                    color: #333333;
                    border: 2px solid #e0e0e0;
                    gridline-color: #e0e0e0;
                    selection-background-color: #2196f3;
                }
                QHeaderView::section {
                    background-color: #2196f3;
                    color: white;
                    padding: 8px;
                    border: 1px solid #e0e0e0;
                }
            """)
    
    def toggle_theme(self):
        self.dark_theme = not self.dark_theme
        self.apply_theme()
        self.update_preview()
    
    def toggle_auto_theme(self, checked):
        self.auto_theme = checked
        if checked:
            self.check_auto_theme()
            # 每分钟检查一次
            if not hasattr(self, 'theme_timer'):
                self.theme_timer = QTimer(self)
                self.theme_timer.timeout.connect(self.check_auto_theme)
                self.theme_timer.start(60000)
        else:
            if hasattr(self, 'theme_timer'):
                self.theme_timer.stop()
    
    def check_auto_theme(self):
        if not self.auto_theme:
            return
        
        current_hour = datetime.now().hour
        # 6:00 - 18:00 为白天，其余为夜晚
        is_daytime = 6 <= current_hour < 18
        
        if is_daytime and self.dark_theme:
            self.dark_theme = False
            self.apply_theme()
            self.update_preview()
        elif not is_daytime and not self.dark_theme:
            self.dark_theme = True
            self.apply_theme()
            self.update_preview()
    
    def toggle_quick_preview(self, checked):
        self.quick_preview_mode = checked
        self.update_preview()
    
    def on_theme_preset_changed(self, preset_name):
        if preset_name in self.theme_presets:
            self.theme_colors = [tuple(color) for color in self.theme_presets[preset_name]]
            self.current_theme_preset = preset_name
            if hasattr(self, 'custom_colors_check') and self.use_custom_colors:
                self.use_custom_colors = False
                self.custom_colors_check.blockSignals(True)
                self.custom_colors_check.setChecked(False)
                self.custom_colors_check.blockSignals(False)
            self.update_color_buttons()
            self.update_preview()
        else:
            self.current_theme_preset = "Custom"
    
    def update_color_buttons(self):
        for i, btn in enumerate(self.color_buttons):
            color = self.custom_colors[i] if self.use_custom_colors and self.custom_colors[i] else self.theme_colors[i]
            btn.setStyleSheet(f"background-color: rgb{color}; border: 2px solid #555; border-radius: 6px; color: white;")
    
    def zoom_in(self):
        self.preview_scale *= 1.2
        self.update_preview_display()
    
    def zoom_out(self):
        self.preview_scale /= 1.2
        self.update_preview_display()
    
    def rotate_preview(self):
        self.preview_rotation = (self.preview_rotation + 90) % 360
        self.update_preview_display()
    
    def reset_preview_view(self):
        self.preview_scale = 1.0
        self.preview_rotation = 0
        self.update_preview_display()
    
    def update_preview_display(self):
        if not self.preview_pixmap:
            return
        
        # 应用缩放和旋转
        transform = QTransform()
        transform.rotate(self.preview_rotation)
        transformed_pixmap = self.preview_pixmap.transformed(transform, Qt.TransformationMode.SmoothTransformation)
        
        # 应用缩放
        scaled_pixmap = transformed_pixmap.scaled(
            int(transformed_pixmap.width() * self.preview_scale),
            int(transformed_pixmap.height() * self.preview_scale),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        )
        
        self.preview_label.setPixmap(scaled_pixmap)
    
    def input_drag_enter_event(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def input_drop_event(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            file_path = files[0]
            if os.path.isfile(file_path):
                self.input_file = file_path
                self.input_path.setText(file_path)
                self.update_preview()
    
    def logo_drag_enter_event(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
    
    def logo_drop_event(self, event):
        files = [u.toLocalFile() for u in event.mimeData().urls()]
        if files:
            file_path = files[0]
            if os.path.isfile(file_path) and file_path.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                self.logo_file = file_path
                self.logo_path.setText(file_path)
                self.extract_colors_from_logo(file_path)
                self.update_preview()
    
    def save_preset_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle("Save Preset")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        
        # 预设名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Preset Name:"))
        name_edit = QLineEdit()
        name_layout.addWidget(name_edit)
        layout.addLayout(name_layout)
        
        # 预设描述
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("Description:"))
        desc_edit = QLineEdit()
        desc_layout.addWidget(desc_edit)
        layout.addLayout(desc_layout)
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            name = name_edit.text().strip()
            desc = desc_edit.text().strip()
            
            if name:
                preset = {
                    "name": name,
                    "description": desc,
                    "selected_template": self.selected_template,
                    "qr_scale": self.qr_scale,
                    "output_dpi": self.output_dpi,
                    "output_quality": self.output_quality,
                    "theme_colors": self.theme_colors,
                    "custom_colors": self.custom_colors,
                    "use_custom_colors": self.use_custom_colors,
                    "title_text": self.title_text,
                    "subtitle_text": self.subtitle_text,
                    "name_prefix": self.name_prefix,
                    "title_font_size": self.title_font_size,
                    "subtitle_font_size": self.subtitle_font_size,
                    "name_font_size": self.name_font_size,
                    "text_color": self.text_color,
                    "output_format": self.output_format,
                    "create_zip": self.create_zip,
                    "create_pdf": self.create_pdf,
                    "transparent_bg": self.transparent_bg_check.isChecked()
                }
                
                self.presets.append(preset)
                self.save_presets()
                QMessageBox.information(self, "Success", "Preset saved successfully!")
    
    def load_preset_dialog(self):
        if not self.presets:
            QMessageBox.information(self, "Info", "No presets available")
            return
        
        dialog = QDialog(self)
        dialog.setWindowTitle("Load Preset")
        dialog.setModal(True)
        layout = QVBoxLayout(dialog)
        
        # 预设列表
        preset_list = QListWidget()
        for preset in self.presets:
            item = QListWidgetItem(f"{preset['name']} - {preset['description']}")
            preset_list.addItem(item)
        layout.addWidget(preset_list)
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected_items = preset_list.selectedItems()
            if selected_items:
                index = preset_list.row(selected_items[0])
                preset = self.presets[index]
                self.apply_preset(preset)
                QMessageBox.information(self, "Success", "Preset loaded successfully!")
    
    def apply_preset(self, preset):
        self.selected_template = preset.get("selected_template", 1)
        self.qr_scale = preset.get("qr_scale", 15)
        self.output_dpi = preset.get("output_dpi", 400)
        self.output_quality = preset.get("output_quality", 98)
        self.theme_colors = preset.get("theme_colors", [(26, 35, 126), (74, 0, 224), (138, 43, 226)])
        self.custom_colors = preset.get("custom_colors", [None, None, None])
        self.use_custom_colors = preset.get("use_custom_colors", False)
        self.title_text = preset.get("title_text", "VPN Configuration")
        self.subtitle_text = preset.get("subtitle_text", "Scan to Connect")
        self.name_prefix = preset.get("name_prefix", "VPN")
        self.title_font_size = preset.get("title_font_size", 32)
        self.subtitle_font_size = preset.get("subtitle_font_size", 18)
        self.name_font_size = preset.get("name_font_size", 24)
        self.text_color = preset.get("text_color", "#FFFFFF")
        self.output_format = preset.get("output_format", "PNG")
        self.create_zip = preset.get("create_zip", False)
        self.create_pdf = preset.get("create_pdf", False)
        
        # 更新UI
        self.template_combo.setCurrentIndex(self.template_combo.findData(self.selected_template))
        self.qr_scale_slider.setValue(self.qr_scale)
        self.dpi_spin.setValue(self.output_dpi)
        self.quality_spin.setValue(self.output_quality)
        self.title_edit.setText(self.title_text)
        self.subtitle_edit.setText(self.subtitle_text)
        self.name_prefix_edit.setText(self.name_prefix)
        self.title_font_spin.setValue(self.title_font_size)
        self.subtitle_font_spin.setValue(self.subtitle_font_size)
        self.name_font_spin.setValue(self.name_font_size)
        self.text_color_btn.setStyleSheet(f"background-color: {self.text_color}; border: 2px solid #555; border-radius: 6px;")
        self.format_combo.setCurrentText(self.output_format)
        self.create_zip_check.setChecked(self.create_zip)
        self.create_pdf_check.setChecked(self.create_pdf)
        self.transparent_bg_check.setChecked(preset.get("transparent_bg", False))
        if hasattr(self, 'custom_colors_check'):
            self.custom_colors_check.blockSignals(True)
            self.custom_colors_check.setChecked(self.use_custom_colors)
            self.custom_colors_check.blockSignals(False)
            self.toggle_custom_colors(self.use_custom_colors)
        
        self.update_color_buttons()
        self.update_preview()
    
    def save_presets(self):
        try:
            self.config_storage.save_presets(self.presets)
        except Exception as e:
            print(f"Failed to save presets: {e}")
    
    def load_presets(self):
        try:
            self.presets = self.config_storage.load_presets()
        except Exception as e:
            print(f"Failed to load presets: {e}")
            self.presets = []
    
    def test_qr(self):
        if not self.input_file:
            QMessageBox.warning(self, "Warning", "Please select input file")
            return
        
        try:
            with open(self.input_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        # 检测数据类型
                        if line.startswith("WIFI:"):
                            # WiFi配置
                            webbrowser.open(line)
                        elif line.startswith("TEL:"):
                            # 电话号码
                            webbrowser.open(line)
                        elif line.startswith("mailto:"):
                            # 邮件
                            webbrowser.open(line)
                        elif line.startswith("http"):
                            # 网址
                            webbrowser.open(line)
                        else:
                            # 其他类型，尝试作为网址打开
                            if not line.startswith(("http://", "https://")):
                                webbrowser.open(f"https://{line}")
                            else:
                                webbrowser.open(line)
                        break
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to test QR: {str(e)}")
    
    def filter_history(self, text):
        # 清空表格
        self.history_table.setRowCount(0)
        
        # 过滤历史记录
        filtered_history = []
        search_text = text.lower()
        
        for item in self.history:
            if (search_text in item["date"].lower() or 
                search_text in item["template"].lower() or 
                search_text in str(item["count"]).lower() or 
                search_text in item["output_dir"].lower()):
                filtered_history.append(item)
        
        # 填充表格
        self.history_table.setRowCount(len(filtered_history))
        for row, item in enumerate(filtered_history):
            self.history_table.setItem(row, 0, QTableWidgetItem(item["date"]))
            self.history_table.setItem(row, 1, QTableWidgetItem(item["template"]))
            self.history_table.setItem(row, 2, QTableWidgetItem(str(item["count"])))
            self.history_table.setItem(row, 3, QTableWidgetItem(item["output_dir"]))
    
    def update_history_table(self):
        self.history_table.setRowCount(len(self.history))
        for row, item in enumerate(self.history):
            self.history_table.setItem(row, 0, QTableWidgetItem(item["date"]))
            self.history_table.setItem(row, 1, QTableWidgetItem(item["template"]))
            self.history_table.setItem(row, 2, QTableWidgetItem(str(item["count"])))
            self.history_table.setItem(row, 3, QTableWidgetItem(item["output_dir"]))
    
    def open_history_output(self, item):
        row = item.row()
        output_dir = self.history_table.item(row, 3).text()
        if os.path.exists(output_dir):
            webbrowser.open(output_dir)
    
    def export_history(self):
        if not self.history:
            QMessageBox.information(self, "Info", "No history to export")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Export History", "", "JSON Files (*.json);;CSV Files (*.csv);;All Files (*)"
        )
        
        if file_path:
            try:
                if file_path.endswith('.csv'):
                    # 导出为CSV
                    import csv
                    with open(file_path, 'w', newline='') as csvfile:
                        fieldnames = ['date', 'template', 'count', 'output_dir']
                        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                        writer.writeheader()
                        for item in self.history:
                            writer.writerow(item)
                else:
                    # 导出为JSON
                    with open(file_path, 'w') as f:
                        json.dump(self.history, f, indent=4)
                
                QMessageBox.information(self, "Success", f"History exported to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export history: {str(e)}")
    
    def clear_history(self):
        reply = QMessageBox.question(self, 'Clear History', 
                                   'Are you sure you want to clear all history?',
                                   QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.history = []
            self.save_history()
            self.update_history_table()
    
    def update_template_list(self):
        self.template_combo.clear()
        
        # 内置模板
        templates = [
            ("🌊 Modern Gradient - Modern gradient design", 1),
            ("🔮 Glassmorphism - Glass morphism effect", 2),
            ("⚡ Neon Cyberpunk - Cyberpunk neon style", 3),
            ("✨ Minimalist - Clean minimal design", 4),
            ("💎 3D Luxury - 3D luxury card", 5),
            ("🌈 Aurora Glow - Floating halo aesthetic", 6),
            ("🧊 Split Contrast - Bold two-tone layout", 7),
            ("🌅 Sunrise Spotlight - Diagonal spotlight layout", 8)
        ]
        
        for name, template_id in templates:
            self.template_combo.addItem(name, template_id)
        
        # 添加自定义模板
        for template in self.custom_templates:
            self.template_combo.addItem(f"🎨 {template['name']} - {template['description']}", template['id'])
        
        # 选择当前模板
        for i in range(self.template_combo.count()):
            if self.template_combo.itemData(i) == self.selected_template:
                self.template_combo.setCurrentIndex(i)
                break
    
    def update_template_label(self):
        template_names = {
            1: "Modern Gradient",
            2: "Glassmorphism", 
            3: "Neon Cyberpunk",
            4: "Minimalist",
            5: "3D Luxury",
            6: "Aurora Glow",
            7: "Split Contrast",
            8: "Sunrise Spotlight"
        }
        
        template_name = template_names.get(self.selected_template, "Custom")
        self.template_label.setText(f"🎨 Template: {template_name}")
    
    def get_template_name(self):
        template_names = {
            1: "Modern Gradient",
            2: "Glassmorphism", 
            3: "Neon Cyberpunk",
            4: "Minimalist",
            5: "3D Luxury",
            6: "Aurora Glow",
            7: "Split Contrast",
            8: "Sunrise Spotlight"
        }
        
        # 检查是否是内置模板
        if self.selected_template in template_names:
            return template_names[self.selected_template]
        
        # 检查是否是自定义模板
        for template in self.custom_templates:
            if template['id'] == self.selected_template:
                return template['name']
        
        # 默认回退
        return "Custom"
    
    def on_template_changed(self):
        self.selected_template = self.template_combo.currentData()
        self.update_template_label()
        self.update_preview()
    
    def toggle_custom_colors(self, checked):
        self.use_custom_colors = checked
        
        for btn in self.color_buttons:
            btn.setEnabled(checked)
        
        if checked:
            self.current_theme_preset = "Custom"
            if hasattr(self, 'theme_preset_combo'):
                self.theme_preset_combo.blockSignals(True)
                self.theme_preset_combo.setCurrentText("Custom")
                self.theme_preset_combo.blockSignals(False)
            for i in range(3):
                if self.custom_colors[i] is None:
                    self.custom_colors[i] = self.theme_colors[i]
                color = self.custom_colors[i]
                self.color_buttons[i].setStyleSheet(f"background-color: rgb{color}; border: 2px solid #555; border-radius: 6px; color: white;")
        self.update_color_buttons()
        
        if hasattr(self, 'preview_label'):
            self.update_preview()

    def choose_color(self, index):
        color = QColorDialog.getColor()
        if color.isValid():
            rgb = (color.red(), color.green(), color.blue())
            self.custom_colors[index] = rgb
            self.current_theme_preset = "Custom"
            if hasattr(self, 'theme_preset_combo'):
                self.theme_preset_combo.blockSignals(True)
                self.theme_preset_combo.setCurrentText("Custom")
                self.theme_preset_combo.blockSignals(False)
            self.update_color_buttons()
            if hasattr(self, 'preview_label'):
                self.update_preview()
    
    def choose_text_color(self):
        color = QColorDialog.getColor(QColor(self.text_color))
        if color.isValid():
            self.text_color = color.name()
            self.text_color_btn.setStyleSheet(f"background-color: {self.text_color}; border: 2px solid #555; border-radius: 6px;")
            self.update_preview()
    
    def update_preview(self):
        try:
            self.statusBar.showMessage("🔄 Updating preview...")
            QApplication.processEvents()
            
            # 获取示例链接
            link = "https://example.com"
            if self.input_file and os.path.exists(self.input_file):
                with open(self.input_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            link = line
                            break
            
            # 检测数据类型
            qr_data = self.detect_data_type(link)
            
            # 创建QR码
            qr = segno.make(qr_data, error='h')
            
            # 使用唯一临时文件名
            temp_fd, temp_path = tempfile.mkstemp(suffix='.png')
            os.close(temp_fd)
            
            try:
                # 快速预览模式使用较小的比例，但仍保持与滑块成比例
                if self.quick_preview_mode:
                    scaled_value = int(max(5, round(self.qr_scale * self.preview_quality)))
                    scale = max(5, scaled_value)
                else:
                    scale = self.qr_scale
                
                qr.save(temp_path, scale=scale,
                        dark='#1a1a2e', light='#ffffff', border=1)
                
                qr_img = Image.open(temp_path)
                self.last_qr_preview_size = qr_img.size
                if hasattr(self, 'qr_dimensions_label'):
                    approx_cm = (qr_img.width / max(1, self.output_dpi)) * 2.54
                    self.qr_dimensions_label.setText(
                        f"QR Pixels: {qr_img.width} × {qr_img.height}  (~{approx_cm:.1f} cm)"
                    )
                
                # 获取颜色
                if self.use_custom_colors and all(self.custom_colors):
                    colors = self.custom_colors
                else:
                    colors = self.theme_colors
                
                # 获取模板函数
                template_func = self.get_template_function()
                
                # 应用模板
                final_img = template_func(
                    qr_img,
                    "Preview",
                    colors,
                    self.logo_file if self.logo_file else None,
                    {
                        'title': self.title_text,
                        'subtitle': self.subtitle_text,
                        'title_font_size': self.title_font_size,
                        'subtitle_font_size': self.subtitle_font_size,
                        'name_font_size': self.name_font_size,
                        'text_color': self.text_color
                    }
                )
                
                # 转换为QPixmap
                final_img.thumbnail((600, 600), Image.Resampling.LANCZOS if hasattr(Image, 'Resampling') else Image.ANTIALIAS)
                
                # 转换PIL到QPixmap
                img_data = final_img.convert('RGBA')
                qimg = QImage(img_data.tobytes(), img_data.width, img_data.height, QImage.Format.Format_RGBA8888)
                self.preview_pixmap = QPixmap.fromImage(qimg)
                
                # 更新预览
                self.update_preview_display()
                self.preview_img = final_img
                
                self.statusBar.showMessage("✅ Preview updated successfully!")
                
            finally:
                # 清理临时文件
                try:
                    if os.path.exists(temp_path):
                        os.unlink(temp_path)
                except:
                    pass
                
                # 强制垃圾回收
                gc.collect()
                
        except Exception as e:
            self.preview_label.setText(f"❌ Preview Error:\n{str(e)}")
            self.statusBar.showMessage(f"❌ Preview error: {str(e)}")
            print(f"Preview error: {e}")
    
    def detect_data_type(self, data):
        # 检测数据类型并返回适当的QR码数据
        if data.startswith("WIFI:"):
            # WiFi配置
            return data
        elif data.startswith("TEL:"):
            # 电话号码
            return data
        elif data.startswith("mailto:"):
            # 邮件
            return data
        elif data.startswith("http"):
            # 网址
            return data
        else:
            # 其他类型，尝试作为网址
            if not data.startswith(("http://", "https://")):
                return f"https://{data}"
            else:
                return data
    
    def get_template_function(self):
        if self.selected_template == 1:
            return self.template_modern_gradient
        elif self.selected_template == 2:
            return self.template_glassmorphism
        elif self.selected_template == 3:
            return self.template_neon_cyberpunk
        elif self.selected_template == 4:
            return self.template_minimalist
        elif self.selected_template == 5:
            return self.template_3d_card
        elif self.selected_template == 6:
            return self.template_aurora_glow
        elif self.selected_template == 7:
            return self.template_split_contrast
        elif self.selected_template == 8:
            return self.template_sunrise_spotlight
        
        # 自定义模板
        for template in self.custom_templates:
            if template['id'] == self.selected_template:
                try:
                    namespace = {}
                    exec(template['code'], namespace)
                    return namespace.get('template_custom', self.template_modern_gradient)
                except:
                    return self.template_modern_gradient
        
        return self.template_modern_gradient
    
    # 模板函数（与之前相同，但添加了text_settings参数）
    def template_modern_gradient(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        card_width = qr_width + 180
        card_height = qr_height + 300
        
        final_img = self.create_gradient(card_width, card_height, colors[0], colors[1], 'vertical')
        draw = ImageDraw.Draw(final_img)
        
        # 浅色圆圈
        overlay = Image.new('RGBA', (card_width, card_height), (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.ellipse([card_width - 200, -80, card_width + 80, 200], fill=(255, 255, 255, 25))
        final_img = Image.alpha_composite(final_img.convert('RGBA'), overlay).convert('RGB')
        draw = ImageDraw.Draw(final_img)
        
        # QR卡片带阴影
        qr_x, qr_y = (card_width - qr_width) // 2, 100
        qr_padding = 30
        
        draw.rounded_rectangle([qr_x - qr_padding + 12, qr_y - qr_padding + 12,
                               qr_x + qr_width + qr_padding + 12, qr_y + qr_height + qr_padding + 12],
                              radius=25, fill=(0, 0, 0, 80))
        draw.rounded_rectangle([qr_x - qr_padding, qr_y - qr_padding,
                               qr_x + qr_width + qr_padding, qr_y + qr_height + qr_padding],
                              radius=25, fill='white')
        
        final_img.paste(qr_img, (qr_x, qr_y))
        
        # Logo
        if logo_path and os.path.exists(logo_path):
            self.add_rounded_logo(final_img, logo_path,
                                 (qr_x + qr_width//2 - 70, qr_y + qr_height//2 - 70), 140)
        
        # 文本
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
            subtitle_font = ImageFont.truetype("arial.ttf", text_settings['subtitle_font_size'])
        except:
            title_font = name_font = subtitle_font = ImageFont.load_default()
        
        # 将十六进制颜色转换为RGB
        text_color_rgb = self.hex_to_rgb(text_settings['text_color'])
        
        # 标题
        title = text_settings['title']
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        draw.text(((card_width - title_w) // 2, 30), title, font=title_font, fill=text_color_rgb)
        
        # 名称
        name_y = qr_y + qr_height + qr_padding + 40
        name_bbox = draw.textbbox((0, 0), file_name, font=name_font)
        name_w = name_bbox[2] - name_bbox[0]
        draw.text(((card_width - name_w) // 2, name_y), file_name, font=name_font, fill=text_color_rgb)
        
        # 副标题
        subtitle = text_settings['subtitle']
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=subtitle_font)
        subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
        draw.text(((card_width - subtitle_w) // 2, name_y + 40), subtitle, font=subtitle_font, fill=text_color_rgb)
        
        return final_img
    
    def template_glassmorphism(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        card_width = qr_width + 160
        card_height = qr_height + 280
        
        final_img = self.create_gradient(card_width, card_height,
                                         tuple(max(0, c - 60) for c in colors[0]),
                                         tuple(max(0, c - 40) for c in colors[1]), 'vertical')
        
        qr_x, qr_y = (card_width - qr_width) // 2, 90
        
        draw = ImageDraw.Draw(final_img)
        draw.rounded_rectangle([qr_x - 15, qr_y - 15, qr_x + qr_width + 15, qr_y + qr_height + 15],
                              radius=20, fill='white')
        
        final_img.paste(qr_img, (qr_x, qr_y))
        
        if logo_path and os.path.exists(logo_path):
            self.add_rounded_logo(final_img, logo_path,
                                 (qr_x + qr_width//2 - 65, qr_y + qr_height//2 - 65), 130)
        
        # 文本
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
        except:
            title_font = name_font = ImageFont.load_default()
        
        text_color_rgb = self.hex_to_rgb(text_settings['text_color'])
        
        title = text_settings['title']
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        draw.text(((card_width - title_w) // 2, 30), title, font=title_font, fill=text_color_rgb)
        
        name_y = qr_y + qr_height + 35
        name_bbox = draw.textbbox((0, 0), file_name, font=name_font)
        name_w = name_bbox[2] - name_bbox[0]
        draw.text(((card_width - name_w) // 2, name_y), file_name, font=name_font, fill=text_color_rgb)
        
        return final_img
    
    def template_neon_cyberpunk(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        card_width = qr_width + 200
        card_height = qr_height + 320
        
        final_img = Image.new('RGB', (card_width, card_height), (10, 10, 25))
        draw = ImageDraw.Draw(final_img)
        
        neon_color = colors[1] if sum(colors[1]) > 200 else (0, 255, 200)
        for i in range(0, card_height, 30):
            draw.line([(0, i), (card_width, i)], fill=neon_color, width=2)
        
        qr_x, qr_y = (card_width - qr_width) // 2, 120
        
        for offset in [40, 30, 20]:
            draw.rounded_rectangle([qr_x - offset, qr_y - offset,
                                   qr_x + qr_width + offset, qr_y + qr_height + offset],
                                  radius=15, outline=neon_color, width=3)
        
        draw.rounded_rectangle([qr_x - 15, qr_y - 15, qr_x + qr_width + 15, qr_y + qr_height + 15],
                              radius=10, fill=(15, 15, 30))
        
        final_img.paste(qr_img, (qr_x, qr_y))
        
        if logo_path and os.path.exists(logo_path):
            self.add_rounded_logo(final_img, logo_path,
                                 (qr_x + qr_width//2 - 75, qr_y + qr_height//2 - 75), 150)
        
        # 文本
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
        except:
            title_font = name_font = ImageFont.load_default()
        
        title = text_settings['title']
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        draw.text(((card_width - title_w) // 2, 40), title, font=title_font, fill=neon_color)
        
        name_y = qr_y + qr_height + 60
        name_bbox = draw.textbbox((0, 0), file_name, font=name_font)
        name_w = name_bbox[2] - name_bbox[0]
        draw.rectangle([(card_width - name_w) // 2 - 20, name_y - 10,
                       (card_width + name_w) // 2 + 20, name_y + 35],
                      fill=(20, 20, 40), outline=neon_color, width=2)
        
        text_color_rgb = self.hex_to_rgb(text_settings['text_color'])
        draw.text(((card_width - name_w) // 2, name_y), file_name, font=name_font, fill=text_color_rgb)
        
        return final_img
    
    def template_minimalist(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        card_width = qr_width + 140
        card_height = qr_height + 260
        
        final_img = Image.new('RGB', (card_width, card_height), (250, 250, 252))
        draw = ImageDraw.Draw(final_img)
        
        accent_color = colors[0]
        for i, width in enumerate([8, 5, 3]):
            draw.line([(40, 30 + i * 12), (card_width - 40, 30 + i * 12)],
                     fill=accent_color, width=width)
        
        qr_x, qr_y = (card_width - qr_width) // 2, 100
        
        shadow = Image.new('RGBA', (card_width, card_height), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle([qr_x - 25, qr_y - 25, qr_x + qr_width + 25, qr_y + qr_height + 25],
                                      radius=20, fill=(0, 0, 0, 40))
        shadow = shadow.filter(ImageFilter.GaussianBlur(15))
        final_img.paste(shadow, (0, 5), shadow)
        
        draw.rounded_rectangle([qr_x - 20, qr_y - 20, qr_x + qr_width + 20, qr_y + qr_height + 20],
                              radius=15, fill='white', outline=(220, 220, 220), width=2)
        
        final_img.paste(qr_img, (qr_x, qr_y))
        
        if logo_path and os.path.exists(logo_path):
            logo_size = 120
            logo_pos = (qr_x + qr_width//2 - logo_size//2, qr_y + qr_height//2 - logo_size//2)
            self.add_rounded_logo(final_img, logo_path, logo_pos, logo_size)
        
        # 文本
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
        except:
            title_font = name_font = ImageFont.load_default()
        
        text_color_rgb = self.hex_to_rgb(text_settings['text_color'])
        
        name_y = qr_y + qr_height + 40
        name_bbox = draw.textbbox((0, 0), file_name, font=name_font)
        name_w = name_bbox[2] - name_bbox[0]
        draw.text(((card_width - name_w) // 2, name_y), file_name, font=name_font, fill=text_color_rgb)
        
        line_y = name_y + 40
        draw.line([(card_width // 2 - 50, line_y), (card_width // 2 + 50, line_y)],
                 fill=accent_color, width=3)
        
        subtitle = text_settings['subtitle']
        subtitle_bbox = draw.textbbox((0, 0), subtitle, font=title_font)
        subtitle_w = subtitle_bbox[2] - subtitle_bbox[0]
        draw.text(((card_width - subtitle_w) // 2, line_y + 15), subtitle,
                 font=title_font, fill=text_color_rgb)
        
        return final_img
    
    def template_3d_card(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        card_width = qr_width + 200
        card_height = qr_height + 340
        
        final_img = Image.new('RGB', (card_width, card_height), colors[0])
        for y in range(card_height):
            for x in range(card_width):
                ratio = (x + y) / (card_width + card_height)
                r = int(colors[0][0] * (1 - ratio) + colors[1][0] * ratio)
                g = int(colors[0][1] * (1 - ratio) + colors[1][1] * ratio)
                b = int(colors[0][2] * (1 - ratio) + colors[1][2] * ratio)
                final_img.putpixel((x, y), (r, g, b))
        
        draw = ImageDraw.Draw(final_img)
        qr_x, qr_y = (card_width - qr_width) // 2, 120
        
        for i in range(5, 0, -1):
            offset = i * 8
            darkness = 255 - i * 30
            draw.rounded_rectangle([qr_x - 40 + offset, qr_y - 40 + offset,
                                   qr_x + qr_width + 40 + offset, qr_y + qr_height + 40 + offset],
                                  radius=25, fill=(darkness // 3, darkness // 3, darkness // 2))
        
        draw.rounded_rectangle([qr_x - 40, qr_y - 40, qr_x + qr_width + 40, qr_y + qr_height + 40],
                              radius=25, fill='white')
        
        for width in [4, 2, 1]:
            color_intensity = 255 - width * 30
            draw.rounded_rectangle([qr_x - 40, qr_y - 40, qr_x + qr_width + 40, qr_y + qr_height + 40],
                                  radius=25, outline=(color_intensity, color_intensity // 2, 50), width=width)
        
        final_img.paste(qr_img, (qr_x, qr_y))
        
        if logo_path and os.path.exists(logo_path):
            logo_size = 140
            logo_pos = (qr_x + qr_width//2 - logo_size//2, qr_y + qr_height//2 - logo_size//2)
            
            ring = Image.new('RGBA', (logo_size + 60, logo_size + 60), (0, 0, 0, 0))
            ring_draw = ImageDraw.Draw(ring)
            for r in range(3):
                ring_draw.ellipse([r * 10, r * 10, logo_size + 60 - r * 10, logo_size + 60 - r * 10],
                                 outline=(220 - r * 20, 180 - r * 20, 50, 200), width=3)
            
            final_img.paste(ring, (logo_pos[0] - 30, logo_pos[1] - 30), ring)
            
            circle_bg = Image.new('RGBA', (logo_size + 20, logo_size + 20), (0, 0, 0, 0))
            circle_draw = ImageDraw.Draw(circle_bg)
            circle_draw.ellipse([0, 0, logo_size + 20, logo_size + 20], fill='white')
            final_img.paste(circle_bg, (logo_pos[0] - 10, logo_pos[1] - 10), circle_bg)
            
            self.add_rounded_logo(final_img, logo_path, logo_pos, logo_size)
        
        # 文本
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
        except:
            title_font = name_font = ImageFont.load_default()
        
        title = text_settings['title']
        title_bbox = draw.textbbox((0, 0), title, font=title_font)
        title_w = title_bbox[2] - title_bbox[0]
        
        for offset in [(3, 3), (2, 2), (1, 1), (0, 0)]:
            if offset == (0, 0):
                color = (220, 180, 50)
            else:
                color = (100, 80, 20)
            draw.text(((card_width - title_w) // 2 + offset[0], 45 + offset[1]),
                     title, font=title_font, fill=color)
        
        name_y = qr_y + qr_height + 70
        name_bbox = draw.textbbox((0, 0), file_name, font=name_font)
        name_w = name_bbox[2] - name_bbox[0]
        
        draw.rounded_rectangle([(card_width - name_w) // 2 - 25, name_y - 12,
                               (card_width + name_w) // 2 + 25, name_y + 38],
                              radius=10, fill='white', outline=(220, 180, 50), width=2)
        
        text_color_rgb = self.hex_to_rgb(text_settings['text_color'])
        draw.text(((card_width - name_w) // 2, name_y), file_name,
                 font=name_font, fill=text_color_rgb)
        
        return final_img
    
    def template_aurora_glow(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        card_width = qr_width + 260
        card_height = qr_height + 360
        
        base = Image.new('RGB', (card_width, card_height), (8, 10, 28))
        glow_layer = Image.new('RGBA', (card_width, card_height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_layer)
        
        for idx, color in enumerate((colors[2], colors[1], colors[0])):
            alpha = max(30, 150 - idx * 40)
            padding = idx * 40
            glow_draw.ellipse(
                [padding, 80 + padding, card_width - padding, card_height - 140 - padding],
                fill=(*color, alpha)
            )
        glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=55))
        base = Image.alpha_composite(base.convert('RGBA'), glow_layer).convert('RGB')
        
        qr_box_width = qr_width + 100
        qr_box_height = qr_height + 100
        qr_box_x = (card_width - qr_box_width) // 2
        qr_box_y = 120
        
        card_overlay = Image.new('RGBA', (qr_box_width, qr_box_height), (18, 18, 40, 235))
        highlight = Image.new('RGBA', (qr_box_width, qr_box_height), (255, 255, 255, 18))
        highlight = highlight.filter(ImageFilter.GaussianBlur(6))
        card_overlay = Image.alpha_composite(card_overlay, highlight)
        shadow = Image.new('RGBA', (qr_box_width + 50, qr_box_height + 50), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle(
            [0, 0, qr_box_width + 50, qr_box_height + 50],
            radius=45,
            fill=(0, 0, 0, 120)
        )
        shadow = shadow.filter(ImageFilter.GaussianBlur(18))
        base.paste(shadow, (qr_box_x - 25, qr_box_y - 25), shadow)
        
        base.paste(card_overlay, (qr_box_x, qr_box_y), card_overlay)
        base.paste(qr_img, (qr_box_x + 50, qr_box_y + 50))
        
        if logo_path and os.path.exists(logo_path):
            self.add_rounded_logo(base, logo_path,
                                  (qr_box_x + qr_box_width//2 - 70, qr_box_y + qr_box_height//2 - 70), 140)
        
        draw = ImageDraw.Draw(base)
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            subtitle_font = ImageFont.truetype("arial.ttf", text_settings['subtitle_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
        except:
            title_font = subtitle_font = name_font = ImageFont.load_default()
        
        text_color = self.hex_to_rgb(text_settings['text_color'])
        draw.text((60, 40), text_settings['title'], font=title_font, fill=text_color)
        draw.text((60, card_height - 140), text_settings['subtitle'], font=subtitle_font, fill=text_color)
        draw.text((60, card_height - 90), file_name, font=name_font, fill=text_color)
        
        return base
    
    def template_split_contrast(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        accent_width = max(200, qr_width // 2)
        card_width = qr_width + accent_width + 220
        card_height = qr_height + 240
        
        base = Image.new('RGB', (card_width, card_height), tuple(min(255, c + 35) for c in colors[2]))
        draw = ImageDraw.Draw(base)
        draw.rectangle([0, 0, accent_width, card_height], fill=colors[0])
        
        qr_x = accent_width + (card_width - accent_width - qr_width) // 2
        qr_y = 100
        shadow = Image.new('RGBA', (qr_width + 60, qr_height + 60), (0, 0, 0, 0))
        shadow_draw = ImageDraw.Draw(shadow)
        shadow_draw.rounded_rectangle([0, 0, qr_width + 60, qr_height + 60], radius=30, fill=(0, 0, 0, 90))
        shadow = shadow.filter(ImageFilter.GaussianBlur(10))
        base.paste(shadow, (qr_x - 30, qr_y - 30), shadow)
        base.paste(qr_img, (qr_x, qr_y))
        
        if logo_path and os.path.exists(logo_path):
            self.add_rounded_logo(base, logo_path,
                                  (qr_x + qr_width//2 - 60, qr_y + qr_height//2 - 60), 120)
        
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            subtitle_font = ImageFont.truetype("arial.ttf", text_settings['subtitle_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
        except:
            title_font = subtitle_font = name_font = ImageFont.load_default()
        
        text_color = self.hex_to_rgb(text_settings['text_color'])
        draw.text((30, 70), text_settings['title'], font=title_font, fill=text_color)
        draw.text((30, 130), text_settings['subtitle'], font=subtitle_font, fill=text_color)
        draw.text((30, card_height - 90), file_name, font=name_font, fill=text_color)
        
        draw.line([(accent_width - 8, 60), (accent_width - 8, card_height - 60)], fill=colors[1], width=4)
        draw.line([(30, card_height - 105), (accent_width - 30, card_height - 105)], fill=colors[1], width=3)
        
        return base
    
    def template_sunrise_spotlight(self, qr_img, file_name, colors, logo_path, text_settings):
        qr_width, qr_height = qr_img.size
        card_width = qr_width + 160
        card_height = qr_height + 220
        
        base = self.create_gradient(card_width, card_height, colors[0], colors[1], 'vertical')
        draw = ImageDraw.Draw(base)
        
        qr_x = (card_width - qr_width) // 2
        qr_y = 90
        base.paste(qr_img, (qr_x, qr_y))
        
        if logo_path and os.path.exists(logo_path):
            self.add_rounded_logo(base, logo_path,
                                  (qr_x + qr_width//2 - 60, qr_y + qr_height//2 - 60), 120)
        
        try:
            title_font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
            subtitle_font = ImageFont.truetype("arial.ttf", text_settings['subtitle_font_size'])
            name_font = ImageFont.truetype("arial.ttf", text_settings['name_font_size'])
        except:
            title_font = subtitle_font = name_font = ImageFont.load_default()
        
        text_color = self.hex_to_rgb(text_settings['text_color'])
        title_bbox = draw.textbbox((0, 0), text_settings['title'], font=title_font)
        title_width = title_bbox[2] - title_bbox[0]
        title_x = max(20, (card_width - title_width) // 2)
        draw.text((title_x, 20), text_settings['title'], font=title_font, fill=text_color)
        
        subtitle_bbox = draw.textbbox((0, 0), text_settings['subtitle'], font=subtitle_font)
        subtitle_width = subtitle_bbox[2] - subtitle_bbox[0]
        subtitle_x = max(20, (card_width - subtitle_width) // 2)
        draw.text((subtitle_x, 20 + (title_bbox[3] - title_bbox[1]) + 5),
                  text_settings['subtitle'], font=subtitle_font, fill=text_color)
        
        name_bbox = draw.textbbox((0, 0), file_name, font=name_font)
        name_width = name_bbox[2] - name_bbox[0]
        name_x = max(20, (card_width - name_width) // 2)
        draw.text((name_x, qr_y + qr_height + 30), file_name, font=name_font, fill=text_color)
        
        return base
    
    # 辅助函数
    def create_gradient(self, width, height, color1, color2, direction='vertical'):
        base = Image.new('RGB', (width, height))
        draw = ImageDraw.Draw(base)
        
        for i in range(height if direction == 'vertical' else width):
            ratio = i / (height if direction == 'vertical' else width)
            r = int(color1[0] * (1 - ratio) + color2[0] * ratio)
            g = int(color1[1] * (1 - ratio) + color2[1] * ratio)
            b = int(color1[2] * (1 - ratio) + color2[2] * ratio)
            
            if direction == 'vertical':
                draw.line([(0, i), (width, i)], fill=(r, g, b))
            else:
                draw.line([(i, 0), (i, height)], fill=(r, g, b))
        
        return base
    
    def add_rounded_logo(self, base_img, logo_path, position, size):
        try:
            logo = Image.open(logo_path).convert('RGBA')
            try:
                logo.thumbnail((size, size), Image.Resampling.LANCZOS)
            except AttributeError:
                logo.thumbnail((size, size), Image.ANTIALIAS)
            
            mask = Image.new('L', (size, size), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, size, size], fill=255)
            
            logo_square = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            offset = ((size - logo.size[0]) // 2, (size - logo.size[1]) // 2)
            logo_square.paste(logo, offset, logo)
            
            logo_circle = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            logo_circle.paste(logo_square, (0, 0))
            logo_circle.putalpha(mask)
            
            base_img.paste(logo_circle, position, logo_circle)
        except:
            pass
    
    def hex_to_rgb(self, hex_color):
        hex_color = hex_color.lstrip('#')
        return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
    
    def normalize_palette(self, palette, allow_none=False):
        if not palette:
            return [None, None, None] if allow_none else [(26, 35, 126), (74, 0, 224), (138, 43, 226)]
        
        normalized = []
        for color in palette:
            if color is None:
                normalized.append(None if allow_none else (26, 35, 126))
                continue
            if isinstance(color, (list, tuple)):
                normalized.append(tuple(int(c) for c in color[:3]))
            else:
                normalized.append(color)
        return normalized
    
    # 文件操作
    def browse_input_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Input File", "", "Text Files (*.txt);;All Files (*)"
        )
        if file_path:
            self.input_file = file_path
            self.input_path.setText(file_path)
            self.update_preview()
    
    def browse_output_dir(self):
        dir_path = QFileDialog.getExistingDirectory(self, "Select Output Directory")
        if dir_path:
            self.output_dir = dir_path
            self.output_path.setText(dir_path)
    
    def browse_logo_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Logo File", "", 
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif);;All Files (*)"
        )
        if file_path:
            self.logo_file = file_path
            self.logo_path.setText(file_path)
            self.extract_colors_from_logo(file_path)
            self.update_preview()
    
    def extract_colors_from_logo(self, logo_path, num_colors=3):
        try:
            if COLOR_THIEF_SUPPORT:
                # 使用colorthief提取颜色
                color_thief = ColorThief(logo_path)
                palette = color_thief.get_palette(color_count=num_colors)
                return palette
            else:
                # 回退到原始方法
                img = Image.open(logo_path).convert('RGB').resize((150, 150))
                pixels = [p for p in img.getdata() if not (
                    (p[0] > 240 and p[1] > 240 and p[2] > 240) or
                    (p[0] < 20 and p[1] < 20 and p[2] < 20)
                )]
                
                color_counts = Counter(pixels or list(img.getdata()))
                selected = []
                for color, _ in color_counts.most_common(num_colors * 5):
                    if not selected or all(sum(abs(color[i] - c[i]) for i in range(3)) > 80 for c in selected):
                        selected.append(color)
                        if len(selected) >= num_colors:
                            break
                
                while len(selected) < num_colors:
                    selected.append(tuple(max(0, c - 40) for c in selected[0]))
                
                return selected[:num_colors]
        except:
            return [(26, 35, 126), (74, 0, 224), (138, 43, 226)]
    
    # 生成
    def start_generation(self):
        if not self.input_file:
            QMessageBox.warning(self, "Warning", "Please select input file")
            return
        
        if not os.path.exists(self.input_file):
            QMessageBox.warning(self, "Warning", "Input file does not exist")
            return
        
        self.generate_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.statusBar.showMessage("🚀 Generating QR codes...")
        
        # 运行在线程池中
        self.worker = QRWorker(self)
        self.worker.signals.progress.connect(self.update_progress)
        self.worker.signals.finished.connect(self.generation_finished)
        self.thread_pool.start(self.worker)
    
    def update_progress(self, value):
        self.progress_bar.setValue(value)
        self.statusBar.showMessage(f"🔄 Generating... {value}%")
        self.progress_indicator.setText(f"🔄 {value}%")
    
    def generation_finished(self, success, message):
        self.generate_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self.progress_indicator.setText("")
        
        if success:
            self.statusBar.showMessage("✅ Generation completed successfully!")
            QMessageBox.information(self, "Success", message)
            
            # 自动打开输出文件夹
            if hasattr(self, 'auto_open_check') and self.auto_open_check.isChecked():
                self.open_output_folder()
        else:
            self.statusBar.showMessage("❌ Generation failed!")
            QMessageBox.critical(self, "Error", message)
    
    # 预览操作
    def save_preview(self):
        if not self.preview_img:
            QMessageBox.warning(self, "Warning", "No preview to save")
            return
        
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Save Preview", "", "PNG Files (*.png);;All Files (*)"
        )
        
        if file_path:
            try:
                self.preview_img.save(file_path, quality=self.output_quality,
                                     dpi=(self.output_dpi, self.output_dpi))
                QMessageBox.information(self, "Success", f"Preview saved to {file_path}")
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to save preview: {str(e)}")
    
    def open_output_folder(self):
        if os.path.exists(self.output_dir):
            if platform.system() == "Windows":
                os.startfile(self.output_dir)
            elif platform.system() == "Darwin":  # macOS
                os.system(f"open {self.output_dir}")
            else:  # Linux
                os.system(f"xdg-open {self.output_dir}")
        else:
            QMessageBox.warning(self, "Warning", "Output directory does not exist")
    
    # 模板管理
    def add_template_dialog(self):
        dialog = TemplateDialog(self, "Add Custom Template")
        if dialog.exec() == QDialog.DialogCode.Accepted:
            template = dialog.get_template()
            template_id = max([t['id'] for t in self.custom_templates], default=8) + 1
            template['id'] = template_id
            self.custom_templates.append(template)
            self.save_custom_templates()
            self.update_template_list()
            QMessageBox.information(self, "Success", "Template added successfully!")
    
    def edit_template_dialog(self):
        if self.selected_template <= 5:
            QMessageBox.information(self, "Info", "Built-in templates cannot be edited")
            return
        
        template = None
        for t in self.custom_templates:
            if t['id'] == self.selected_template:
                template = t
                break
        
        if not template:
            QMessageBox.warning(self, "Warning", "Template not found")
            return
        
        dialog = TemplateDialog(self, "Edit Template", template)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            updated_template = dialog.get_template()
            template.update(updated_template)
            self.save_custom_templates()
            self.update_template_list()
            QMessageBox.information(self, "Success", "Template updated successfully!")
    
    # 对话框
    def show_history(self):
        # 切换到历史记录选项卡
        self.right_panel().setCurrentIndex(1)
    
    def show_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()
    
    def show_about(self):
        QMessageBox.about(self, "About QR Code Generator Pro", 
                         "🎨 QR Code Generator Pro\nVersion 2.0\n\n"
                         "A professional QR code generator with custom templates\n\n"
                         "Features:\n"
                         "• 🌊 Multiple built-in templates\n"
                         "• 🎨 Custom template support\n"
                         "• ✏️ Full text customization\n"
                         "• 👁️ Live preview\n"
                         "• 📋 History tracking\n"
                         "• 🌙 Dark/Light theme\n"
                         "• 🚀 High performance\n\n"
                         "Built with PyQt6")
    
    # 配置操作
    def save_config(self):
        config = {
            "assets": asdict(self.assets),
            "text": asdict(self.text_settings),
            "generation": asdict(self.generation_options),
            "selected_template": self.selected_template,
            "theme_colors": self.theme_colors,
            "custom_colors": self.custom_colors,
            "use_custom_colors": self.use_custom_colors,
            "dark_theme": self.dark_theme,
            "auto_theme": self.auto_theme,
            "quick_preview_mode": self.quick_preview_mode,
            "preview_quality": self.preview_quality,
            "current_theme_preset": self.current_theme_preset
        }
        
        try:
            self.config_storage.save_config(config)
            QMessageBox.information(self, "Success", "✅ Configuration saved successfully!")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save configuration: {str(e)}")
    
    def load_config(self):
        try:
            config = self.config_storage.load_config()
            if config:
                self.apply_config_payload(config)
        except Exception as e:
            print(f"Failed to load configuration: {e}")
    
    def apply_config_payload(self, config):
        assets = config.get("assets")
        if assets:
            self.assets.input_file = assets.get("input_file", self.assets.input_file)
            self.assets.output_dir = assets.get("output_dir", self.assets.output_dir)
            self.assets.logo_file = assets.get("logo_file", self.assets.logo_file)
        else:
            self.assets.input_file = config.get("input_file", self.assets.input_file)
            self.assets.output_dir = config.get("output_dir", self.assets.output_dir)
            self.assets.logo_file = config.get("logo_file", self.assets.logo_file)
        
        text = config.get("text")
        if text:
            self.text_settings.title = text.get("title", self.text_settings.title)
            self.text_settings.subtitle = text.get("subtitle", self.text_settings.subtitle)
            self.text_settings.name_prefix = text.get("name_prefix", self.text_settings.name_prefix)
            self.text_settings.title_font_size = text.get("title_font_size", self.text_settings.title_font_size)
            self.text_settings.subtitle_font_size = text.get("subtitle_font_size", self.text_settings.subtitle_font_size)
            self.text_settings.name_font_size = text.get("name_font_size", self.text_settings.name_font_size)
            self.text_settings.text_color = text.get("text_color", self.text_settings.text_color)
        else:
            self.text_settings.title = config.get("title_text", self.text_settings.title)
            self.text_settings.subtitle = config.get("subtitle_text", self.text_settings.subtitle)
            self.text_settings.name_prefix = config.get("name_prefix", self.text_settings.name_prefix)
            self.text_settings.title_font_size = config.get("title_font_size", self.text_settings.title_font_size)
            self.text_settings.subtitle_font_size = config.get("subtitle_font_size", self.text_settings.subtitle_font_size)
            self.text_settings.name_font_size = config.get("name_font_size", self.text_settings.name_font_size)
            self.text_settings.text_color = config.get("text_color", self.text_settings.text_color)
        
        generation = config.get("generation")
        if generation:
            self.generation_options.qr_scale = generation.get("qr_scale", self.generation_options.qr_scale)
            self.generation_options.output_dpi = generation.get("output_dpi", self.generation_options.output_dpi)
            self.generation_options.output_quality = generation.get("output_quality", self.generation_options.output_quality)
            self.generation_options.output_format = generation.get("output_format", self.generation_options.output_format)
            self.generation_options.create_zip = generation.get("create_zip", self.generation_options.create_zip)
            self.generation_options.create_pdf = generation.get("create_pdf", self.generation_options.create_pdf)
        else:
            self.generation_options.qr_scale = config.get("qr_scale", self.generation_options.qr_scale)
            self.generation_options.output_dpi = config.get("output_dpi", self.generation_options.output_dpi)
            self.generation_options.output_quality = config.get("output_quality", self.generation_options.output_quality)
            self.generation_options.output_format = config.get("output_format", self.generation_options.output_format)
            self.generation_options.create_zip = config.get("create_zip", self.generation_options.create_zip)
            self.generation_options.create_pdf = config.get("create_pdf", self.generation_options.create_pdf)
        
        self.selected_template = config.get("selected_template", self.selected_template)
        self.theme_colors = self.normalize_palette(config.get("theme_colors", self.theme_colors))
        self.custom_colors = self.normalize_palette(config.get("custom_colors", self.custom_colors), allow_none=True)
        self.use_custom_colors = config.get("use_custom_colors", self.use_custom_colors)
        self.dark_theme = config.get("dark_theme", self.dark_theme)
        self.auto_theme = config.get("auto_theme", self.auto_theme)
        self.quick_preview_mode = config.get("quick_preview_mode", self.quick_preview_mode)
        self.preview_quality = config.get("preview_quality", self.preview_quality)
        self.current_theme_preset = config.get("current_theme_preset", self.current_theme_preset)
    
    def save_history(self):
        try:
            self.config_storage.save_history(self.history)
        except Exception as e:
            print(f"Failed to save history: {e}")
    
    def load_history(self):
        try:
            self.history = self.config_storage.load_history()
        except Exception as e:
            print(f"Failed to load history: {e}")
            self.history = []
    
    def save_custom_templates(self):
        try:
            self.config_storage.save_custom_templates(self.custom_templates)
        except Exception as e:
            print(f"Failed to save custom templates: {e}")
    
    def load_custom_templates(self):
        try:
            self.custom_templates = self.config_storage.load_custom_templates()
        except Exception as e:
            print(f"Failed to load custom templates: {e}")
            self.custom_templates = []
    
    def closeEvent(self, event):
        self.save_config()
        event.accept()

    # Dataclass-backed proxies keep the rest of the UI code unchanged while
    # state itself lives in dedicated containers.
    @property
    def input_file(self):
        return self.assets.input_file

    @input_file.setter
    def input_file(self, value):
        self.assets.input_file = value

    @property
    def output_dir(self):
        return self.assets.output_dir

    @output_dir.setter
    def output_dir(self, value):
        self.assets.output_dir = value

    @property
    def logo_file(self):
        return self.assets.logo_file

    @logo_file.setter
    def logo_file(self, value):
        self.assets.logo_file = value

    @property
    def title_text(self):
        return self.text_settings.title

    @title_text.setter
    def title_text(self, value):
        self.text_settings.title = value

    @property
    def subtitle_text(self):
        return self.text_settings.subtitle

    @subtitle_text.setter
    def subtitle_text(self, value):
        self.text_settings.subtitle = value

    @property
    def name_prefix(self):
        return self.text_settings.name_prefix

    @name_prefix.setter
    def name_prefix(self, value):
        self.text_settings.name_prefix = value

    @property
    def title_font_size(self):
        return self.text_settings.title_font_size

    @title_font_size.setter
    def title_font_size(self, value):
        self.text_settings.title_font_size = value

    @property
    def subtitle_font_size(self):
        return self.text_settings.subtitle_font_size

    @subtitle_font_size.setter
    def subtitle_font_size(self, value):
        self.text_settings.subtitle_font_size = value

    @property
    def name_font_size(self):
        return self.text_settings.name_font_size

    @name_font_size.setter
    def name_font_size(self, value):
        self.text_settings.name_font_size = value

    @property
    def text_color(self):
        return self.text_settings.text_color

    @text_color.setter
    def text_color(self, value):
        self.text_settings.text_color = value

    @property
    def qr_scale(self):
        return self.generation_options.qr_scale

    @qr_scale.setter
    def qr_scale(self, value):
        self.generation_options.qr_scale = value
        if hasattr(self, 'qr_scale_label'):
            self.qr_scale_label.setText(str(value))

    @property
    def output_dpi(self):
        return self.generation_options.output_dpi

    @output_dpi.setter
    def output_dpi(self, value):
        self.generation_options.output_dpi = value

    @property
    def output_quality(self):
        return self.generation_options.output_quality

    @output_quality.setter
    def output_quality(self, value):
        self.generation_options.output_quality = value

    @property
    def output_format(self):
        return self.generation_options.output_format

    @output_format.setter
    def output_format(self, value):
        self.generation_options.output_format = value

    @property
    def create_zip(self):
        return self.generation_options.create_zip

    @create_zip.setter
    def create_zip(self, value):
        self.generation_options.create_zip = value

    @property
    def create_pdf(self):
        return self.generation_options.create_pdf

    @create_pdf.setter
    def create_pdf(self, value):
        self.generation_options.create_pdf = value


class WorkerSignals(QObject):
    progress = pyqtSignal(int)
    finished = pyqtSignal(bool, str)


class QRWorker(QRunnable):
    def __init__(self, parent):
        super().__init__()
        self.parent = parent
        self.signals = WorkerSignals()

    def run(self):
        try:
            output_dir = self.parent.output_dir
            os.makedirs(output_dir, exist_ok=True)
            
            with open(self.parent.input_file, 'r', encoding='utf-8') as f:
                links = [line.strip() for line in f.readlines() if line.strip()]
            
            total = len(links)
            self.signals.progress.emit(0)
            
            template_func = self.parent.get_template_function()
            template_name = self.parent.get_template_name()

            if self.parent.use_custom_colors and all(self.parent.custom_colors):
                colors = self.parent.custom_colors
            else:
                colors = self.parent.theme_colors

            text_settings = {
                'title': self.parent.title_text,
                'subtitle': self.parent.subtitle_text,
                'title_font_size': self.parent.title_font_size,
                'subtitle_font_size': self.parent.subtitle_font_size,
                'name_font_size': self.parent.name_font_size,
                'text_color': self.parent.text_color
            }

            formatted_file = os.path.join(output_dir, "formatted_links.txt")
            with open(formatted_file, 'w', encoding='utf-8') as out_f:
                for index, link in enumerate(links, start=1):
                    file_name = f"{self.parent.name_prefix} {index}"
                    out_f.write(f"{file_name}\n`{link}`\n\n")

                    qr_data = self.parent.detect_data_type(link)
                    qr = segno.make(qr_data, error='h')

                    temp_fd, temp_qr = tempfile.mkstemp(suffix='.png')
                    os.close(temp_fd)

                    try:
                        qr.save(temp_qr, scale=self.parent.qr_scale, dark='#1a1a2e', light='#ffffff', border=1)
                        qr_img = Image.open(temp_qr)

                        final_img = template_func(
                            qr_img, file_name, colors,
                            self.parent.logo_file if self.parent.logo_file else None,
                            text_settings
                        )

                        output_file = os.path.join(output_dir, f"{template_name}_{file_name}.{self.parent.output_format.lower()}")
                        if self.parent.output_format == "PNG":
                            final_img.save(output_file, format="PNG", quality=self.parent.output_quality)
                        elif self.parent.output_format == "JPG":
                            final_img.save(output_file, format="JPEG", quality=self.parent.output_quality)
                        elif self.parent.output_format == "WEBP":
                            final_img.save(output_file, format="WEBP", quality=self.parent.output_quality)

                        progress = int((index / total) * 100)
                        self.signals.progress.emit(progress)

                    finally:
                        if os.path.exists(temp_qr):
                            os.unlink(temp_qr)

            self.parent.history.append({
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "template": template_name,
                "count": total,
                "output_dir": output_dir
            })
            self.parent.save_history()

            self.signals.finished.emit(True, f"✅ Generated {total} QR codes successfully!\n\n📁 Path: {output_dir}")

        except Exception as e:
            self.signals.finished.emit(False, f"❌ Failed to generate QR codes:\n{str(e)}")

class TemplateDialog(QDialog):
    def __init__(self, parent, title, template=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(800, 700)
        
        layout = QVBoxLayout(self)
        
        # 模板名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("Template Name:"))
        self.name_edit = QLineEdit()
        name_layout.addWidget(self.name_edit)
        layout.addLayout(name_layout)
        
        # 模板描述
        desc_layout = QHBoxLayout()
        desc_layout.addWidget(QLabel("Description:"))
        self.desc_edit = QLineEdit()
        desc_layout.addWidget(self.desc_edit)
        layout.addLayout(desc_layout)
        
        # 模板代码
        layout.addWidget(QLabel("Template Code (Python):"))
        self.code_edit = QTextEdit()
        self.code_edit.setFont(QFont("Consolas", 11))
        layout.addWidget(self.code_edit)
        
        # 按钮
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # 加载模板（如果是编辑）
        if template:
            self.name_edit.setText(template['name'])
            self.desc_edit.setText(template['description'])
            self.code_edit.setPlainText(template['code'])
        else:
            # 默认模板代码
            default_code = '''def template_custom(qr_img, file_name, colors, logo_path, text_settings):
    """Custom template function"""
    qr_width, qr_height = qr_img.size
    card_width = qr_width + 100
    card_height = qr_height + 150
    
    # 创建背景
    final_img = Image.new('RGB', (card_width, card_height), colors[0])
    draw = ImageDraw.Draw(final_img)
    
    # 添加QR码
    qr_x = (card_width - qr_width) // 2
    qr_y = 50
    final_img.paste(qr_img, (qr_x, qr_y))
    
    # 添加文本
    try:
        font = ImageFont.truetype("arial.ttf", text_settings['title_font_size'])
        title_bbox = draw.textbbox((0, 0), text_settings['title'], font=font)
        title_w = title_bbox[2] - title_bbox[0]
        draw.text(((card_width - title_w) // 2, 10), text_settings['title'], 
                 font=font, fill=text_settings['text_color'])
    except:
        pass
    
    return final_img'''
            self.code_edit.setPlainText(default_code)
    
    def validate_and_accept(self):
        name = self.name_edit.text().strip()
        desc = self.desc_edit.text().strip()
        code = self.code_edit.toPlainText().strip()
        
        if not name or not code:
            QMessageBox.warning(self, "Warning", "Please enter template name and code")
            return
        
        try:
            namespace = {}
            exec(code, namespace)
            
            if 'template_custom' not in namespace:
                QMessageBox.warning(self, "Warning", "Template function must be named 'template_custom'")
                return
            
            self.accept()
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Invalid template code: {str(e)}")
    
    def get_template(self):
        return {
            'name': self.name_edit.text().strip(),
            'description': self.desc_edit.text().strip(),
            'code': self.code_edit.toPlainText().strip()
        }


class SettingsDialog(QDialog):
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("⚙️ Settings")
        self.setModal(True)
        self.resize(600, 500)
        
        layout = QVBoxLayout(self)
        
        # 创建选项卡
        tabs = QTabWidget()
        
        # 常规选项卡
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        
        # 自动保存设置
        self.auto_save_check = QCheckBox("Auto-save configuration on exit")
        self.auto_save_check.setChecked(True)
        general_layout.addWidget(self.auto_save_check)
        
        self.auto_open_check = QCheckBox("Auto-open output folder after generation")
        self.auto_open_check.setChecked(False)
        general_layout.addWidget(self.auto_open_check)
        
        # 备份设置
        self.backup_check = QCheckBox("Create backup before generation")
        self.backup_check.setChecked(True)
        general_layout.addWidget(self.backup_check)
        
        general_layout.addStretch()
        tabs.addTab(general_tab, "⚙️ General")
        
        # 性能选项卡
        performance_tab = QWidget()
        performance_layout = QVBoxLayout(performance_tab)
        
        # 线程数
        thread_layout = QHBoxLayout()
        thread_layout.addWidget(QLabel("Thread Count:"))
        self.thread_spin = QSpinBox()
        self.thread_spin.setRange(1, 8)
        self.thread_spin.setValue(4)
        thread_layout.addWidget(self.thread_spin)
        thread_layout.addStretch()
        performance_layout.addLayout(thread_layout)
        
        # 快速预览
        self.quick_preview_check = QCheckBox("Quick Preview Mode")
        self.quick_preview_check.setChecked(parent.quick_preview_mode)
        performance_layout.addWidget(self.quick_preview_check)
        
        performance_layout.addStretch()
        tabs.addTab(performance_tab, "⚡ Performance")
        
        # 关于选项卡
        about_tab = QWidget()
        about_layout = QVBoxLayout(about_tab)
        
        about_text = QLabel(
            "🎨 QR Code Generator Pro\n"
            "Version 2.0\n\n"
            "A professional QR code generator with custom templates\n\n"
            "✨ Features:\n"
            "• 🌊 Multiple built-in templates\n"
            "• 🎨 Custom template support\n"
            "• ✏️ Full text customization\n"
            "• 👁️ Live preview\n"
            "• 📋 History tracking\n"
            "• 🌙 Beautiful dark/light theme\n"
            "• 🚀 High performance\n\n"
            "🔧 Built with PyQt6\n"
            "© 2024 QR Generator Pro"
        )
        about_text.setAlignment(Qt.AlignmentFlag.AlignCenter)
        about_text.setStyleSheet("""
            QLabel {
                font-size: 14px;
                line-height: 1.5;
                padding: 20px;
            }
        """)
        about_layout.addWidget(about_text)
        tabs.addTab(about_tab, "ℹ️ About")
        
        layout.addWidget(tabs)
        
        # 关闭按钮
        close_btn = QPushButton("❌ Close")
        close_btn.setProperty("class", "primary")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    
    # 设置应用程序信息
    app.setApplicationName("QR Code Generator Pro")
    app.setApplicationVersion("2.0")
    app.setOrganizationName("QR Generator Pro")
    
    window = ModernQRGenerator()
    window.apply_theme()  # 应用初始主题
    window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
