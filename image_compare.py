# --- Imports ---
import sys
import os
import numpy as np
# Utiliser PySide6 au lieu de PyQt5
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QSize, QTimer # Remplacer pyqtSignal par Signal
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QBrush, QColor, QTransform, QAction # QAction pour menus/barres d'outils si besoin
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QRadioButton, QSlider, QComboBox,
    QCheckBox, QFrame, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsLineItem, QSizePolicy, QStatusBar, QMessageBox, QGridLayout,
    QStyle, QStackedWidget, QGroupBox # Added QGroupBox
)
# Try importing ImageQt, handle potential import variations
try:
    from PIL import ImageQt
except ImportError:
    print("Warning: PIL.ImageQt not found directly. Ensure Pillow is up-to-date.")
    ImageQt = None

from PIL import Image, ImageChops, ImageOps

# Try importing scikit-image for metrics
try:
    from skimage.metrics import mean_squared_error, peak_signal_noise_ratio, structural_similarity
    SKIMAGE_AVAILABLE = True
except ImportError:
    print("Warning: scikit-image not found. Metrics calculation (MSE, PSNR, SSIM) will be disabled.")
    SKIMAGE_AVAILABLE = False
    # Define dummy functions if skimage is not available
    def mean_squared_error(img1, img2): return -1.0
    def peak_signal_noise_ratio(img1, img2, data_range=255): return -1.0
    def structural_similarity(img1, img2, data_range=255, channel_axis=-1): return -1.0


# --- Configuration ---
MAX_IMAGE_DIM_LOAD = 3000 # Keep existing limit

# --- Custom Graphics View (ImageViewer) ---
# No changes needed in ImageViewer itself, keeping it as provided.
class ImageViewer(QtWidgets.QGraphicsView):
    """ QGraphicsView customisé pour afficher une image avec zoom/pan """
    viewChanged = Signal() # Utiliser Signal de PySide6
    mouseMoved = Signal(QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True) # Utiliser QPainter.RenderHint
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse) # Utiliser ViewportAnchor
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff) # Utiliser QtCore.Qt
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor(70, 70, 70)))
        self.setFrameShape(QFrame.Shape.NoFrame) # Utiliser QFrame.Shape
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag) # Utiliser DragMode

        self._zoom = 1.0
        self._panning = False
        self._last_pan_point = QtCore.QPoint()

        self.setMouseTracking(True)

    def set_pixmap(self, pixmap):
        if pixmap and not pixmap.isNull():
            self._pixmap_item.setPixmap(pixmap)
            # Important: Set scene rect *before* fitting
            self._scene.setSceneRect(QRectF(pixmap.rect()))
            self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio) # Utiliser QtCore.Qt
            self._zoom = self.transform().m11() # Update zoom after fitInView
        else:
            self._pixmap_item.setPixmap(QPixmap())
            self._scene.setSceneRect(QRectF()) # Clear scene rect if no pixmap

    def get_pixmap_item(self):
        return self._pixmap_item

    def wheelEvent(self, event: QtGui.QWheelEvent):
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
            self._zoom *= zoom_factor
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor)
            self._zoom /= zoom_factor
        self.viewChanged.emit()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton: # Utiliser QtCore.Qt
             self._panning = True
             self._last_pan_point = event.position().toPoint() # Utiliser event.position() dans PySide6
             self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor) # Utiliser QtCore.Qt
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        scene_pos = self.mapToScene(event.position().toPoint()) # Utiliser event.position()
        self.mouseMoved.emit(scene_pos)

        if self._panning:
             # Use global position for delta calculation to avoid jumps when cursor leaves/enters window
             global_pos = event.globalPosition().toPoint()
             if not self._last_pan_point.isNull(): # Check if last point is valid
                 delta = global_pos - self._last_pan_point
                 self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
                 self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
                 self.viewChanged.emit()
             self._last_pan_point = global_pos # Update last point
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._panning = False
            self._last_pan_point = QtCore.QPoint() # Reset last pan point
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor) # Use ArrowCursor or OpenHandCursor
        super().mouseReleaseEvent(event)

    def reset_view(self):
        if not self._pixmap_item.pixmap().isNull():
            # Ensure scene rect is correct before fitting
            self._scene.setSceneRect(QRectF(self._pixmap_item.pixmap().rect()))
            self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()
            self.viewChanged.emit()
        else:
            # Reset transform even if pixmap is null
            self.setTransform(QTransform())
            self._zoom = 1.0
            self.viewChanged.emit()


    def get_transform(self) -> QTransform:
        return self.transform()

    # Modified set_transform to handle potential floating point inaccuracies and ensure update
    def set_transform(self, transform: QTransform):
        current_transform = self.transform()
        # Compare relevant parts (scale and translation)
        if (not np.isclose(current_transform.m11(), transform.m11()) or
            not np.isclose(current_transform.m22(), transform.m22()) or
            not np.isclose(current_transform.dx(), transform.dx()) or
            not np.isclose(current_transform.dy(), transform.dy())):

            super().setTransform(transform) # Use the base class method
            self._zoom = transform.m11() # Update internal zoom state
            # self.viewChanged.emit() # Avoid emitting here, let sync_views handle it


