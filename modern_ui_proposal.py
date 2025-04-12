import sys
import os
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, Signal

# Exemple de code pour moderniser l'interface utilisateur
class ModernImageComparerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Comparer - Modern UI")
        self.setGeometry(100, 100, 1200, 700)
        
        # Application d'un style moderne
        self.apply_modern_style()
        
        # Configuration de l'interface
        self.setup_ui()
    
    def apply_modern_style(self):
        """Applique un style moderne à l'application"""
        # Palette de couleurs moderne
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor(53, 53, 53))
        palette.setColor(QtGui.QPalette.WindowText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.Base, QtGui.QColor(25, 25, 25))
        palette.setColor(QtGui.QPalette.AlternateBase, QtGui.QColor(53, 53, 53))
        palette.setColor(QtGui.QPalette.ToolTipBase, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.ToolTipText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.Text, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.Button, QtGui.QColor(53, 53, 53))
        palette.setColor(QtGui.QPalette.ButtonText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor(255, 0, 0))
        palette.setColor(QtGui.QPalette.Link, QtGui.QColor(42, 130, 218))
        palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor(42, 130, 218))
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor(255, 255, 255))
        
        # Application de la palette
        self.setPalette(palette)
        
        # Style des widgets
        style_sheet = """
        QMainWindow {
            background-color: #353535;
        }
        QWidget {
            color: #ffffff;
            background-color: #353535;
        }
        QPushButton {
            background-color: #2a82da;
            color: white;
            border: none;
            padding: 5px 15px;
            border-radius: 4px;
            font-weight: bold;
        }
        QPushButton:hover {
            background-color: #3a92ea;
        }
        QPushButton:pressed {
            background-color: #1a72ca;
        }
        QComboBox {
            border: 1px solid #555555;
            border-radius: 3px;
            padding: 3px 15px 3px 5px;
            min-width: 6em;
            background-color: #2a2a2a;
        }
        QComboBox:hover {
            border: 1px solid #2a82da;
        }
        QComboBox::drop-down {
            subcontrol-origin: padding;
            subcontrol-position: top right;
            width: 15px;
            border-left-width: 1px;
            border-left-color: #555555;
            border-left-style: solid;
        }
        QRadioButton {
            spacing: 5px;
        }
        QRadioButton::indicator {
            width: 15px;
            height: 15px;
        }
        QCheckBox {
            spacing: 5px;
        }
        QCheckBox::indicator {
            width: 15px;
            height: 15px;
        }
        QSlider::groove:horizontal {
            border: 1px solid #999999;
            height: 8px;
            background: #2a2a2a;
            margin: 2px 0;
            border-radius: 4px;
        }
        QSlider::handle:horizontal {
            background: #2a82da;
            border: 1px solid #5c5c5c;
            width: 18px;
            margin: -2px 0;
            border-radius: 9px;
        }
        QStatusBar {
            background-color: #2a2a2a;
            color: #ffffff;
        }
        QLabel {
            color: #ffffff;
        }
        QGroupBox {
            border: 1px solid #555555;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 15px;
        }
        QGroupBox::title {
            subcontrol-origin: margin;
            subcontrol-position: top left;
            padding: 0 5px;
            color: #2a82da;
            font-weight: bold;
        }
        """
        self.setStyleSheet(style_sheet)
    
    def setup_ui(self):
        """Configuration de l'interface utilisateur moderne"""
        # Widget central
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        
        # Barre d'outils
        self.toolbar = QtWidgets.QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QtCore.QSize(24, 24))
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)
        
        # Actions de la barre d'outils
        self.action_open_image1 = QtWidgets.QAction("Open Image 1", self)
        self.action_open_image1.setIcon(QtGui.QIcon.fromTheme("document-open"))
        self.toolbar.addAction(self.action_open_image1)
        
        self.action_open_image2 = QtWidgets.QAction("Open Image 2", self)
        self.action_open_image2.setIcon(QtGui.QIcon.fromTheme("document-open"))
        self.toolbar.addAction(self.action_open_image2)
        
        self.toolbar.addSeparator()
        
        self.action_reset_view = QtWidgets.QAction("Reset View", self)
        self.action_reset_view.setIcon(QtGui.QIcon.fromTheme("view-refresh"))
        self.toolbar.addAction(self.action_reset_view)
        
        # Panneau de contrôle
        control_panel = QtWidgets.QFrame()
        control_panel.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        control_panel.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        control_layout = QtWidgets.QHBoxLayout(control_panel)
        control_layout.setContentsMargins(5, 5, 5, 5)
        control_layout.setSpacing(10)
        main_layout.addWidget(control_panel)
        
        # Groupe de chargement d'images
        load_group = QtWidgets.QGroupBox("Images")
        load_layout = QtWidgets.QVBoxLayout(load_group)
        
        # Boutons avec icônes
        btn_load1 = QtWidgets.QPushButton("Load Image 1")
        btn_load1.setIcon(QtGui.QIcon.fromTheme("document-open"))
        self.lbl_img1 = QtWidgets.QLabel("No Image 1")
        self.lbl_img1.setWordWrap(True)
        
        btn_load2 = QtWidgets.QPushButton("Load Image 2")
        btn_load2.setIcon(QtGui.QIcon.fromTheme("document-open"))
        self.lbl_img2 = QtWidgets.QLabel("No Image 2")
        self.lbl_img2.setWordWrap(True)
        
        load_layout.addWidget(btn_load1)
        load_layout.addWidget(self.lbl_img1)
        load_layout.addStretch()
        load_layout.addWidget(btn_load2)
        load_layout.addWidget(self.lbl_img2)
        control_layout.addWidget(load_group)
        
        # Groupe des modes de comparaison
        mode_group = QtWidgets.QGroupBox("Comparison Mode")
        mode_layout = QtWidgets.QVBoxLayout(mode_group)
        
        # Boutons radio avec disposition verticale
        self.radio_side = QtWidgets.QRadioButton("Side by Side")
        self.radio_side.setChecked(True)
        self.radio_slider = QtWidgets.QRadioButton("Slider")
        self.radio_ab_switch = QtWidgets.QRadioButton("A/B Switch")
        
        mode_layout.addWidget(self.radio_side)
        mode_layout.addWidget(self.radio_slider)
        mode_layout.addWidget(self.radio_ab_switch)
        
        # Options spécifiques au mode
        self.options_stack = QtWidgets.QStackedWidget()
        mode_layout.addWidget(self.options_stack)
        
        # Page vide pour les modes sans options
        self.options_stack.addWidget(QtWidgets.QWidget())
        
        # Page pour le mode A/B switch
        ab_switch_widget = QtWidgets.QWidget()
        ab_switch_layout = QtWidgets.QVBoxLayout(ab_switch_widget)
        
        ab_speed_layout = QtWidgets.QHBoxLayout()
        ab_speed_layout.addWidget(QtWidgets.QLabel("Switch Speed:"))
        
        self.slider_ab_speed = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_ab_speed.setRange(100, 2000)
        self.slider_ab_speed.setValue(500)
        ab_speed_layout.addWidget(self.slider_ab_speed)
        
        self.lbl_ab_speed_value = QtWidgets.QLabel("500 ms")
        ab_speed_layout.addWidget(self.lbl_ab_speed_value)
        
        ab_switch_layout.addLayout(ab_speed_layout)
        self.options_stack.addWidget(ab_switch_widget)
        
        control_layout.addWidget(mode_group, 1)
        
        # Groupe d'ajustement de taille
        adjust_group = QtWidgets.QGroupBox("Size Adjustment")
        adjust_layout = QtWidgets.QVBoxLayout(adjust_group)
        
        self.combo_size_adjust = QtWidgets.QComboBox()
        self.combo_size_adjust.addItem("Resize Image 2 → Image 1", "resize2to1")
        self.combo_size_adjust.addItem("Resize Image 1 → Image 2", "resize1to2")
        self.combo_size_adjust.addItem("Resize Both (Max Size)", "resizeboth")
        self.combo_size_adjust.addItem("Keep Original Sizes", "original")
        self.combo_size_adjust.addItem("Proportional Adjustment", "proportional")
        
        adjust_layout.addWidget(self.combo_size_adjust)
        control_layout.addWidget(adjust_group)
        
        # Groupe des options de vue
        view_group = QtWidgets.QGroupBox("View Options")
        view_layout = QtWidgets.QVBoxLayout(view_group)
        
        self.check_link_views = QtWidgets.QCheckBox("Link Views")
        self.check_link_views.setChecked(True)
        view_layout.addWidget(self.check_link_views)
        
        # Ajout de nouvelles options
        self.check_show_grid = QtWidgets.QCheckBox("Show Grid")
        view_layout.addWidget(self.check_show_grid)
        
        self.check_high_quality = QtWidgets.QCheckBox("High Quality Rendering")
        self.check_high_quality.setChecked(True)
        view_layout.addWidget(self.check_high_quality)
        
        view_layout.addStretch()
        
        btn_reset_view = QtWidgets.QPushButton("Reset View")
        btn_reset_view.setIcon(QtGui.QIcon.fromTheme("view-refresh"))
        view_layout.addWidget(btn_reset_view)
        
        control_layout.addWidget(view_group)
        
        # Zone d'affichage
        self.view_stack = QtWidgets.QStackedWidget()
        main_layout.addWidget(self.view_stack, 1)
        
        # Barre de statut améliorée
        self.statusBar = QtWidgets.QStatusBar()
        self.setStatusBar(self.statusBar)
        
        self.lbl_status_coords = QtWidgets.QLabel("Coords: (N/A, N/A)")
        self.lbl_status_rgb = QtWidgets.QLabel("RGB: (N/A)")
        self.lbl_status_zoom = QtWidgets.QLabel("Zoom: 100%")
        
        self.statusBar.addPermanentWidget(self.lbl_status_coords)
        self.statusBar.addPermanentWidget(self.lbl_status_rgb)
        self.statusBar.addPermanentWidget(self.lbl_status_zoom)
        
        # Menu principal
        self.setup_menu()
    
    def setup_menu(self):
        """Configuration du menu principal"""
        menubar = self.menuBar()
        
        # Menu Fichier
        file_menu = menubar.addMenu("&File")
        
        open_image1_action = QtWidgets.QAction("Open Image &1...", self)
        open_image1_action.setShortcut("Ctrl+1")
        file_menu.addAction(open_image1_action)
        
        open_image2_action = QtWidgets.QAction("Open Image &2...", self)
        open_image2_action.setShortcut("Ctrl+2")
        file_menu.addAction(open_image2_action)
        
        file_menu.addSeparator()
        
        # Sous-menu fichiers récents
        self.recent_menu = file_menu.addMenu("Recent Files")
        
        file_menu.addSeparator()
        
        exit_action = QtWidgets.QAction("E&xit", self)
        exit_action.setShortcut("Ctrl+Q")
        file_menu.addAction(exit_action)
        
        # Menu Édition
        edit_menu = menubar.addMenu("&Edit")
        
        copy_action = QtWidgets.QAction("&Copy Current View", self)
        copy_action.setShortcut("Ctrl+C")
        edit_menu.addAction(copy_action)
        
        # Menu Vue
        view_menu = menubar.addMenu("&View")
        
        zoom_in_action = QtWidgets.QAction("Zoom &In", self)
        zoom_in_action.setShortcut("Ctrl++")
        view_menu.addAction(zoom_in_action)
        
        zoom_out_action = QtWidgets.QAction("Zoom &Out", self)
        zoom_out_action.setShortcut("Ctrl+-")
        view_menu.addAction(zoom_out_action)
        
        reset_zoom_action = QtWidgets.QAction("&Reset Zoom", self)
        reset_zoom_action.setShortcut("Ctrl+0")
        view_menu.addAction(reset_zoom_action)
        
        view_menu.addSeparator()
        
        side_by_side_action = QtWidgets.QAction("&Side by Side Mode", self)
        side_by_side_action.setShortcut("Ctrl+S")
        view_menu.addAction(side_by_side_action)
        
        slider_action = QtWidgets.QAction("S&lider Mode", self)
        slider_action.setShortcut("Ctrl+L")
        view_menu.addAction(slider_action)
        
        ab_switch_action = QtWidgets.QAction("&A/B Switch Mode", self)
        ab_switch_action.setShortcut("Ctrl+A")
        view_menu.addAction(ab_switch_action)
        
        # Menu Aide
        help_menu = menubar.addMenu("&Help")
        
        about_action = QtWidgets.QAction("&About", self)
        help_menu.addAction(about_action)
        
        keyboard_shortcuts_action = QtWidgets.QAction("&Keyboard Shortcuts", self)
        help_menu.addAction(keyboard_shortcuts_action)

# Exemple d'utilisation
if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = ModernImageComparerApp()
    window.show()
    sys.exit(app.exec())