# --- Custom Slider Item (InteractiveSliderItem) ---
# No changes needed in InteractiveSliderItem itself, keeping it as provided.
class InteractiveSliderItem(QtWidgets.QGraphicsItem):
    """
    Une implémentation optimisée du curseur interactif qui utilise une approche
    plus performante pour le rendu et les déplacements.
    """
    # Pour PySide6, les signaux doivent être attachés à un QObject
    class Signals(QtCore.QObject):
        positionChanged = Signal(float)
        positionChanging = Signal(float)  # Signal pendant le déplacement (optimisation)

    def __init__(self, scene_rect, parent=None):
        super().__init__(parent)
        self.scene_rect = scene_rect
        self._position = 0.5
        # Définir la largeur de la ligne (en pixels)
        self._line_width = 2
        self._line_color = QtCore.Qt.GlobalColor.red
        self._is_dragging = False

        # Instancier les signaux
        self.signals = self.Signals()
        self.positionChanged = self.signals.positionChanged
        self.positionChanging = self.signals.positionChanging

        # Cache pour limiter les émissions de signaux
        self._last_emitted_position = None
        self._position_change_threshold = 0.005  # Émettre seulement si mouvement > 0.5%

        # Permettre les interactions
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)

        # Zone active plus large pour faciliter la saisie
        self._active_width = 10  # En pixels

    def boundingRect(self):
        """
        Renvoie le rectangle englobant de l'élément, qui définit sa zone de dessin.
        Zone élargie pour faciliter la saisie du curseur.
        """
        if not self.scene_rect or self.scene_rect.isNull() or self.scene_rect.width() <= 0:
             # Return a minimal valid rect if scene_rect is invalid
             x = -self._active_width / 2
             y = -50 # Arbitrary height if scene rect is bad
             w = self._active_width
             h = 100
             return QRectF(x, y, w, h)


        # Ajout d'une marge pour la largeur du trait et zone active
        half_active = self._active_width / 2
        x = self.scene_rect.left() + self.scene_rect.width() * self._position - half_active
        y = self.scene_rect.top()
        w = self._active_width
        h = self.scene_rect.height()

        return QRectF(x, y, w, h)

    def paint(self, painter, option, widget):
        """
        Dessine la ligne verticale du curseur avec optimisations.
        """
        if not self.scene_rect or self.scene_rect.isNull() or self.scene_rect.height() <= 0:
            return

        # Optimisation: Désactiver l'antialiasing pour la ligne verticale
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Configuration du stylo avec couleur plus visible si en cours de déplacement
        pen = QPen(
            QtCore.Qt.GlobalColor.yellow if self._is_dragging else self._line_color,
            self._line_width,
            QtCore.Qt.PenStyle.SolidLine
        )
        painter.setPen(pen)

        # Calculer la position x du slider
        x_pos = self.scene_rect.left() + self.scene_rect.width() * self._position

        # Dessiner une ligne verticale (optimisation: pas de conversion en QPointF)
        painter.drawLine(
            int(x_pos), int(self.scene_rect.top()),
            int(x_pos), int(self.scene_rect.bottom())
        )

    def mousePressEvent(self, event):
        """
        Gère l'événement de clic de souris pour activer le déplacement.
        """
        if not self.scene_rect or self.scene_rect.isNull(): return # Prevent interaction if no scene rect
        self._is_dragging = True
        self.update()  # Mettre à jour l'apparence du curseur
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """
        Gère le déplacement de la souris pour mettre à jour la position du curseur.
        Optimisé pour réduire les mises à jour.
        """
        if not self._is_dragging or not self.scene_rect or self.scene_rect.isNull():
             # event.ignore() # Allow panning if not dragging slider
             super().mouseMoveEvent(event) # Pass event up for panning
             return

        # Récupérer la position de la souris dans les coordonnées de la scène
        mouse_pos = self.mapToScene(event.pos()) # Use mapToScene for correct position

        # Calculer la nouvelle position du curseur (contrainte à la scène)
        min_x = self.scene_rect.left()
        max_x = self.scene_rect.right()

        # Ensure min_x <= max_x
        if min_x > max_x: min_x, max_x = max_x, min_x # Swap if necessary

        constrained_x = max(min_x, min(mouse_pos.x(), max_x))

        # Calculer la nouvelle position relative
        scene_width = self.scene_rect.width()
        if scene_width > 0:
            new_position = (constrained_x - min_x) / scene_width
        else:
            new_position = 0.5

        # Mettre à jour seulement si le changement est significatif
        if abs(new_position - self._position) > 0.001:
            self._position = new_position

            # Mettre à jour le rectangle englobant AVANT emitting signals/updating
            self.prepareGeometryChange()

            # N'émettre le signal que si le changement est suffisamment grand
            if (self._last_emitted_position is None or
                abs(new_position - self._last_emitted_position) > self._position_change_threshold):
                self._last_emitted_position = new_position
                # Signal en temps réel pour les updates légères pendant le déplacement
                self.signals.positionChanging.emit(self._position)

            # Demander une mise à jour du dessin (redundant due to prepareGeometryChange?)
            # self.update() # Let geometry change handle update

        # Empêcher la propagation de l'événement pour ne pas panner la vue en même temps
        event.accept()


    def mouseReleaseEvent(self, event):
        """
        Gère la libération du bouton de la souris.
        Émet le signal final de changement de position.
        """
        if not self._is_dragging:
            super().mouseReleaseEvent(event)
            return

        self._is_dragging = False

        # Émettre le signal final de position pour mise à jour de haute qualité
        self.signals.positionChanged.emit(self._position)
        self._last_emitted_position = None # Reset cache

        # Mise à jour de l'apparence
        self.update()

        super().mouseReleaseEvent(event)

    def set_scene_rect(self, rect):
        """
        Met à jour le rectangle de scène et déclenche une mise à jour.
        """
        if self.scene_rect != rect:
            self.prepareGeometryChange() # Notify change before updating rect
            self.scene_rect = rect
            self.update() # Trigger repaint

    def set_position_ratio(self, ratio):
        """
        Définit la position relative (0.0 à 1.0) et met à jour.
        """
        new_pos = max(0.0, min(1.0, ratio))
        if not np.isclose(self._position, new_pos):
            self.prepareGeometryChange() # Notify change before updating position
            self._position = new_pos
            self._last_emitted_position = self._position # Update cache
            self.update() # Trigger repaint

    def get_position_ratio(self):
        """
        Renvoie la position relative actuelle (entre 0 et 1).
        """
        return self._position

    # itemChange is complex, ensure it doesn't interfere unless needed
    # def itemChange(self, change, value):
    #     # Example: Constrain movement if needed, but ItemIsMovable handles basic movement
    #     # if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionChange:
    #         # # value is the new position.
    #         # # Constrain value.x() based on scene_rect if necessary
    #         # pass
    #     return super().itemChange(change, value)


# --- Classe Principale de l'Application ---
class ImageComparerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("VGG-Style Image Comparer (PySide6)")
        self.setGeometry(100, 100, 1400, 800) # Increased default size

        # --- Variables d'état ---
        self.image_path1 = None
        self.image_path2 = None
        self.pil_image1_orig = None
        self.pil_image2_orig = None
        self.qt_pixmap1_orig = None
        self.qt_pixmap2_orig = None
        self.display_pixmap1 = None # Pixmap potentially resized for display/comparison
        self.display_pixmap2 = None # Pixmap potentially resized for display/comparison
        self.comparison_pixmap = None # Result of comparison modes
        self.current_mode = "side_by_side"
        self.opacity_value = 0.5
        self.diff_colormap = "grayscale"
        self.diff_threshold = 0.0 # New: Difference threshold (0.0 to 1.0)
        self.checker_size = 20
        self.link_views_enabled = True
        self._is_updating_views = False
        self._slider_pixmaps = None # Cache for slider mode
        self._switch_state_is_b = False # State for Switch A/B mode

        # --- Initialisation UI ---
        self.setup_ui()
        self.update_display()
        self.update_metrics_display() # Initial update for placeholders

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        # Main layout: Horizontal split (Controls Left, Display Right)
        main_layout = QHBoxLayout(main_widget)

        # --- Panneau de Contrôle (Gauche) ---
        control_panel = QFrame()
        control_panel.setFrameShape(QFrame.Shape.StyledPanel)
        control_panel.setFixedWidth(350) # Give controls a fixed width
        control_layout = QVBoxLayout(control_panel)
        control_layout.setAlignment(Qt.AlignmentFlag.AlignTop) # Align sections to top
        main_layout.addWidget(control_panel)

        # --- Section: Load Images ---
        load_group = QGroupBox("Load Images")
        load_layout = QGridLayout(load_group) # Use grid for better alignment

        btn_load1 = QPushButton("Load Image A")
        btn_load1.clicked.connect(lambda: self.load_image(1))
        self.lbl_img1 = QLabel("No Image A")
        self.lbl_img1.setWordWrap(True)
        btn_clear1 = QPushButton("Clear A")
        btn_clear1.clicked.connect(lambda: self.clear_image(1))

        btn_load2 = QPushButton("Load Image B")
        btn_load2.clicked.connect(lambda: self.load_image(2))
        self.lbl_img2 = QLabel("No Image B")
        self.lbl_img2.setWordWrap(True)
        btn_clear2 = QPushButton("Clear B")
        btn_clear2.clicked.connect(lambda: self.clear_image(2))

        load_layout.addWidget(btn_load1, 0, 0)
        load_layout.addWidget(self.lbl_img1, 0, 1)
        load_layout.addWidget(btn_clear1, 0, 2)
        load_layout.addWidget(btn_load2, 1, 0)
        load_layout.addWidget(self.lbl_img2, 1, 1)
        load_layout.addWidget(btn_clear2, 1, 2)
        control_layout.addWidget(load_group)

        # --- Section: View Mode ---
        mode_group = QGroupBox("View Mode")
        mode_layout = QVBoxLayout(mode_group)

        self.radio_side = QRadioButton("Side by Side")
        self.radio_side.setChecked(True)
        self.radio_side.toggled.connect(lambda checked: self.set_mode("side_by_side") if checked else None)
        mode_layout.addWidget(self.radio_side)

        self.radio_slider = QRadioButton("Slider")
        self.radio_slider.toggled.connect(lambda checked: self.set_mode("slider") if checked else None)
        mode_layout.addWidget(self.radio_slider)

        self.radio_opacity = QRadioButton("Opacity (Fade)")
        self.radio_opacity.toggled.connect(lambda checked: self.set_mode("opacity") if checked else None)
        mode_layout.addWidget(self.radio_opacity)

        self.radio_diff = QRadioButton("Difference Map")
        self.radio_diff.toggled.connect(lambda checked: self.set_mode("difference") if checked else None)
        mode_layout.addWidget(self.radio_diff)

        self.radio_checker = QRadioButton("Checkerboard")
        self.radio_checker.toggled.connect(lambda checked: self.set_mode("checkerboard") if checked else None)
        mode_layout.addWidget(self.radio_checker)

        self.radio_switch = QRadioButton("Switch A/B") # New Mode
        self.radio_switch.toggled.connect(lambda checked: self.set_mode("switch") if checked else None)
        mode_layout.addWidget(self.radio_switch)

        control_layout.addWidget(mode_group)

        # --- Section: Mode Options ---
        options_group = QGroupBox("Mode Options")
        options_layout = QVBoxLayout(options_group)
        self.options_stack = QStackedWidget()
        options_layout.addWidget(self.options_stack)
        control_layout.addWidget(options_group)

        # Page Indices for options_stack:
        # 0: Empty/SideBySide/Switch
        # 1: Opacity
        # 2: Difference
        # 3: Checkerboard
        # 4: Slider (No specific options needed here currently)

        # Page 0: Empty Placeholder
        self.options_stack.addWidget(QWidget())

        # Page 1: Opacity Options
        opacity_widget = QWidget()
        opacity_layout = QHBoxLayout(opacity_widget)
        opacity_layout.addWidget(QLabel("Opacity A <-> B:"))
        self.slider_opacity = QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(int(self.opacity_value * 100))
        self.slider_opacity.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.slider_opacity)
        self.lbl_opacity_value = QLabel(f"{self.opacity_value:.2f}")
        opacity_layout.addWidget(self.lbl_opacity_value)
        self.options_stack.addWidget(opacity_widget) # Index 1

        # Page 2: Difference Options
        diff_widget = QWidget()
        diff_layout = QGridLayout(diff_widget) # Use grid for layout
        diff_layout.addWidget(QLabel("Colormap:"), 0, 0)
        self.combo_diff_cmap = QComboBox()
        self.combo_diff_cmap.addItems(["grayscale", "thermal", "inverted"])
        self.combo_diff_cmap.currentTextChanged.connect(self.on_diff_colormap_changed)
        diff_layout.addWidget(self.combo_diff_cmap, 0, 1, 1, 2) # Span 2 columns

        diff_layout.addWidget(QLabel("Threshold:"), 1, 0)
        self.slider_diff_threshold = QSlider(QtCore.Qt.Orientation.Horizontal) # New Threshold Slider
        self.slider_diff_threshold.setRange(0, 100) # 0-100 represents 0.0-1.0
        self.slider_diff_threshold.setValue(int(self.diff_threshold * 100))
        self.slider_diff_threshold.valueChanged.connect(self.on_diff_threshold_changed)
        diff_layout.addWidget(self.slider_diff_threshold, 1, 1)
        self.lbl_diff_threshold_value = QLabel(f"{self.diff_threshold:.2f}") # New Label
        diff_layout.addWidget(self.lbl_diff_threshold_value, 1, 2)
        self.options_stack.addWidget(diff_widget) # Index 2

        # Page 3: Checkerboard Options
        checker_widget = QWidget()
        checker_layout = QHBoxLayout(checker_widget)
        checker_layout.addWidget(QLabel("Checker Size:"))
        self.slider_checker = QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_checker.setRange(5, 100)
        self.slider_checker.setValue(self.checker_size)
        self.slider_checker.valueChanged.connect(self.on_checker_size_changed)
        checker_layout.addWidget(self.slider_checker)
        self.lbl_checker_value = QLabel(str(self.checker_size))
        checker_layout.addWidget(self.lbl_checker_value)
        self.options_stack.addWidget(checker_widget) # Index 3

        # Page 4: Slider (No options currently) - Add empty widget
        self.options_stack.addWidget(QWidget()) # Index 4

        # --- Section: Metrics ---
        metrics_group = QGroupBox("Metrics")
        metrics_layout = QGridLayout(metrics_group)

        self.lbl_mse = QLabel("MSE:")
        self.val_mse = QLabel("N/A")
        self.lbl_psnr = QLabel("PSNR:")
        self.val_psnr = QLabel("N/A")
        self.lbl_ssim = QLabel("SSIM:")
        self.val_ssim = QLabel("N/A")
        self.btn_compute_metrics = QPushButton("Compute Metrics")
        self.btn_compute_metrics.clicked.connect(self.calculate_and_display_metrics)
        self.btn_compute_metrics.setEnabled(False) # Disabled initially

        metrics_layout.addWidget(self.lbl_mse, 0, 0)
        metrics_layout.addWidget(self.val_mse, 0, 1)
        metrics_layout.addWidget(self.lbl_psnr, 1, 0)
        metrics_layout.addWidget(self.val_psnr, 1, 1)
        metrics_layout.addWidget(self.lbl_ssim, 2, 0)
        metrics_layout.addWidget(self.val_ssim, 2, 1)
        metrics_layout.addWidget(self.btn_compute_metrics, 3, 0, 1, 2) # Span 2 columns

        if not SKIMAGE_AVAILABLE:
            warning_label = QLabel("<i>scikit-image not found.\nMetrics disabled.</i>")
            warning_label.setStyleSheet("color: orange;")
            warning_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            metrics_layout.addWidget(warning_label, 4, 0, 1, 2)
            self.btn_compute_metrics.setEnabled(False)
            self.btn_compute_metrics.setToolTip("Install scikit-image to enable metrics")


        control_layout.addWidget(metrics_group)

        # --- Section: View Controls ---
        view_control_group = QGroupBox("View Controls")
        view_control_layout = QVBoxLayout(view_control_group)

        # Button for Switch A/B mode
        self.btn_switch_ab = QPushButton("Show Image B")
        self.btn_switch_ab.clicked.connect(self.toggle_switch_image)
        self.btn_switch_ab.setVisible(False) # Hidden initially
        view_control_layout.addWidget(self.btn_switch_ab)

        # Link Views Checkbox
        self.check_link_views = QCheckBox("Link Side-by-Side Views")
        self.check_link_views.setChecked(self.link_views_enabled)
        self.check_link_views.toggled.connect(self.on_link_views_toggled)
        view_control_layout.addWidget(self.check_link_views)

        # Reset View Button
        btn_reset_view = QPushButton("Reset View")
        btn_reset_view.clicked.connect(self.reset_all_views)
        view_control_layout.addWidget(btn_reset_view)

        control_layout.addWidget(view_control_group)

        control_layout.addStretch() # Pushes controls to the top

        # --- Zone d'Affichage (Droite) ---
        display_area = QFrame()
        display_area.setFrameShape(QFrame.Shape.StyledPanel)
        display_layout = QVBoxLayout(display_area) # Use QVBoxLayout for the display area itself
        display_layout.setContentsMargins(0,0,0,0)
        main_layout.addWidget(display_area, 1) # Display area takes remaining space

        # Vues graphiques
        self.view1 = ImageViewer()
        self.view2 = ImageViewer()
        self.view_combined = ImageViewer()

        # Empiler les vues
        self.view_stack = QStackedWidget()

        # Widget for Side by Side view
        side_by_side_widget = QWidget()
        side_by_side_layout = QHBoxLayout(side_by_side_widget)
        side_by_side_layout.setContentsMargins(0,0,0,0)
        side_by_side_layout.setSpacing(1)
        side_by_side_layout.addWidget(self.view1)
        side_by_side_layout.addWidget(self.view2)
        self.view_stack.addWidget(side_by_side_widget) # Index 0 (Side by Side)

        # Widget for Combined view (all other modes)
        self.view_stack.addWidget(self.view_combined)   # Index 1 (Combined modes)

        display_layout.addWidget(self.view_stack) # Add stack to the display area layout

        # Connect view signals
        self.view1.viewChanged.connect(lambda: self.sync_views(source_view=self.view1))
        self.view2.viewChanged.connect(lambda: self.sync_views(source_view=self.view2))
        self.view1.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 1))
        self.view2.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 2))
        self.view_combined.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 0)) # 0 for combined view

        # --- Slider Item ---
        # Initialize with a default rect, will be updated when image loads
        self.interactive_slider = InteractiveSliderItem(QRectF(0, 0, 100, 100)) # Default rect
        self.interactive_slider.positionChanged.connect(self.on_interactive_slider_moved)
        self.interactive_slider.positionChanging.connect(self.on_interactive_slider_changing)
        self.interactive_slider.setVisible(False)
        self.view_combined.scene().addItem(self.interactive_slider)

        # --- Barre de Statut ---
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.lbl_status_coords = QLabel("Coords: (N/A)")
        self.lbl_status_rgb = QLabel("RGB: (N/A)")
        self.statusBar.addPermanentWidget(self.lbl_status_coords)
        spacer = QLabel(" | ") # Simple spacer
        self.statusBar.addPermanentWidget(spacer)
        self.statusBar.addPermanentWidget(self.lbl_status_rgb)


    # --- Fonctions Logiques ---

    def set_mode(self, mode):
        if self.current_mode != mode:
            print(f"Mode changed to: {mode}")
            self.current_mode = mode

            # Update visibility of mode-specific controls
            self.btn_switch_ab.setVisible(mode == "switch")
            self.interactive_slider.setVisible(mode == "slider")
            self.check_link_views.setEnabled(mode == "side_by_side") # Only enable linking for side-by-side

            # Update options stack index based on mode
            if mode == "opacity": self.options_stack.setCurrentIndex(1)
            elif mode == "difference": self.options_stack.setCurrentIndex(2)
            elif mode == "checkerboard": self.options_stack.setCurrentIndex(3)
            elif mode == "slider": self.options_stack.setCurrentIndex(4) # Use index 4 for slider (even if empty)
            else: self.options_stack.setCurrentIndex(0) # SideBySide, Switch, or others default to empty

            # Reset switch state if leaving switch mode
            if mode != "switch":
                self._switch_state_is_b = False
                self.btn_switch_ab.setText("Show Image B")

            self.update_display() # Update the main display area

    def clear_image(self, image_num):
        if image_num == 1:
            self.image_path1 = None
            self.pil_image1_orig = None
            self.qt_pixmap1_orig = None
            self.lbl_img1.setText("No Image A")
            self.view1.set_pixmap(QPixmap()) # Clear view
        else:
            self.image_path2 = None
            self.pil_image2_orig = None
            self.qt_pixmap2_orig = None
            self.lbl_img2.setText("No Image B")
            self.view2.set_pixmap(QPixmap()) # Clear view

        # Update display and metrics
        self.update_display()
        self.update_metrics_display(clear=True) # Clear metrics values
        self.update_compute_metrics_button_state()

    def on_opacity_changed(self, value):
        self.opacity_value = value / 100.0
        self.lbl_opacity_value.setText(f"{self.opacity_value:.2f}")
        if self.current_mode == "opacity": self.update_comparison_image()

    def on_diff_colormap_changed(self, cmap):
        self.diff_colormap = cmap
        if self.current_mode == "difference": self.update_comparison_image()

    def on_diff_threshold_changed(self, value): # New handler for threshold
        self.diff_threshold = value / 100.0
        self.lbl_diff_threshold_value.setText(f"{self.diff_threshold:.2f}")
        if self.current_mode == "difference": self.update_comparison_image()

    def on_checker_size_changed(self, value):
        self.checker_size = value
        self.lbl_checker_value.setText(str(value))
        if self.current_mode == "checkerboard": self.update_comparison_image()

    def on_link_views_toggled(self, checked):
        self.link_views_enabled = checked
        print(f"Link Views: {self.link_views_enabled}")
        if checked and self.current_mode == "side_by_side":
             # When enabling, sync view 2 to view 1's state
             self.sync_views(self.view1, force_sync=True)

    def on_interactive_slider_changing(self, position_ratio):
        if self.current_mode == "slider" and self._slider_pixmaps:
            self.fast_update_slider_image(position_ratio)

    def on_interactive_slider_moved(self, position_ratio):
        if self.current_mode == "slider":
            # Update with high quality render after dragging stops
            self.update_comparison_image()

    def toggle_switch_image(self):
        """ Toggles the image displayed in 'Switch A/B' mode. """
        if self.current_mode != "switch": return

        self._switch_state_is_b = not self._switch_state_is_b
        if self._switch_state_is_b:
            # Show B
            pixmap_to_show = self.display_pixmap2 if self.display_pixmap2 else QPixmap()
            self.view_combined.set_pixmap(pixmap_to_show)
            self.btn_switch_ab.setText("Show Image A")
            if not pixmap_to_show.isNull():
                 self.view_combined.setSceneRect(QRectF(pixmap_to_show.rect()))
            else:
                 self.view_combined.setSceneRect(QRectF())

        else:
            # Show A
            pixmap_to_show = self.display_pixmap1 if self.display_pixmap1 else QPixmap()
            self.view_combined.set_pixmap(pixmap_to_show)
            self.btn_switch_ab.setText("Show Image B")
            if not pixmap_to_show.isNull():
                 self.view_combined.setSceneRect(QRectF(pixmap_to_show.rect()))
            else:
                 self.view_combined.setSceneRect(QRectF())
        # No need to call update_comparison_image here, just swap the displayed pixmap


    def fast_update_slider_image(self, position_ratio):
        """ Optimized slider update using QPainter """
        if not self._slider_pixmaps: return
        pixmap1, pixmap2 = self._slider_pixmaps
        if pixmap1.isNull() or pixmap2.isNull(): return

        # Ensure result pixmap exists and has the correct size
        target_size = pixmap1.size()
        if not hasattr(self, '_result_pixmap') or self._result_pixmap.size() != target_size:
            self._result_pixmap = QPixmap(target_size)
            self._result_pixmap.fill(Qt.GlobalColor.transparent) # Fill with transparent

        painter = QPainter(self._result_pixmap)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source) # Overwrite previous content

        split_x = int(target_size.width() * position_ratio)

        # Draw left part (Image A)
        source_rect1 = QRectF(0, 0, split_x, target_size.height())
        target_rect1 = QRectF(0, 0, split_x, target_size.height())
        painter.drawPixmap(target_rect1, pixmap1, source_rect1)

        # Draw right part (Image B)
        if split_x < target_size.width():
            source_rect2 = QRectF(split_x, 0, target_size.width() - split_x, target_size.height())
            target_rect2 = QRectF(split_x, 0, target_size.width() - split_x, target_size.height())
            # Ensure pixmap2 is valid before drawing
            if not pixmap2.isNull() and pixmap2.size() == target_size:
                 painter.drawPixmap(target_rect2, pixmap2, source_rect2)
            # else: # Optional: fill the right side with a color if pixmap2 is missing/wrong size
            #    painter.fillRect(target_rect2, QColor(50, 50, 50))


        painter.end()

        # Update the view directly - bypass set_pixmap's fitInView logic
        self.view_combined.get_pixmap_item().setPixmap(self._result_pixmap)
        # Ensure scene rect matches the updated pixmap
        # self.view_combined.setSceneRect(QRectF(self._result_pixmap.rect())) # This might cause view jumps, maybe update only if size changes significantly


    def pil_to_qpixmap(self, pil_image):
        """ Converts PIL Image to QPixmap, handling modes. """
        if pil_image is None: return QPixmap()
        try:
            # Ensure RGB or RGBA for conversion
            if pil_image.mode == "L":
                pil_image = pil_image.convert("RGB") # Convert grayscale to RGB
            elif pil_image.mode == "P": # Palette images
                pil_image = pil_image.convert("RGBA" if 'transparency' in pil_image.info else "RGB")
            elif pil_image.mode not in ["RGB", "RGBA"]:
                 print(f"Warning: Converting PIL image from mode {pil_image.mode} to RGB.")
                 pil_image = pil_image.convert("RGB")


            if ImageQt:
                # Use ImageQt if available (usually handles formats well)
                qimage = ImageQt.ImageQt(pil_image)
                # Ensure it's a QImage before creating QPixmap
                if isinstance(qimage, QImage):
                    return QPixmap.fromImage(qimage)
                else:
                    # Fallback if ImageQt returns something unexpected
                    print("Warning: ImageQt did not return QImage. Using fallback.")
                    return QPixmap(qimage) # Try direct conversion
            else:
                # Fallback using raw bytes (less robust for formats)
                print("Warning: ImageQt not available, using fallback conversion.")
                if pil_image.mode == "RGB":
                    data = pil_image.tobytes("raw", "RGB")
                    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGB888)
                elif pil_image.mode == "RGBA":
                    data = pil_image.tobytes("raw", "RGBA")
                    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
                else: # Should not happen due to conversion above, but as safeguard
                    print(f"Error: Cannot convert mode {pil_image.mode} in fallback.")
                    return QPixmap()

                # Check if conversion was successful
                if qimage.isNull():
                     print("Error: Fallback QImage conversion resulted in null image.")
                     return QPixmap()

                return QPixmap.fromImage(qimage)

        except Exception as e:
            print(f"Error converting PIL to QPixmap: {e}")
            import traceback
            traceback.print_exc()
            return QPixmap()


    def load_image(self, image_num):
        filepath, _ = QFileDialog.getOpenFileName(
            self, f"Select Image {'A' if image_num == 1 else 'B'}", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;All Files (*)"
        )
        if not filepath: return

        try:
            img = Image.open(filepath)

            # Resize if necessary BEFORE conversion
            if max(img.width, img.height) > MAX_IMAGE_DIM_LOAD:
                 img.thumbnail((MAX_IMAGE_DIM_LOAD, MAX_IMAGE_DIM_LOAD), Image.Resampling.LANCZOS)
                 print(f"Image {image_num} resized to fit max dimension {MAX_IMAGE_DIM_LOAD}")

            # Convert to RGB/RGBA *after* potential resize
            # Prefer RGBA if original has alpha, otherwise RGB
            if img.mode == 'RGBA' or 'transparency' in img.info:
                 pil_img_conv = img.convert("RGBA")
            else:
                 pil_img_conv = img.convert("RGB")

            qt_pixmap = self.pil_to_qpixmap(pil_img_conv)
            if qt_pixmap.isNull():
                 raise ValueError("Failed to convert PIL image to QPixmap.")


            if image_num == 1:
                self.image_path1 = filepath
                self.pil_image1_orig = pil_img_conv
                self.qt_pixmap1_orig = qt_pixmap
                self.lbl_img1.setText(os.path.basename(filepath))
                view_to_reset = self.view1
            else: # image_num == 2
                self.image_path2 = filepath
                self.pil_image2_orig = pil_img_conv
                self.qt_pixmap2_orig = qt_pixmap
                self.lbl_img2.setText(os.path.basename(filepath))
                view_to_reset = self.view2

            print(f"Loaded Image {image_num}: {filepath} ({pil_img_conv.width}x{pil_img_conv.height}, Mode: {pil_img_conv.mode})")

            # Update display first, then reset the specific view
            self.update_display()
            view_to_reset.reset_view()
            # Also reset combined view if it's active and showing this image potentially
            if self.view_stack.currentIndex() == 1:
                 self.view_combined.reset_view()

            # Update metrics state
            self.update_metrics_display(clear=True) # Clear old metrics
            self.update_compute_metrics_button_state()


        except Exception as e:
            QMessageBox.critical(self, "Error Loading Image", f"Could not load image:\n{filepath}\n\nError: {e}")
            # Reset variables if loading failed
            self.clear_image(image_num) # Use clear_image to reset state


    def prepare_display_images(self):
        """
        Prepares PIL images and QPixmaps for the current mode.
        Handles resizing for comparison modes if dimensions differ.
        Returns (pil1, pil2) for comparison, and sets self.display_pixmap1/2.
        """
        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig

        # Default to original pixmaps
        self.display_pixmap1 = self.qt_pixmap1_orig if self.qt_pixmap1_orig else QPixmap()
        self.display_pixmap2 = self.qt_pixmap2_orig if self.qt_pixmap2_orig else QPixmap()

        # For combined modes, ensure images have the same dimensions for comparison logic
        is_combined_mode = self.current_mode not in ['side_by_side']

        if is_combined_mode and pil1 and pil2:
            if pil1.size != pil2.size:
                try:
                    print(f"Resizing Image B ({pil2.width}x{pil2.height}) to match Image A ({pil1.width}x{pil1.height}) for comparison.")
                    # Use LANCZOS for better quality resize
                    pil2_resized = pil2.resize(pil1.size, Image.Resampling.LANCZOS)
                    # Update the display pixmap for image 2
                    self.display_pixmap2 = self.pil_to_qpixmap(pil2_resized)
                    if self.display_pixmap2.isNull():
                         print("Warning: Resized pixmap 2 is null, using original.")
                         self.display_pixmap2 = self.qt_pixmap2_orig if self.qt_pixmap2_orig else QPixmap()
                         return pil1, pil2 # Return originals if resize failed
                    return pil1, pil2_resized # Return resized PIL image for comparison logic
                except Exception as e:
                    print(f"Error resizing Image 2: {e}. Using original sizes for comparison.")
                    # Fallback to original pixmaps if resize fails
                    self.display_pixmap2 = self.qt_pixmap2_orig if self.qt_pixmap2_orig else QPixmap()
                    return pil1, pil2 # Return original PIL images
            else:
                # Sizes match, return original PIL images
                return pil1, pil2
        elif is_combined_mode and pil1:
            # Only image 1 is loaded
            self.display_pixmap2 = QPixmap() # Ensure pixmap 2 is cleared
            return pil1, None
        elif is_combined_mode and pil2:
            # Only image 2 is loaded
            self.display_pixmap1 = QPixmap() # Ensure pixmap 1 is cleared
            # We need a reference size for combined modes. Let's use image 2's size.
            # The comparison logic should handle the case where pil1 is None.
            return None, pil2
        else: # Side-by-side mode or no images loaded for combined
             # Return original PIL images (can be None)
             return pil1, pil2


    def update_display(self):
        """ Updates the main display area based on the current mode and loaded images. """
        print(f"Updating display for mode: {self.current_mode}")
        # Prepare images (handles potential resizing for combined modes)
        pil1_comp, pil2_comp = self.prepare_display_images()

        if self.current_mode == "side_by_side":
            self.view_stack.setCurrentIndex(0) # Show side-by-side view (index 0)
            self.view1.set_pixmap(self.display_pixmap1)
            self.view2.set_pixmap(self.display_pixmap2)
            self.interactive_slider.setVisible(False) # Hide slider
            # Force sync if linking enabled and views might be out of sync
            if self.link_views_enabled:
                 QTimer.singleShot(0, lambda: self.sync_views(self.view1, force_sync=True)) # Sync after event loop processes potential resize/load

        else: # Combined modes (Slider, Opacity, Difference, Checkerboard, Switch)
            self.view_stack.setCurrentIndex(1) # Show combined view (index 1)
            self.interactive_slider.setVisible(self.current_mode == "slider")

            # Prepare pixmaps specifically for the fast slider update if needed
            if self.current_mode == "slider":
                self._prepare_slider_pixmaps(pil1_comp, pil2_comp)

            # Generate the comparison image (or select the base image for Switch)
            self.update_comparison_image(pil1_comp, pil2_comp)

            # Determine which pixmap to show initially in the combined view
            pixmap_to_show = QPixmap()
            if self.current_mode == "switch":
                 # Show A initially or if B is not loaded, otherwise show B if _switch_state_is_b is True
                 if self._switch_state_is_b and self.display_pixmap2 and not self.display_pixmap2.isNull():
                      pixmap_to_show = self.display_pixmap2
                 elif self.display_pixmap1 and not self.display_pixmap1.isNull():
                      pixmap_to_show = self.display_pixmap1
                 elif self.display_pixmap2 and not self.display_pixmap2.isNull(): # Fallback to B if A isn't loaded
                      pixmap_to_show = self.display_pixmap2

            elif self.comparison_pixmap and not self.comparison_pixmap.isNull():
                 pixmap_to_show = self.comparison_pixmap # Use generated comparison for other modes
            elif self.display_pixmap1 and not self.display_pixmap1.isNull():
                 pixmap_to_show = self.display_pixmap1 # Fallback to image A
            elif self.display_pixmap2 and not self.display_pixmap2.isNull():
                 pixmap_to_show = self.display_pixmap2 # Fallback to image B

            # Set the pixmap in the combined view
            self.view_combined.set_pixmap(pixmap_to_show)

            # Update scene rect and slider position/visibility
            if not pixmap_to_show.isNull():
                scene_rect = QRectF(pixmap_to_show.rect())
                self.view_combined.setSceneRect(scene_rect) # Update scene rect for combined view
                if self.current_mode == "slider":
                    self.interactive_slider.set_scene_rect(scene_rect) # Update slider's scene rect
                    # Trigger a redraw of the slider overlay after potential resize
                    self.on_interactive_slider_moved(self.interactive_slider.get_position_ratio())
            else:
                 # Clear scene if no image is displayed
                 self.view_combined.setSceneRect(QRectF())
                 if self.current_mode == "slider":
                      self.interactive_slider.set_scene_rect(QRectF())


    def _prepare_slider_pixmaps(self, pil1_comp, pil2_comp):
        """ Prepares and caches the *display* pixmaps for fast slider updates. """
        # We need the pixmaps that correspond to pil1_comp and pil2_comp,
        # which are stored in self.display_pixmap1 and self.display_pixmap2
        # after prepare_display_images() is called.
        if self.display_pixmap1 and not self.display_pixmap1.isNull() and \
           self.display_pixmap2 and not self.display_pixmap2.isNull():
            # Ensure they are the same size for slider logic
            if self.display_pixmap1.size() == self.display_pixmap2.size():
                self._slider_pixmaps = (self.display_pixmap1, self.display_pixmap2)
                print(f"Slider pixmaps prepared: Size {self.display_pixmap1.size()}")
            else:
                print("Warning: Slider mode requires images of the same size. Resizing failed or skipped.")
                self._slider_pixmaps = None # Invalidate cache if sizes don't match
        else:
            self._slider_pixmaps = None # Invalidate if one or both images are missing


    def update_comparison_image(self, pil1_comp=None, pil2_comp=None):
        """ Generates the result PIL image based on the current comparison mode. """
        # If PIL images aren't provided, get them (handles resizing)
        if pil1_comp is None or pil2_comp is None:
             # We need both potentially resized images if available
             _pil1, _pil2 = self.prepare_display_images()
             # Use the potentially resized images if they exist
             pil1_comp = _pil1 if _pil1 else None
             pil2_comp = _pil2 if _pil2 else None


        pil_result = None
        mode = self.current_mode

        # Handle modes that require both images
        if pil1_comp and pil2_comp:
            # Ensure modes are compatible (RGB/RGBA) before operations
            try:
                # Convert to compatible modes (prefer RGB for blend/diff, RGBA for paste)
                if mode == "opacity":
                    img1_blend = pil1_comp.convert("RGB")
                    img2_blend = pil2_comp.convert("RGB")
                    pil_result = Image.blend(img1_blend, img2_blend, alpha=self.opacity_value)
                elif mode == "difference":
                    # Use numpy for difference calculation
                    np1 = np.array(pil1_comp.convert("RGB")).astype(float)
                    np2 = np.array(pil2_comp.convert("RGB")).astype(float)
                    # Calculate absolute difference per pixel, then mean across channels
                    diff_np = np.abs(np1 - np2).mean(axis=2)

                    # Apply threshold
                    max_diff = np.max(diff_np) if np.any(diff_np) else 1.0 # Avoid division by zero
                    threshold_val = self.diff_threshold * max_diff
                    diff_np[diff_np < threshold_val] = 0.0

                    # Normalize the thresholded difference
                    max_remaining_diff = np.max(diff_np) if np.any(diff_np) else 1.0
                    if max_remaining_diff > 0:
                         diff_norm = (diff_np / max_remaining_diff * 255).astype(np.uint8)
                    else:
                         diff_norm = np.zeros(diff_np.shape, dtype=np.uint8)

                    # Apply colormap
                    if self.diff_colormap == "grayscale":
                        pil_result = Image.fromarray(diff_norm, 'L').convert('RGB')
                    elif self.diff_colormap == "thermal":
                        # Simple thermal: Red = high diff, Blue = low diff
                        r = diff_norm
                        g = np.zeros_like(diff_norm) # No green channel
                        b = 255 - diff_norm
                        colored_diff_np = np.stack((r, g, b), axis=-1)
                        pil_result = Image.fromarray(colored_diff_np, 'RGB')
                    elif self.diff_colormap == "inverted":
                        pil_result = ImageOps.invert(Image.fromarray(diff_norm, 'L')).convert('RGB')

                elif mode == "checkerboard":
                    size = self.checker_size
                    w, h = pil1_comp.size
                    # Create RGBA checker image to handle potential transparency in source images
                    checker_img = Image.new('RGBA', (w, h))
                    img1_rgba = pil1_comp.convert("RGBA") # Ensure RGBA for pasting
                    img2_rgba = pil2_comp.convert("RGBA") # Ensure RGBA for pasting
                    use_img1 = True
                    for y in range(0, h, size):
                        row_start_img1 = use_img1
                        for x in range(0, w, size):
                            box = (x, y, min(x + size, w), min(y + size, h))
                            crop_img = img1_rgba if use_img1 else img2_rgba
                            region = crop_img.crop(box)
                            checker_img.paste(region, box) # Paste RGBA region
                            use_img1 = not use_img1
                        use_img1 = not row_start_img1
                    pil_result = checker_img.convert("RGB") # Convert final to RGB if needed

                elif mode == "slider":
                    # High-quality render for when slider stops moving
                    slider_ratio = self.interactive_slider.get_position_ratio()
                    width, height = pil1_comp.size
                    split_x = int(width * slider_ratio)

                    # Start with image A
                    pil_result = pil1_comp.copy().convert("RGBA") # Work with RGBA copy

                    if split_x < width:
                        # Crop the right part of image B
                        img2_part = pil2_comp.convert("RGBA").crop((split_x, 0, width, height))
                        # Paste using alpha compositing
                        pil_result.paste(img2_part, (split_x, 0), img2_part) # Use img2_part as mask for transparency

                    pil_result = pil_result.convert("RGB") # Convert final to RGB

            except Exception as e:
                print(f"Error generating comparison image for mode '{mode}': {e}")
                import traceback
                traceback.print_exc()
                # Fallback to showing image A if error occurs
                pil_result = pil1_comp

        # Handle modes requiring only one image or fallback
        if pil_result is None:
            if mode == "switch":
                 # The actual display is handled in update_display/toggle_switch_image
                 # We just need a placeholder pixmap if needed, default to A
                 pil_result = pil1_comp if pil1_comp else pil2_comp # Show A or B if one exists
            elif pil1_comp:
                 pil_result = pil1_comp # Fallback to image A
            elif pil2_comp:
                 pil_result = pil2_comp # Fallback to image B


        # --- Convert final PIL result to QPixmap ---
        if pil_result:
            self.comparison_pixmap = self.pil_to_qpixmap(pil_result)
            if self.comparison_pixmap.isNull():
                 print("Error: Resulting comparison pixmap is null.")
                 # Fallback pixmap if conversion failed
                 self.comparison_pixmap = self.display_pixmap1 if self.display_pixmap1 and not self.display_pixmap1.isNull() else QPixmap()
        else:
            self.comparison_pixmap = QPixmap() # No result, empty pixmap

        # Note: The actual display of comparison_pixmap happens in update_display


    def reset_all_views(self):
        print("Resetting views")
        if self.current_mode == "side_by_side":
            self.view1.reset_view()
            self.view2.reset_view()
            # Ensure sync after reset if linked
            if self.link_views_enabled:
                 QTimer.singleShot(0, lambda: self.sync_views(self.view1, force_sync=True))
        else:
            self.view_combined.reset_view()


    def sync_views(self, source_view, force_sync=False):
        if self._is_updating_views: return # Prevent recursion
        if not self.link_views_enabled and not force_sync: return
        if self.current_mode != "side_by_side": return # Only sync in side-by-side

        self._is_updating_views = True
        print(f"Syncing views (source: {'View1' if source_view == self.view1 else 'View2'})")

        target_view = self.view2 if source_view == self.view1 else self.view1

        if target_view:
            # Sync transform (includes zoom and center point)
            source_transform = source_view.get_transform() # Use the getter
            target_view.set_transform(source_transform) # Use the setter

            # Sync scrollbars explicitly for precise position matching
            h_val = source_view.horizontalScrollBar().value()
            v_val = source_view.verticalScrollBar().value()
            h_max = source_view.horizontalScrollBar().maximum()
            v_max = source_view.verticalScrollBar().maximum()

            # Set maximum first to ensure value is within range
            if target_view.horizontalScrollBar().maximum() != h_max:
                target_view.horizontalScrollBar().setMaximum(h_max)
            target_view.horizontalScrollBar().setValue(h_val)

            if target_view.verticalScrollBar().maximum() != v_max:
                target_view.verticalScrollBar().setMaximum(v_max)
            target_view.verticalScrollBar().setValue(v_val)

        # Use QTimer to release the lock after the event loop has processed updates
        QTimer.singleShot(0, self._release_sync_lock)

    def _release_sync_lock(self):
        self._is_updating_views = False
        # print("View sync lock released.")


    def update_status_bar(self, scene_pos, view_index):
        """ Updates status bar with coordinates and pixel values. """
        img_coords, pixel_value = None, "N/A"
        img_w, img_h = 0, 0
        source_pil_image = None # The original PIL image for pixel value lookup

        active_view = None
        pixmap_item = None

        # Determine the active view and corresponding pixmap item/PIL image
        if view_index == 1 and self.current_mode == "side_by_side":
            active_view = self.view1
            pixmap_item = self.view1.get_pixmap_item()
            source_pil_image = self.pil_image1_orig
        elif view_index == 2 and self.current_mode == "side_by_side":
            active_view = self.view2
            pixmap_item = self.view2.get_pixmap_item()
            source_pil_image = self.pil_image2_orig
        elif view_index == 0 and self.current_mode != "side_by_side":
            active_view = self.view_combined
            pixmap_item = self.view_combined.get_pixmap_item()
            # For combined view, determine the relevant source image based on mode/state
            if self.current_mode == "switch":
                 source_pil_image = self.pil_image2_orig if self._switch_state_is_b else self.pil_image1_orig
            elif self.current_mode == "slider":
                 # Determine which image is under the cursor based on slider position
                 if pixmap_item and not pixmap_item.pixmap().isNull():
                      item_pos_temp = pixmap_item.mapFromScene(scene_pos)
                      slider_ratio = self.interactive_slider.get_position_ratio()
                      split_x = int(pixmap_item.pixmap().width() * slider_ratio)
                      if item_pos_temp.x() < split_x:
                           source_pil_image = self.pil_image1_orig
                      else:
                           source_pil_image = self.pil_image2_orig # Assumes B is resized to A's coords
            else:
                 # For other modes (Opacity, Diff, Checker), coords usually relate to Image A's frame
                 source_pil_image = self.pil_image1_orig


        if active_view and pixmap_item and not pixmap_item.pixmap().isNull():
            pixmap = pixmap_item.pixmap()
            img_w, img_h = pixmap.width(), pixmap.height()

            # Map scene coordinates to item's coordinate system (image pixels)
            item_pos = pixmap_item.mapFromScene(scene_pos)
            x, y = int(item_pos.x()), int(item_pos.y())

            if 0 <= x < img_w and 0 <= y < img_h:
                img_coords = (x, y)
                try:
                    # Try reading pixel directly from the displayed QPixmap's QImage
                    qimg_to_read = pixmap.toImage()
                    if not qimg_to_read.isNull() and qimg_to_read.valid(x, y):
                        color = QColor(qimg_to_read.pixel(x, y))
                        # Format based on whether the source image had alpha
                        has_alpha = qimg_to_read.hasAlphaChannel() # source_pil_image and source_pil_image.mode == 'RGBA' if source_pil_image else False
                        if has_alpha:
                             pixel_value = f"({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
                        else:
                             pixel_value = f"({color.red()}, {color.green()}, {color.blue()})"
                    else:
                         # Fallback to reading from original PIL image if QImage read fails
                         # This gives the *original* pixel value, not necessarily the displayed one (e.g., in diff mode)
                         if source_pil_image:
                              pil_w, pil_h = source_pil_image.size
                              # Need to potentially scale coordinates if displayed pixmap was resized
                              # For simplicity, assume coords match original if view matches source_pil_image index
                              # This might be inaccurate if B was resized for combined view.
                              read_x, read_y = x, y
                              if 0 <= read_x < pil_w and 0 <= read_y < pil_h:
                                   pv = source_pil_image.getpixel((read_x, read_y))
                                   if isinstance(pv, (int, float)): pixel_value = f"({pv}, {pv}, {pv})" # Grayscale
                                   elif len(pv) == 4: pixel_value = f"({pv[0]}, {pv[1]}, {pv[2]}, {pv[3]})" # RGBA
                                   elif len(pv) == 3: pixel_value = f"({pv[0]}, {pv[1]}, {pv[2]})" # RGB
                                   else: pixel_value = "Invalid Format"
                              else: pixel_value = "Out (PIL)"
                         else: pixel_value = "No Source PIL"

                except Exception as e:
                    print(f"Error reading pixel value: {e}")
                    pixel_value = "Error"
            else:
                pixel_value = "Out" # Outside image bounds

        # Update status bar labels
        coords_text = f"Coords: ({img_coords[0]}, {img_coords[1]}) / ({img_w}x{img_h})" if img_coords else f"Coords: (N/A) / ({img_w}x{img_h})" if img_w > 0 else "Coords: (N/A)"
        rgb_text = f"Pixel: {pixel_value}" # Changed label to Pixel:

        self.lbl_status_coords.setText(coords_text)
        self.lbl_status_rgb.setText(rgb_text)

    # --- Metrics Functions ---
    def update_compute_metrics_button_state(self):
        """ Enables or disables the 'Compute Metrics' button based on image availability and library status. """
        enabled = (self.pil_image1_orig is not None and
                   self.pil_image2_orig is not None and
                   SKIMAGE_AVAILABLE)
        self.btn_compute_metrics.setEnabled(enabled)

    def update_metrics_display(self, mse=None, psnr=None, ssim=None, clear=False):
        """ Updates the metric labels in the UI. """
        if clear or not SKIMAGE_AVAILABLE:
            self.val_mse.setText("N/A")
            self.val_psnr.setText("N/A")
            self.val_ssim.setText("N/A")
            return

        self.val_mse.setText(f"{mse:.4f}" if mse is not None else "Error")
        self.val_psnr.setText(f"{psnr:.4f} dB" if psnr is not None and psnr != float('inf') else "Inf dB" if psnr == float('inf') else "Error")
        self.val_ssim.setText(f"{ssim:.4f}" if ssim is not None else "Error")


    def calculate_and_display_metrics(self):
        """ Calculates MSE, PSNR, SSIM and updates the display. """
        if not SKIMAGE_AVAILABLE:
            self.update_metrics_display(clear=True)
            QMessageBox.warning(self, "Metrics Unavailable", "Scikit-image library not found. Cannot compute metrics.")
            return

        if not self.pil_image1_orig or not self.pil_image2_orig:
            self.update_metrics_display(clear=True)
            QMessageBox.warning(self, "Metrics Error", "Both Image A and Image B must be loaded to compute metrics.")
            return

        try:
            img1 = self.pil_image1_orig
            img2 = self.pil_image2_orig

            # Ensure images have the same size for metrics
            if img1.size != img2.size:
                print(f"Metrics: Resizing Image B ({img2.width}x{img2.height}) to match Image A ({img1.width}x{img1.height}) for calculation.")
                img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)

            # Convert images to numpy arrays (RGB)
            # Use uint8 for calculations as expected by skimage metrics
            np1 = np.array(img1.convert("RGB"), dtype=np.uint8)
            np2 = np.array(img2.convert("RGB"), dtype=np.uint8)

            # Calculate Metrics
            data_range = 255 # For uint8 images

            # MSE
            mse_val = mean_squared_error(np1, np2)

            # PSNR
            # Handle potential zero MSE (identical images)
            if mse_val == 0:
                psnr_val = float('inf')
            else:
                psnr_val = peak_signal_noise_ratio(np1, np2, data_range=data_range)

            # SSIM
            # SSIM is often calculated on grayscale, but can work on multichannel
            # Specify channel_axis for multichannel images
            # Convert to grayscale for a common SSIM measure:
            # np1_gray = np.array(img1.convert("L"), dtype=np.uint8)
            # np2_gray = np.array(img2.convert("L"), dtype=np.uint8)
            # ssim_val = structural_similarity(np1_gray, np2_gray, data_range=data_range)
            # Or calculate on RGB (set channel_axis)
            ssim_val = structural_similarity(np1, np2, data_range=data_range, channel_axis=-1) # Use channel_axis for RGB


            print(f"Metrics Computed: MSE={mse_val:.4f}, PSNR={psnr_val:.4f}, SSIM={ssim_val:.4f}")
            self.update_metrics_display(mse=mse_val, psnr=psnr_val, ssim=ssim_val)

        except Exception as e:
            print(f"Error calculating metrics: {e}")
            import traceback
            traceback.print_exc()
            self.update_metrics_display(clear=True) # Clear display on error
            QMessageBox.critical(self, "Metrics Calculation Error", f"Could not compute metrics:\n{e}")


# --- Point d'Entrée ---
if __name__ == "__main__":
    # High DPI scaling attributes
    if hasattr(QtCore.Qt, 'ApplicationAttribute'):
         QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
         QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    elif hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'): # Fallback for older Qt versions?
         QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
         QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    window = ImageComparerApp()
    window.show()
    sys.exit(app.exec())
