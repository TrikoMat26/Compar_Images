# --- START OF FILE image_compare.py ---

import sys
import os
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal

try:
    from PIL import Image, ImageQt
except ImportError:
    print("Warning: Pillow not found. Please install it if needed.")
    ImageQt = None
    Image = None # Make sure Image is None if Pillow is not found

# --- OpenCV Import ---
try:
    import cv2
    OPENCV_AVAILABLE = True
    print("OpenCV found.")
except ImportError:
    print("Warning: OpenCV (cv2) not found. Defect detection will be disabled.")
    OPENCV_AVAILABLE = False
    cv2 = None

# --- Configuration ---
MAX_IMAGE_DIM_LOAD = 3000
DEFAULT_AB_SWITCH_INTERVAL = 500
MIN_AB_SWITCH_INTERVAL = 100
MAX_AB_SWITCH_INTERVAL = 2000
# --- Defect Detection Configuration ---
DEFAULT_DEFECT_THRESHOLD = 30
DEFAULT_MORPH_KERNEL_SIZE = (3, 3)
DEFAULT_MORPH_ITERATIONS = 2


# -------------------------------------------------------------
# 1) DraggablePixmapItem (Keep as is)
# -------------------------------------------------------------
class DraggablePixmapItem(QtWidgets.QGraphicsPixmapItem):
    """
    QGraphicsPixmapItem déplaçable : gère le drag (souris) et
    appelle move_pixmap_item du contrôleur.
    """
    def __init__(self, controller=None, item_id=1, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.item_id = item_id
        self._dragging = False
        self._last_mouse_pos = QtCore.QPointF()
        self._accumulated_delta = QtCore.QPointF()  # Pour accumuler les petits mouvements

        # Autoriser la sélection + mouvements
        self.setFlags(
            QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable
        )
        self.setAcceptHoverEvents(True)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_mouse_pos = event.scenePos()
            event.accept()
        super().mousePressEvent(event)
    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if self._dragging and self.controller:
            current_pos = event.scenePos()
            delta = current_pos - self._last_mouse_pos
            self._last_mouse_pos = current_pos

            # Accumuler les deltas
            self._accumulated_delta += delta

            # Si le mouvement accumulé est significatif, appliquer le déplacement
            if abs(self._accumulated_delta.x()) >= 1.0 or abs(self._accumulated_delta.y()) >= 1.0:
                self.controller.move_pixmap_item(self.item_id,
                                              self._accumulated_delta.x(),
                                              self._accumulated_delta.y())
                self._accumulated_delta = QtCore.QPointF()  # Réinitialiser l'accumulation

            event.accept()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = False
            # Appliquer tout mouvement restant accumulé
            if not self._accumulated_delta.isNull() and self.controller:
                self.controller.move_pixmap_item(self.item_id,
                                              self._accumulated_delta.x(),
                                              self._accumulated_delta.y())
                self._accumulated_delta = QtCore.QPointF()
            event.accept()
        super().mouseReleaseEvent(event)


# -------------------------------------------------------------
# 2) Masqué ou non (pour le slider) (Keep as is)
# -------------------------------------------------------------
class MaskedOrFullPixmapItem(DraggablePixmapItem):
    """
    - _use_mask = True => mode Slider (montre la portion gauche ou droite selon ratio).
    - _use_mask = False => affiche l'image complète (mode A/B Switch).
    - ratio + is_left => déterminent la coupe (partie gauche ou droite).
    """
    def __init__(self, controller=None, item_id=1, is_left=True, parent=None):
        super().__init__(controller=controller, item_id=item_id, parent=parent)
        self._use_mask = False
        self._ratio = 0.5
        self._is_left = is_left

    def set_use_mask(self, use_mask: bool):
        self._use_mask = use_mask
        self.update()

    def set_slider_ratio(self, ratio: float):
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paint(self, painter: QtGui.QPainter, option, widget=None):
        pm = self.pixmap()
        if pm.isNull():
            return
        w = pm.width()
        h = pm.height()
        if w <= 0 or h <= 0:
            return

        if not self._use_mask:
            # Pas de masquage => on dessine tout
            painter.drawPixmap(0, 0, pm)
            return

        # Mode masqué => couper selon ratio (moitié gauche/droite)
        split_x = int(self._ratio * w)
        if self._is_left:
            source_rect = QtCore.QRect(0, 0, split_x, h)
            target_rect = QtCore.QRectF(0, 0, split_x, h)
        else:
            source_rect = QtCore.QRect(split_x, 0, w - split_x, h)
            target_rect = QtCore.QRectF(split_x, 0, w - split_x, h)

        if source_rect.width() > 0:
            painter.drawPixmap(target_rect, pm, source_rect)


# -------------------------------------------------------------
# 3) InteractiveSliderItem (barre rouge) (Keep as is)
# -------------------------------------------------------------
class InteractiveSliderItem(QtWidgets.QGraphicsLineItem):
    class Signals(QtCore.QObject):
        positionChanged = Signal(float)

    def __init__(self, scene_rect: QtCore.QRectF, parent=None):
        super().__init__(parent)
        self.scene_rect = scene_rect
        self._position = 0.5
        self.signals = self.Signals()
        self.positionChanged = self.signals.positionChanged
        self._is_dragging = False

        pen = QtGui.QPen(QtCore.Qt.GlobalColor.red, 2, QtCore.Qt.PenStyle.SolidLine)
        self.setPen(pen)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        self.setPos(QtCore.QPointF(0, 0))
        self.update_line_geometry()
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._is_dragging = True
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if self._is_dragging:
            sx = event.scenePos().x()
            min_x = self.scene_rect.left()
            max_x = self.scene_rect.right()
            if max_x < min_x:
                max_x = min_x
            constrained_x = max(min_x, min(sx, max_x))
            w = self.scene_rect.width()
            new_ratio = (constrained_x - min_x)/w if w>0 else 0.5
            if not np.isclose(new_ratio, self._position):
                self._position = new_ratio
                self.update_line_geometry()
                self.positionChanged.emit(self._position)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            event.accept()
        super().mouseReleaseEvent(event)

    def update_line_geometry(self):
        x = self.scene_rect.left() + self._position*self.scene_rect.width()
        self.setLine(x, self.scene_rect.top(), x, self.scene_rect.bottom())

    def set_scene_rect(self, rect: QtCore.QRectF):
        self.scene_rect = rect
        self.update_line_geometry()

    def set_position_ratio(self, ratio: float):
        ratio = max(0.0, min(1.0, ratio))
        if not np.isclose(ratio, self._position):
            self._position = ratio
            self.update_line_geometry()

    def get_position_ratio(self):
        return self._position

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QtCore.QPointF(0,0)
        return super().itemChange(change, value)


# -------------------------------------------------------------
# 4) ImageViewer (Keep as is, but update methods using it later)
# -------------------------------------------------------------
class ImageViewer(QtWidgets.QGraphicsView):
    viewChanged = Signal()
    mouseMoved = Signal(QtCore.QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem() # This is the standard item
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)

        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(70, 70, 70)))
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        # self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag) # We manage drag manually now

        self._zoom = 1.0
        self._panning = False
        self._last_pan_point = QtCore.QPoint()
        self.setMouseTracking(True)

    def set_pixmap(self, pixmap: QtGui.QPixmap):
        if self._pixmap_item:
            current_transform = self.transform() # Save transform before changing pixmap
            was_empty = self._pixmap_item.pixmap().isNull()

            if pixmap and not pixmap.isNull():
                self._pixmap_item.setPixmap(pixmap)
                # Important: Update scene rect based on the *new* pixmap
                self._scene.setSceneRect(QtCore.QRectF(pixmap.rect()))
                # Adjust view: Fit if it was empty, otherwise restore transform
                if was_empty or self._zoom < 0.01 : # Also reset if zoom is near zero
                     self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                     self._zoom = self.transform().m11() # Update zoom after fitInView
                else:
                    # Restore previous transform to keep zoom/pan state
                    self.setTransform(current_transform)

            else: # Clear pixmap
                self._pixmap_item.setPixmap(QtGui.QPixmap())
                self._scene.setSceneRect(QtCore.QRectF()) # Reset scene rect if empty

            # Emit viewChanged *after* potential transform changes
            self.viewChanged.emit()


    def get_pixmap_item(self):
        """Returns the standard QGraphicsPixmapItem used by this view."""
        return self._pixmap_item

    # Keep wheelEvent, mousePressEvent, mouseMoveEvent, mouseReleaseEvent as they are
    def wheelEvent(self, event: QtGui.QWheelEvent):
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
            self._zoom *= zoom_factor
        else:
            self.scale(1/zoom_factor, 1/zoom_factor)
            self._zoom /= zoom_factor
        self.viewChanged.emit()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        # Only allow panning if the click is not on an interactive item
        # (like MaskedOrFullPixmapItem or InteractiveSliderItem)
        item_under_mouse = self.itemAt(event.position().toPoint())
        is_background_click = (item_under_mouse is None)
        is_standard_pixmap_click = (item_under_mouse == self._pixmap_item)

        if event.button() == QtCore.Qt.MouseButton.LeftButton and (is_background_click or is_standard_pixmap_click):
            self._panning = True
            self._last_pan_point = event.position().toPoint()
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            event.accept() # Accept the event so items below don't get it
        else:
            # If clicking on another item, let the item handle it
            self._panning = False
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor) # Reset cursor
            super().mousePressEvent(event) # Pass event down


    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        scene_pos = self.mapToScene(event.position().toPoint())
        self.mouseMoved.emit(scene_pos) # Emit mouse position regardless of panning

        if self._panning:
            delta = event.position().toPoint() - self._last_pan_point
            self._last_pan_point = event.position().toPoint()
            # Use scrollbars to pan
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.viewChanged.emit() # Panning changes the view
            event.accept()
        else:
             super().mouseMoveEvent(event) # Pass event down

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._panning:
                self._panning = False
                self.setCursor(QtCore.Qt.CursorShape.ArrowCursor) # Or OpenHandCursor if preferred
                event.accept()
            else:
                 super().mouseReleaseEvent(event) # Pass event down
        else:
             super().mouseReleaseEvent(event) # Pass event down for other buttons

    def reset_view(self):
        # Determine the primary item to fit in view
        target_item = None

        # Prioritize items added specifically for combined modes if they are visible
        scene_items = self.scene().items()
        visible_draggable_items = [item for item in scene_items if isinstance(item, DraggablePixmapItem) and item.isVisible()]

        if visible_draggable_items:
             # If multiple draggable items, create a bounding box around them
             bounding_rect = QtCore.QRectF()
             for item in visible_draggable_items:
                 bounding_rect = bounding_rect.united(item.sceneBoundingRect())
             if not bounding_rect.isEmpty():
                 self.fitInView(bounding_rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                 self._zoom = self.transform().m11()
                 self.viewChanged.emit()
                 return # Exit after fitting combined items

        # If no specific items visible, try the standard pixmap item
        elif self._pixmap_item and self._pixmap_item.isVisible() and not self._pixmap_item.pixmap().isNull():
            target_item = self._pixmap_item

        # Fit the target item or the entire scene if no specific item
        if target_item:
            self.fitInView(target_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        else:
            # Fallback: fit whatever is in the scene
            brect = self._scene.itemsBoundingRect()
            if not brect.isEmpty():
                self.fitInView(brect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            else:
                # If scene is truly empty, reset transform manually
                 self.setTransform(QtGui.QTransform()) # Reset to identity transform

        self._zoom = self.transform().m11() # Update zoom factor
        self.viewChanged.emit()


    def get_transform(self):
        return self.transform()

    def set_transform(self, transform: QtGui.QTransform):
        super().setTransform(transform)
        self._zoom = self.transform().m11()
        # No viewChanged emit here, let the caller decide (e.g., sync_views)


# -------------------------------------------------------------
# 5) Classe Principale (Application) - Modifications needed
# -------------------------------------------------------------
class ImageComparerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Comparer with Defect Detection") # Updated title
        self.setGeometry(100, 100, 1200, 700)

        # Etat (Keep existing state variables)
        self.image_path1 = None
        self.image_path2 = None
        self.pil_image1_orig = None
        self.pil_image2_orig = None
        self.qt_pixmap1_orig = None
        self.qt_pixmap2_orig = None
        self.display_pixmap1 = None
        self.display_pixmap2 = None
        self.current_mode = "side_by_side"
        self.link_views_enabled = True
        self._is_updating_views = False
        self._ab_recalage_actif = False # State for A/B adjustment

        # Options de redimensionnement (Keep as is)
        self.size_adjust_mode = "resize2to1"
        self.size_adjust_options = {
            "resize2to1": "Redimensionner Image 2 → Image 1",
            "resize1to2": "Redimensionner Image 1 → Image 2",
            "resizeboth": "Redimensionner les deux (taille max)",
            "original": "Conserver tailles originales",
            "proportional": "Adapter proportionnellement"
        }

        # Timer A/B (Keep as is)
        self.ab_timer = QtCore.QTimer(self)
        self.ab_timer.timeout.connect(self.switch_ab_image)
        self.ab_switch_interval = DEFAULT_AB_SWITCH_INTERVAL
        self.ab_showing_image1 = True

        # Offsets (Keep as is)
        self._offset_x = 0
        self._offset_y = 0
        self._slider_offset_x = 0.0
        self._slider_offset_y = 0.0

        # Defect Detection Parameters
        self.defect_threshold = DEFAULT_DEFECT_THRESHOLD
        self.morph_kernel_size = DEFAULT_MORPH_KERNEL_SIZE
        self.morph_iterations = DEFAULT_MORPH_ITERATIONS

        self.setup_ui()
        self.update_controls_state() # Initial state update for buttons etc.
        self.update_display()


    def setup_ui(self):
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QVBoxLayout(main_widget)

        control_panel = QtWidgets.QFrame()
        control_panel.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        control_layout = QtWidgets.QHBoxLayout(control_panel)
        main_layout.addWidget(control_panel)

        # --- Chargement Group (Keep as is) ---
        load_group = QtWidgets.QWidget()
        load_layout = QtWidgets.QVBoxLayout(load_group)
        btn_load1 = QtWidgets.QPushButton("Load Image 1 (Ref)") # Clarify role
        btn_load1.clicked.connect(lambda: self.load_image(1))
        self.lbl_img1 = QtWidgets.QLabel("No Reference Image")
        self.lbl_img1.setWordWrap(True)

        btn_load2 = QtWidgets.QPushButton("Load Image 2 (Test)") # Clarify role
        btn_load2.clicked.connect(lambda: self.load_image(2))
        self.lbl_img2 = QtWidgets.QLabel("No Test Image")
        self.lbl_img2.setWordWrap(True)

        load_layout.addWidget(btn_load1)
        load_layout.addWidget(self.lbl_img1)
        load_layout.addStretch()
        load_layout.addWidget(btn_load2)
        load_layout.addWidget(self.lbl_img2)
        control_layout.addWidget(load_group)

        # --- Modes Group (Keep as is) ---
        mode_group = QtWidgets.QFrame()
        mode_group.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        mode_layout = QtWidgets.QGridLayout(mode_group)
        control_layout.addWidget(mode_group, 1) # Stretch factor 1

        mode_label = QtWidgets.QLabel("<b>Comparison Mode:</b>")
        mode_layout.addWidget(mode_label, 0, 0, 1, 3)
        self.radio_side = QtWidgets.QRadioButton("Side by Side")
        self.radio_side.setChecked(True)
        self.radio_side.toggled.connect(lambda c: self.set_mode("side_by_side") if c else None)
        mode_layout.addWidget(self.radio_side, 1, 0)

        self.radio_slider = QtWidgets.QRadioButton("Slider")
        self.radio_slider.toggled.connect(lambda c: self.set_mode("slider") if c else None)
        mode_layout.addWidget(self.radio_slider, 1, 1)

        self.radio_ab_switch = QtWidgets.QRadioButton("A/B Switch")
        self.radio_ab_switch.toggled.connect(lambda c: self.set_mode("ab_switch") if c else None)
        mode_layout.addWidget(self.radio_ab_switch, 1, 2)

        self.options_stack = QtWidgets.QStackedWidget()
        mode_layout.addWidget(self.options_stack, 3, 0, 1, 3)
        self.options_stack.addWidget(QtWidgets.QWidget())  # Page Vide (index 0)

        # Page A/B switch (Keep as is)
        ab_switch_widget = QtWidgets.QWidget()
        ab_switch_layout = QtWidgets.QHBoxLayout(ab_switch_widget)
        ab_switch_layout.addWidget(QtWidgets.QLabel("Switch Speed (ms):"))
        self.slider_ab_speed = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_ab_speed.setRange(MIN_AB_SWITCH_INTERVAL, MAX_AB_SWITCH_INTERVAL)
        self.slider_ab_speed.setValue(self.ab_switch_interval)
        self.slider_ab_speed.valueChanged.connect(self.on_ab_speed_changed)
        ab_switch_layout.addWidget(self.slider_ab_speed)
        self.lbl_ab_speed_value = QtWidgets.QLabel(str(self.ab_switch_interval))
        ab_switch_layout.addWidget(self.lbl_ab_speed_value)
        self.options_stack.addWidget(ab_switch_widget) # Index 1

        # --- Size Adjustment Group (Keep as is) ---
        adjust_group = QtWidgets.QWidget()
        adjust_layout = QtWidgets.QVBoxLayout(adjust_group)
        adjust_label = QtWidgets.QLabel("<b>Size Adjustment:</b>") # English label
        adjust_layout.addWidget(adjust_label)

        self.combo_size_adjust = QtWidgets.QComboBox()
        for key, label in self.size_adjust_options.items():
            self.combo_size_adjust.addItem(label, key)
        self.combo_size_adjust.setCurrentText(self.size_adjust_options[self.size_adjust_mode])
        self.combo_size_adjust.currentIndexChanged.connect(self.on_size_adjust_changed)
        adjust_layout.addWidget(self.combo_size_adjust)
        adjust_layout.addStretch() # Push combo box up
        control_layout.addWidget(adjust_group)

        # --- View Options & Defect Detection Group (Modified) ---
        view_defect_group = QtWidgets.QFrame()
        view_defect_group.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        view_defect_layout = QtWidgets.QVBoxLayout(view_defect_group)
        control_layout.addWidget(view_defect_group) # Add this new group

        # View controls
        view_options_label = QtWidgets.QLabel("<b>View Options:</b>")
        view_defect_layout.addWidget(view_options_label)
        self.check_link_views = QtWidgets.QCheckBox("Link Views / Sync Drag") # Clarify label
        self.check_link_views.setChecked(self.link_views_enabled)
        self.check_link_views.toggled.connect(self.on_link_views_toggled)
        view_defect_layout.addWidget(self.check_link_views)

        btn_reset_view = QtWidgets.QPushButton("Reset View")
        btn_reset_view.clicked.connect(self.reset_all_views)
        view_defect_layout.addWidget(btn_reset_view)

        view_defect_layout.addSpacing(15) # Add some space

        # Defect detection controls
        defect_label = QtWidgets.QLabel("<b>Defect Detection:</b>")
        view_defect_layout.addWidget(defect_label)
        self.btn_detect_defects = QtWidgets.QPushButton("Detect Defects")
        self.btn_detect_defects.clicked.connect(self.run_defect_detection) # Connect to new method
        self.btn_detect_defects.setEnabled(OPENCV_AVAILABLE) # Enable only if OpenCV is found
        if not OPENCV_AVAILABLE:
            self.btn_detect_defects.setToolTip("OpenCV (cv2) not found. Install it to enable detection.")
        view_defect_layout.addWidget(self.btn_detect_defects)

        # Optional: Add controls for threshold etc. later if needed
        # threshold_layout = QtWidgets.QHBoxLayout()
        # threshold_layout.addWidget(QtWidgets.QLabel("Threshold:"))
        # self.spin_threshold = QtWidgets.QSpinBox()
        # ... setup spin box ...
        # view_defect_layout.addLayout(threshold_layout)

        view_defect_layout.addStretch() # Push controls up

        # --- Display Area (Keep structure, update signal connections) ---
        self.view1 = ImageViewer()
        self.view2 = ImageViewer()
        self.view_combined = ImageViewer() # Used for Slider, A/B, and Defect Results

        self.view_stack = QtWidgets.QStackedWidget()
        side_by_side_widget = QtWidgets.QWidget()
        side_by_side_layout = QtWidgets.QHBoxLayout(side_by_side_widget)
        side_by_side_layout.setContentsMargins(0, 0, 0, 0)
        side_by_side_layout.setSpacing(1)
        side_by_side_layout.addWidget(self.view1)
        side_by_side_layout.addWidget(self.view2)
        self.view_stack.addWidget(side_by_side_widget)  # index 0: side_by_side
        self.view_stack.addWidget(self.view_combined)    # index 1: combined (slider, A/B, defects)
        main_layout.addWidget(self.view_stack, 1) # Stretch factor 1 for display area

        # --- Signal Connections (Consolidated) ---
        self.view1.viewChanged.connect(lambda: self.sync_views(self.view1))
        self.view2.viewChanged.connect(lambda: self.sync_views(self.view2))
        self.view_combined.viewChanged.connect(self.update_combined_view_items) # Sync slider pos if needed

        self.view1.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 1))
        self.view2.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 2))
        self.view_combined.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 0)) # 0 for combined view

        # --- Items for Slider/AB/Adjustment (Keep as is) ---
        scn_combined = self.view_combined.scene()
        # Item1 (Left in Slider, Image 1 in A/B adjust)
        self.item1 = MaskedOrFullPixmapItem(controller=self, item_id=1, is_left=True)
        self.item1.setVisible(False)
        scn_combined.addItem(self.item1)

        # Item2 (Right in Slider, Image 2 in A/B adjust)
        self.item2 = MaskedOrFullPixmapItem(controller=self, item_id=2, is_left=False)
        self.item2.setVisible(False)
        scn_combined.addItem(self.item2)

        # Interactive Slider Bar (Keep as is)
        self.interactive_slider = InteractiveSliderItem(self.view_combined.sceneRect())
        self.interactive_slider.signals.positionChanged.connect(self.on_slider_ratio_update)
        self.interactive_slider.setVisible(False)
        scn_combined.addItem(self.interactive_slider)

        # --- Status Bar (Keep as is) ---
        self.statusBar = QtWidgets.QStatusBar()
        self.setStatusBar(self.statusBar)
        self.lbl_status_coords = QtWidgets.QLabel("Coords: (N/A, N/A)")
        self.lbl_status_rgb = QtWidgets.QLabel("RGB: (N/A)")
        self.statusBar.addPermanentWidget(self.lbl_status_coords)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.statusBar.addPermanentWidget(spacer, 1)
        self.statusBar.addPermanentWidget(self.lbl_status_rgb)


    # -----------------------------------------------------------
    # Helper: Update enabled state of controls
    # -----------------------------------------------------------
    def update_controls_state(self):
        """Enable/disable controls based on loaded images and mode."""
        has_img1 = self.pil_image1_orig is not None
        has_img2 = self.pil_image2_orig is not None
        both_images_loaded = has_img1 and has_img2

        # Defect detection button
        self.btn_detect_defects.setEnabled(OPENCV_AVAILABLE and both_images_loaded)

        # Mode radios (enable only if relevant images are loaded)
        self.radio_side.setEnabled(has_img1 or has_img2)
        self.radio_slider.setEnabled(both_images_loaded)
        self.radio_ab_switch.setEnabled(both_images_loaded)

        # Size adjustment (enable only if both images loaded)
        self.combo_size_adjust.setEnabled(both_images_loaded)

        # Link views checkbox (relevant in side-by-side or when adjusting in slider/ab)
        self.check_link_views.setEnabled(True) # Always allow toggling link

        # Reset view button (always enabled)
        # btn_reset_view is always enabled

    # -----------------------------------------------------------
    # Helper: Conversion Functions (NEW)
    # -----------------------------------------------------------
    def pil_to_numpy(self, pil_img):
        """Convert PIL Image to NumPy array (RGB or RGBA)."""
        if pil_img is None:
            return None
        try:
            # Ensure it's RGB or RGBA for predictability
            if pil_img.mode not in ['RGB', 'RGBA']:
                pil_img = pil_img.convert('RGB')
            return np.array(pil_img)
        except Exception as e:
            print(f"Error converting PIL to NumPy: {e}")
            return None

    def numpy_to_qpixmap(self, np_img):
        """Convert NumPy array (RGB or BGR) to QPixmap."""
        if np_img is None:
            return QtGui.QPixmap()
        try:
            height, width, channel = np_img.shape
            bytes_per_line = 3 * width
            if channel == 3: # RGB or BGR
                 # Assume input is RGB (common after processing), create RGB QImage
                 qimg = QtGui.QImage(np_img.data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
                 # If input was BGR (e.g., direct from cv2.imread), it would need conversion first
                 # qimg = QtGui.QImage(cv2.cvtColor(np_img, cv2.COLOR_BGR2RGB).data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
            elif channel == 4: # RGBA
                 bytes_per_line = 4 * width
                 qimg = QtGui.QImage(np_img.data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGBA8888)
            else: # Grayscale or other formats - convert to RGB for display
                 if np_img.ndim == 2: # Grayscale
                     rgb_img = cv2.cvtColor(np_img, cv2.COLOR_GRAY2RGB)
                     height, width, channel = rgb_img.shape
                     bytes_per_line = 3 * width
                     qimg = QtGui.QImage(rgb_img.data, width, height, bytes_per_line, QtGui.QImage.Format.Format_RGB888)
                 else:
                      print(f"Unsupported NumPy array shape for QPixmap conversion: {np_img.shape}")
                      return QtGui.QPixmap()

            # Crucial: QImage needs a copy of the data if the NumPy array might go out of scope
            # or be modified. Using copy() ensures the QImage has its own data buffer.
            return QtGui.QPixmap.fromImage(qimg.copy())

        except Exception as e:
            print(f"Error converting NumPy to QPixmap: {e}")
            return QtGui.QPixmap()


    # -----------------------------------------------------------
    # Drag Control (Disable/Enable) (Keep as is)
    # -----------------------------------------------------------
    def disable_drag_for_slider(self, item: QtWidgets.QGraphicsPixmapItem):
        old_flags = item.flags()
        new_flags = old_flags & ~QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        item.setFlags(new_flags)

    def enable_drag(self, item: QtWidgets.QGraphicsPixmapItem):
        old_flags = item.flags()
        new_flags = old_flags | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        item.setFlags(new_flags)

    # -----------------------------------------------------------
    # Mode Switching (Keep as is, but update_display handles logic)
    # -----------------------------------------------------------
    def set_mode(self, mode):
        if self.current_mode != mode:
            print(f"Mode changed from {self.current_mode} to: {mode}")
            prev_mode = self.current_mode
            self.current_mode = mode

            # Stop timer if leaving A/B mode
            if prev_mode == "ab_switch":
                self.ab_timer.stop()
                print("A/B Timer stopped.")
                self._ab_recalage_actif = False # Ensure adjustment mode is off

            # Configure stacked widget for A/B options
            if mode == "ab_switch":
                self.options_stack.setCurrentIndex(1)
                self._ab_recalage_actif = False # Start in normal A/B, not adjustment
            else:
                self.options_stack.setCurrentIndex(0) # Hide A/B options

            # Update the display which handles visibility and item setup
            self.update_display()
            self.update_controls_state()

    # -----------------------------------------------------------
    # Event Handlers (AB Speed, Link Views, Slider Ratio) (Keep as is)
    # -----------------------------------------------------------
    def on_ab_speed_changed(self, value):
        self.ab_switch_interval = value
        self.lbl_ab_speed_value.setText(str(value))
        if self.ab_timer.isActive():
            self.ab_timer.setInterval(self.ab_switch_interval)
            # print(f"A/B Timer interval updated to: {self.ab_switch_interval} ms") # Less verbose

    def on_link_views_toggled(self, checked):
        self.link_views_enabled = checked
        print(f"Link Views / Sync Drag -> {checked}")

        # If switching linking ON in Side-by-Side, sync immediately
        if self.current_mode == "side_by_side" and checked:
             self.sync_views(self.view1, force_sync=True)
        # If in Slider/AB and linking is toggled, update offset state
        elif self.current_mode in ["slider", "ab_switch"]:
             if checked:
                 # Capture current relative position as the desired offset
                 x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                 x2, y2 = self.item2.pos().x(), self.item2.pos().y()
                 self._slider_offset_x = x2 - x1
                 self._slider_offset_y = y2 - y1
                 print(f"Captured offset: dx={self._slider_offset_x:.2f}, dy={self._slider_offset_y:.2f}")
                 # Force item2 position based on item1 and the new offset
                 self.item2.setPos(x1 + self._slider_offset_x, y1 + self._slider_offset_y)
             # If unchecked, the offset is no longer enforced, items move independently

        # When toggling link views in Slider mode, update the slider bar geometry
        if self.current_mode == "slider":
            self.update_combined_view_items()


    def on_slider_ratio_update(self, ratio: float):
        if self.current_mode == "slider":
            self.item1.set_slider_ratio(ratio)
            self.item2.set_slider_ratio(ratio)
            # No need to update slider geometry here, it emitted the signal
            # self.update_combined_view_items() # Avoid potential recursion

    def switch_ab_image(self):
        if self.current_mode != "ab_switch" or not self.display_pixmap1 or not self.display_pixmap2:
            self.ab_timer.stop()
            return

        # Only switch if not in adjustment mode
        if not self._ab_recalage_actif:
            self.ab_showing_image1 = not self.ab_showing_image1
            pixmap_to_show = self.display_pixmap1 if self.ab_showing_image1 else self.display_pixmap2
            item_to_show = self.item1 if self.ab_showing_image1 else self.item2

            if pixmap_to_show and not pixmap_to_show.isNull():
                 # In A/B mode, we show *one* item at a time
                 self.item1.setVisible(self.ab_showing_image1)
                 self.item2.setVisible(not self.ab_showing_image1)
                 # Ensure the correct pixmap is set (might have changed due to resize)
                 self.item1.setPixmap(self.display_pixmap1)
                 self.item2.setPixmap(self.display_pixmap2)

                 # Update positions based on link status
                 if self.link_views_enabled:
                     if self.ab_showing_image1:
                         # If showing item1, item2's position should be item1 + offset
                         p1 = self.item1.pos()
                         self.item2.setPos(p1.x() + self._slider_offset_x, p1.y() + self._slider_offset_y)
                     else:
                         # If showing item2, item1's position should be item2 - offset
                         p2 = self.item2.pos()
                         self.item1.setPos(p2.x() - self._slider_offset_x, p2.y() - self._slider_offset_y)
                 # else: positions are independent and managed by drag

            else:
                self.ab_timer.stop()
                print("Warning: A/B switch stopped due to invalid pixmap.")
                self.item1.setVisible(False)
                self.item2.setVisible(False)

    # -----------------------------------------------------------
    # Image Loading (Minor label changes)
    # -----------------------------------------------------------
    def load_image(self, image_num):
        # Keep the core loading logic
        role = "Reference (1)" if image_num == 1 else "Test (2)"
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Select Image {role}", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;All Files (*)"
        )
        if not filepath:
            return

        if Image is None:
             QtWidgets.QMessageBox.critical(self, "Error", "Pillow library is not installed. Cannot load images.")
             return

        try:
            self.statusBar.showMessage(f"Loading Image {image_num}...")
            img = Image.open(filepath)

            # Resize if too large (Pillow operation)
            if max(img.width, img.height) > MAX_IMAGE_DIM_LOAD:
                img.thumbnail((MAX_IMAGE_DIM_LOAD, MAX_IMAGE_DIM_LOAD), Image.Resampling.LANCZOS)
                print(f"Image {image_num} resized during load to fit max dimension {MAX_IMAGE_DIM_LOAD}px")

            # Convert to RGB/RGBA using Pillow for consistency before QPixmap conversion
            pil_img_conv = img.convert("RGBA") if 'A' in img.getbands() else img.convert("RGB")
            qt_pixmap = self.pil_to_qpixmap(pil_img_conv) # Use own converter

            if qt_pixmap.isNull():
                 raise ValueError("Failed to convert PIL image to QPixmap.")

            if image_num == 1:
                self.image_path1 = filepath
                self.pil_image1_orig = pil_img_conv # Store the Pillow object
                self.qt_pixmap1_orig = qt_pixmap    # Store the original QPixmap
                self.lbl_img1.setText(f"Ref: {os.path.basename(filepath)}")
            else:
                self.image_path2 = filepath
                self.pil_image2_orig = pil_img_conv
                self.qt_pixmap2_orig = qt_pixmap
                self.lbl_img2.setText(f"Test: {os.path.basename(filepath)}")

            print(f"Loaded Image {image_num}: {filepath} ({pil_img_conv.width}x{pil_img_conv.height})")
            self.statusBar.showMessage(f"Image {role} loaded successfully.", 3000)

            # Crucial: Update display *after* setting the images
            self.update_display()
            self.update_controls_state() # Update button enable state etc.

            # Reset the relevant view after loading
            if self.current_mode == "side_by_side":
                view_to_reset = self.view1 if image_num == 1 else self.view2
                view_to_reset.reset_view()
            else:
                 # Only reset combined view if it's the active one
                 if self.view_stack.currentIndex() == 1:
                     self.view_combined.reset_view()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error Loading Image", f"Could not load image '{filepath}':\n{e}")
            self.statusBar.showMessage(f"Failed to load Image {image_num}.", 5000)
            if image_num == 1:
                self.image_path1 = None
                self.pil_image1_orig = None
                self.qt_pixmap1_orig = None
                self.lbl_img1.setText("No Reference Image")
            else:
                self.image_path2 = None
                self.pil_image2_orig = None
                self.qt_pixmap2_orig = None
                self.lbl_img2.setText("No Test Image")
            # Update display and controls even on failure
            self.update_display()
            self.update_controls_state()

    # pil_to_qpixmap (keep existing one for now, or replace with numpy bridge if preferred)
    # Sticking with the existing one for now to minimize changes unrelated to defect detection
    def pil_to_qpixmap(self, pil_image):
        """Converts a PIL Image to QPixmap using ImageQt or fallback."""
        if pil_image is None:
            return QtGui.QPixmap()
        if ImageQt is None and Image is None:
             print("Error: Pillow/ImageQt not available for conversion.")
             return QtGui.QPixmap()

        try:
            # Ensure mode is suitable for QPixmap conversion
            if pil_image.mode not in ["RGB", "RGBA", "L"]: # L for grayscale
                pil_image = pil_image.convert("RGB")

            if ImageQt:
                # Use ImageQt if available (often handles formats better)
                qimage = ImageQt.ImageQt(pil_image)
                # ImageQt can return QImage or QPixmap depending on version/platform
                if isinstance(qimage, QtGui.QImage):
                    return QtGui.QPixmap.fromImage(qimage)
                elif isinstance(qimage, QtGui.QPixmap):
                    return qimage
                else:
                    # Fallback if ImageQt returns something unexpected
                     print("Warning: Unexpected type from ImageQt, using fallback.")
                     pass # Proceed to fallback

            # Fallback conversion (manual for common modes)
            if pil_image.mode == "RGB":
                data = pil_image.tobytes("raw", "RGB")
                qimg = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGB888)
            elif pil_image.mode == "RGBA":
                data = pil_image.tobytes("raw", "RGBA")
                qimg = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGBA8888)
            elif pil_image.mode == "L": # Grayscale
                 data = pil_image.tobytes("raw", "L")
                 qimg = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_Grayscale8)
            else:
                print(f"Warning: Unsupported PIL mode '{pil_image.mode}' for fallback conversion.")
                return QtGui.QPixmap() # Cannot convert

            # Important: Create a copy for the QPixmap if QImage data buffer might change
            return QtGui.QPixmap.fromImage(qimg.copy())

        except Exception as e:
            print(f"Error converting PIL to QPixmap: {e}")
            return QtGui.QPixmap()

    # -----------------------------------------------------------
    # Display Update Logic (Major rework needed for modes)
    # -----------------------------------------------------------
    def update_display(self):
        print(f"Updating display for mode: {self.current_mode}")
        # Ensure timer is stopped unless in A/B mode
        if self.current_mode != "ab_switch" and self.ab_timer.isActive():
            self.ab_timer.stop()
            print("Stopped A/B timer as mode changed.")

        # Prepare display pixmaps based on original loaded images and size adjustment
        self.prepare_display_images() # This applies resizing logic

        # --- Clear previous state ---
        # Hide slider and special items by default
        self.interactive_slider.setVisible(False)
        self.item1.setVisible(False)
        self.item2.setVisible(False)
        # Clear the standard pixmap items in all views
        self.view1.set_pixmap(QtGui.QPixmap())
        self.view2.set_pixmap(QtGui.QPixmap())
        self.view_combined.get_pixmap_item().setPixmap(QtGui.QPixmap()) # Clear standard item in combined view


        # --- Configure based on current mode ---
        if self.current_mode == "side_by_side":
            self.view_stack.setCurrentIndex(0) # Show the two views
            self.view1.set_pixmap(self.display_pixmap1)
            self.view2.set_pixmap(self.display_pixmap2)
            # Reset item properties (though they are hidden)
            self.item1.set_use_mask(False)
            self.item2.set_use_mask(False)
            self.item1.setOpacity(1.0)
            self.item2.setOpacity(1.0)
            # Ensure drag is enabled if needed (handled by item itself, but maybe reset flags?)
            # self.enable_drag(self.item1) # Items are hidden, so not strictly needed
            # self.enable_drag(self.item2)
            if self.link_views_enabled:
                self.sync_views(self.view1, force_sync=True) # Force sync on mode switch

        else: # Combined view modes (Slider, A/B)
            self.view_stack.setCurrentIndex(1) # Show the single combined view

            # Set pixmaps for the interactive items (used by Slider/AB)
            # Use the potentially resized display_pixmaps
            self.item1.setPixmap(self.display_pixmap1 if self.display_pixmap1 else QtGui.QPixmap())
            self.item2.setPixmap(self.display_pixmap2 if self.display_pixmap2 else QtGui.QPixmap())

            # Determine scene rect based on the items' pixmaps
            w1, h1 = (self.item1.pixmap().width(), self.item1.pixmap().height()) if not self.item1.pixmap().isNull() else (0,0)
            w2, h2 = (self.item2.pixmap().width(), self.item2.pixmap().height()) if not self.item2.pixmap().isNull() else (0,0)
            scene_w = max(w1, w2, 1) # Ensure minimum size of 1
            scene_h = max(h1, h2, 1)
            # Adjust scene rect based on item positions to encompass both fully
            # Get current positions (might be non-zero from previous interactions)
            p1 = self.item1.pos()
            p2 = self.item2.pos()
            min_x = min(p1.x(), p2.x())
            min_y = min(p1.y(), p2.y())
            max_x = max(p1.x() + w1, p2.x() + w2)
            max_y = max(p1.y() + h1, p2.y() + h2)
            scene_rect = QtCore.QRectF(min_x, min_y, max_x - min_x, max_y - min_y)
            # Only update scene rect if it's valid
            if scene_rect.isValid() and scene_rect.width() > 0 and scene_rect.height() > 0:
                self.view_combined.setSceneRect(scene_rect)
            else: # Fallback if items/pixmaps are invalid
                self.view_combined.setSceneRect(0, 0, scene_w, scene_h)
                # Reset positions if scene rect was reset
                self.item1.setPos(0,0)
                self.item2.setPos(0,0)


            if self.current_mode == "slider":
                # --- Slider Mode Setup ---
                self.item1.set_use_mask(True)  # Enable masking for split view
                self.item2.set_use_mask(True)
                self.item1.setOpacity(1.0) # Ensure full opacity
                self.item2.setOpacity(1.0)
                self.item1.setVisible(True) # Show both masked items
                self.item2.setVisible(True)
                self.interactive_slider.setVisible(True) # Show slider bar
                self.disable_drag_for_slider(self.item1) # Disable drag on images
                self.disable_drag_for_slider(self.item2)
                self.update_combined_view_items() # Update slider geometry and item masks

            elif self.current_mode == "ab_switch":
                # --- A/B Switch Mode Setup ---
                self.item1.set_use_mask(False) # No masking
                self.item2.set_use_mask(False)
                self.enable_drag(self.item1) # Enable drag for adjustment
                self.enable_drag(self.item2)

                if not self.display_pixmap1 or not self.display_pixmap2:
                    self.statusBar.showMessage("A/B Switch requires both images loaded.", 3000)
                    # Show available image if only one exists
                    self.item1.setVisible(self.display_pixmap1 is not None)
                    self.item2.setVisible(self.display_pixmap2 is not None)
                else:
                    # Check if in adjustment mode (link views disabled)
                    if not self.link_views_enabled:
                         self._ab_recalage_actif = True # Enter adjustment mode
                         print("A/B Switch: Entering adjustment mode (Link Views OFF). Drag images to align.")
                         self.statusBar.showMessage("A/B Adjust: Drag images to align, then enable Link Views.", 5000)
                         self.item1.setVisible(True)
                         self.item2.setVisible(True)
                         self.item1.setOpacity(0.6) # Make semi-transparent for alignment
                         self.item2.setOpacity(0.6)
                         if self.ab_timer.isActive(): self.ab_timer.stop() # Stop timer during adjustment
                    else:
                         self._ab_recalage_actif = False # Normal A/B switching mode
                         print("A/B Switch: Normal switching mode (Link Views ON).")
                         self.item1.setOpacity(1.0) # Full opacity
                         self.item2.setOpacity(1.0)
                         # Start timer (switch_ab_image handles visibility)
                         self.ab_showing_image1 = True # Start with image 1
                         self.switch_ab_image() # Set initial visibility
                         if not self.ab_timer.isActive():
                             self.ab_timer.setInterval(self.ab_switch_interval)
                             self.ab_timer.start()
                             print(f"A/B Timer started: {self.ab_switch_interval} ms")

            # Reset view for combined modes after setup
            # Check if scene is valid before resetting
            if self.view_combined.sceneRect().isValid():
                 self.view_combined.reset_view()
            else:
                 print("Warning: Combined view scene rect is invalid, skipping reset view.")

        # Ensure controls reflect the current state (e.g., disable slider mode if only one image)
        self.update_controls_state()


    def prepare_display_images(self):
        """Applies size adjustments based on self.size_adjust_mode."""
        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig
        self.display_pixmap1 = self.qt_pixmap1_orig.copy() if self.qt_pixmap1_orig else QtGui.QPixmap()
        self.display_pixmap2 = self.qt_pixmap2_orig.copy() if self.qt_pixmap2_orig else QtGui.QPixmap()

        if not pil1 or not pil2:
             # print("One or both images not loaded, skipping size adjustment.")
             return # Need both images to adjust

        size1 = pil1.size
        size2 = pil2.size

        if size1 == size2 and self.size_adjust_mode != "original":
            # print("Images are already the same size, no adjustment needed.")
             return # No adjustment needed unless forcing original

        adjust_mode = self.size_adjust_mode
        print(f"Applying size adjustment mode: {adjust_mode}")

        new_pil1 = pil1
        new_pil2 = pil2

        try:
            if adjust_mode == "resize2to1":
                if size1 != size2:
                    print(f"Resizing Image 2 ({size2[0]}x{size2[1]}) -> Image 1 ({size1[0]}x{size1[1]})")
                    new_pil2 = pil2.resize(size1, Image.Resampling.LANCZOS)
            elif adjust_mode == "resize1to2":
                 if size1 != size2:
                    print(f"Resizing Image 1 ({size1[0]}x{size1[1]}) -> Image 2 ({size2[0]}x{size2[1]})")
                    new_pil1 = pil1.resize(size2, Image.Resampling.LANCZOS)
            elif adjust_mode == "resizeboth":
                max_width = max(size1[0], size2[0])
                max_height = max(size1[1], size2[1])
                new_size = (max_width, max_height)
                print(f"Resizing both images to max size: {max_width}x{max_height}")
                if size1 != new_size:
                    new_pil1 = pil1.resize(new_size, Image.Resampling.LANCZOS)
                if size2 != new_size:
                    new_pil2 = pil2.resize(new_size, Image.Resampling.LANCZOS)
            elif adjust_mode == "proportional":
                 # This mode needs careful implementation to maintain aspect ratio
                 # while making dimensions comparable. Let's scale image 2 proportionally
                 # to match the width of image 1 for simplicity here.
                 # A more robust approach might involve fitting both into a common bounding box.
                 if size1[0] != size2[0]:
                     ratio = size1[0] / size2[0]
                     new_h2 = int(size2[1] * ratio)
                     new_size2 = (size1[0], new_h2)
                     print(f"Proportionally resizing Image 2 ({size2[0]}x{size2[1]}) -> ({new_size2[0]}x{new_size2[1]}) to match Image 1 width")
                     new_pil2 = pil2.resize(new_size2, Image.Resampling.LANCZOS)
                 # Keep image 1 as is in this simplified proportional mode
                 new_pil1 = pil1
            elif adjust_mode == "original":
                print("Keeping original image sizes.")
                # No changes needed, new_pil1/2 remain original pil1/2
                pass

            # Convert the potentially new PIL images back to QPixmaps for display
            # Only reconvert if the PIL image object actually changed
            if new_pil1 is not pil1:
                self.display_pixmap1 = self.pil_to_qpixmap(new_pil1)
            if new_pil2 is not pil2:
                self.display_pixmap2 = self.pil_to_qpixmap(new_pil2)

        except Exception as e:
             print(f"Error during size adjustment ({adjust_mode}): {e}")
             # Revert to original pixmaps on error
             self.display_pixmap1 = self.qt_pixmap1_orig.copy() if self.qt_pixmap1_orig else QtGui.QPixmap()
             self.display_pixmap2 = self.qt_pixmap2_orig.copy() if self.qt_pixmap2_orig else QtGui.QPixmap()

        # Debug: Print final display sizes
        w1_disp, h1_disp = (self.display_pixmap1.width(), self.display_pixmap1.height()) if self.display_pixmap1 else (0,0)
        w2_disp, h2_disp = (self.display_pixmap2.width(), self.display_pixmap2.height()) if self.display_pixmap2 else (0,0)
        print(f"Final display sizes: Img1={w1_disp}x{h1_disp}, Img2={w2_disp}x{h2_disp}")


    # update_comparison_image (Seems unused, remove or repurpose?)
    # Removed as defect detection provides the comparison result now.

    def reset_all_views(self):
        print("Resetting all views...")
        # Reset individual views if in side-by-side mode
        if self.current_mode == "side_by_side":
            self.view1.reset_view()
            self.view2.reset_view()
        else:
             # Reset combined view for Slider, A/B, or Defect result
             self.view_combined.reset_view()

        # Reset slider position only if it's relevant (Slider mode)
        if self.interactive_slider:
            current_ratio = self.interactive_slider.get_position_ratio()
            if not np.isclose(current_ratio, 0.5):
                 self.interactive_slider.set_position_ratio(0.5)
                 # If in slider mode, trigger update based on new ratio
                 if self.current_mode == "slider":
                     self.on_slider_ratio_update(0.5)

        # Reset item positions in combined view (important after dragging)
        # Also reset offsets
        self.item1.setPos(0, 0)
        self.item2.setPos(0, 0)
        self._slider_offset_x = 0.0
        self._slider_offset_y = 0.0
        self._offset_x = 0 # Reset side-by-side offset too
        self._offset_y = 0

        # If in a combined mode, ensure items/slider reflect the reset positions
        if self.current_mode in ["slider", "ab_switch"]:
             self.update_combined_view_items()

        self.statusBar.showMessage("Views reset.", 2000)


    def move_pixmap_item(self, item_id: int, dx: float, dy: float):
        """Handles moving item1 or item2 in combined view modes."""
        # This function is called by DraggablePixmapItem on mouse drag
        if self.current_mode not in ("slider", "ab_switch"):
            # print("Drag ignored: Not in Slider or A/B mode.")
            return # Dragging only relevant in these modes

        # --- Handle A/B Switch Adjustment Mode ---
        if self.current_mode == "ab_switch" and self._ab_recalage_actif:
             # Allow free drag of both items when adjusting
             if item_id == 1:
                 p1 = self.item1.pos()
                 self.item1.setPos(p1.x() + dx, p1.y() + dy)
             else: # item_id == 2
                 p2 = self.item2.pos()
                 self.item2.setPos(p2.x() + dx, p2.y() + dy)
             # Update the stored offset while dragging in adjustment mode
             self._slider_offset_x = self.item2.pos().x() - self.item1.pos().x()
             self._slider_offset_y = self.item2.pos().y() - self.item1.pos().y()
             # No need to update slider bar here
             return # Finished handling adjustment drag

        # --- Handle Slider Mode and Linked A/B Mode ---
        if not self.link_views_enabled:
            # Link Views OFF: Only vertical drag allowed in Slider, free drag in A/B
            target_item = self.item1 if item_id == 1 else self.item2
            current_pos = target_item.pos()
            if self.current_mode == "slider":
                # Slider mode, link off: Only allow vertical movement (dy)
                 target_item.setPos(current_pos.x(), current_pos.y() + dy)
            else: # A/B mode, link off (should be adjustment mode, handled above, but as fallback)
                 target_item.setPos(current_pos.x() + dx, current_pos.y() + dy)
        else:
             # Link Views ON: Move both items together maintaining offset
             if item_id == 1:
                 p1 = self.item1.pos()
                 new_p1 = QtCore.QPointF(p1.x() + dx, p1.y() + dy)
                 self.item1.setPos(new_p1)
                 # Move item2 relative to item1 using the stored offset
                 self.item2.setPos(new_p1.x() + self._slider_offset_x,
                                 new_p1.y() + self._slider_offset_y)
             else: # item_id == 2
                 p2 = self.item2.pos()
                 new_p2 = QtCore.QPointF(p2.x() + dx, p2.y() + dy)
                 self.item2.setPos(new_p2)
                 # Move item1 relative to item2 using the stored offset
                 self.item1.setPos(new_p2.x() - self._slider_offset_x,
                                 new_p2.y() - self._slider_offset_y)

        # Update slider bar geometry if in slider mode after movement
        if self.current_mode == "slider":
             self.update_combined_view_items()


    def update_combined_view_items(self):
        """Updates slider position/geometry based on item1's position and size."""
        if self.current_mode == "slider" and self.interactive_slider.isVisible():
            item1_rect = self.item1.sceneBoundingRect() # Use scene bounding rect
            if item1_rect.isValid() and not self.item1.pixmap().isNull():
                # Slider bar should span the height of item1 at its current x position
                slider_scene_rect = QtCore.QRectF(item1_rect.left(), item1_rect.top(),
                                                item1_rect.width(), item1_rect.height())
                self.interactive_slider.set_scene_rect(slider_scene_rect)
                # Ensure the line position reflects the current ratio within the new rect
                current_ratio = self.interactive_slider.get_position_ratio()
                self.interactive_slider.set_position_ratio(current_ratio) # This calls update_line_geometry
            else:
                 # If item1 is invalid, maybe hide the slider or set a default rect?
                 # self.interactive_slider.setVisible(False)
                 pass # Keep slider visible but potentially misaligned if item1 vanishes


    def sync_views(self, source_view, force_sync=False):
        """Synchronizes zoom/pan between view1 and view2 in side-by-side mode."""
        if self._is_updating_views or self.current_mode != "side_by_side":
            return
        if not self.link_views_enabled and not force_sync:
             # If linking is off, just update the offset based on scrollbar values
             h1 = self.view1.horizontalScrollBar().value()
             v1 = self.view1.verticalScrollBar().value()
             h2 = self.view2.horizontalScrollBar().value()
             v2 = self.view2.verticalScrollBar().value()
             # Store difference in scroll values as offset
             self._offset_x = h2 - h1
             self._offset_y = v2 - v1
             # print(f"Side-by-side offset updated: dx={self._offset_x}, dy={self._offset_y}")
             return

        self._is_updating_views = True # Lock to prevent recursion

        try:
            target_view = self.view2 if source_view == self.view1 else self.view1

            # 1. Sync Transform (Zoom and top-left corner position in scene coords)
            source_transform = source_view.transform()
            target_view.setTransform(source_transform) # This also updates target_view._zoom

            # 2. Sync Scrollbars (Pan) respecting the offset
            # Get source scrollbar values
            s_hval = source_view.horizontalScrollBar().value()
            s_vval = source_view.verticalScrollBar().value()
            s_hmax = source_view.horizontalScrollBar().maximum()
            s_vmax = source_view.verticalScrollBar().maximum()

            # Set target scrollbar maximums (in case scene sizes differ slightly)
            target_view.horizontalScrollBar().setMaximum(s_hmax)
            target_view.verticalScrollBar().setMaximum(s_vmax)

            # Calculate target scrollbar values using the offset
            if source_view == self.view1:
                # Source is view1, target is view2. Target scroll = Source scroll + offset
                new_h = s_hval + self._offset_x
                new_v = s_vval + self._offset_y
            else: # Source is view2, target is view1. Target scroll = Source scroll - offset
                new_h = s_hval - self._offset_x
                new_v = s_vval - self._offset_y

            # Apply the calculated scroll values to the target view
            target_view.horizontalScrollBar().setValue(new_h)
            target_view.verticalScrollBar().setValue(new_v)

        except Exception as e:
            print(f"Error during view synchronization: {e}")
        finally:
            self._is_updating_views = False # Release lock

    # update_status_bar (Keep largely as is, adjust item checks)
    def update_status_bar(self, scene_pos, view_index):
        """Updates status bar with coordinates and RGB value under cursor."""
        coords_text = "Coords: (N/A)"
        rgb_text = "RGB: (N/A)"
        pix_item_to_check = None
        source_pil_img = None # To get original pixel data if needed

        if view_index == 1 and self.current_mode == "side_by_side":
            pix_item_to_check = self.view1.get_pixmap_item()
            source_pil_img = self.pil_image1_orig # Use original PIL for accurate color
        elif view_index == 2 and self.current_mode == "side_by_side":
            pix_item_to_check = self.view2.get_pixmap_item()
            source_pil_img = self.pil_image2_orig
        elif view_index == 0 and self.current_mode != "side_by_side":
             # Combined view: Check which item is under the cursor
             item_under_mouse = self.view_combined.itemAt(self.view_combined.mapFromScene(scene_pos))

             if isinstance(item_under_mouse, MaskedOrFullPixmapItem):
                 pix_item_to_check = item_under_mouse
                 source_pil_img = self.pil_image1_orig if item_under_mouse == self.item1 else self.pil_image2_orig
             elif isinstance(item_under_mouse, QtWidgets.QGraphicsPixmapItem) and item_under_mouse == self.view_combined.get_pixmap_item():
                  # Check the standard item (e.g., for defect detection result)
                  pix_item_to_check = item_under_mouse
                  # What image does the standard item represent? Needs context.
                  # For now, assume it's related to image 1 if displaying defects.
                  # This part might need refinement based on what's shown in the standard item.
                  source_pil_img = self.pil_image1_orig # Default assumption

        if pix_item_to_check and isinstance(pix_item_to_check, QtWidgets.QGraphicsPixmapItem):
            pm = pix_item_to_check.pixmap()
            if not pm.isNull():
                # Map scene coordinates to the item's local coordinates
                item_pt = pix_item_to_check.mapFromScene(scene_pos)
                ix, iy = int(item_pt.x()), int(item_pt.y())
                w, h = pm.width(), pm.height() # Use display pixmap size for bounds check

                if 0 <= ix < w and 0 <= iy < h:
                    coords_text = f"Coords: ({ix},{iy}) / ({w}x{h})"
                    # Get color: Use original PIL image if available for accuracy,
                    # otherwise use the potentially resized QPixmap's image.
                    try:
                        if source_pil_img and 0 <= ix < source_pil_img.width and 0 <= iy < source_pil_img.height:
                            # Check bounds against original image size too
                             pixel = source_pil_img.getpixel((ix, iy))
                             if isinstance(pixel, (tuple, list)): # RGB or RGBA
                                 r, g, b = pixel[:3]
                                 rgb_text = f"RGB: ({r},{g},{b})"
                             else: # Grayscale
                                 rgb_text = f"Gray: ({pixel})"
                        else: # Fallback to QPixmap data
                            qimg = pm.toImage()
                            if qimg.valid(ix, iy):
                                c = QtGui.QColor(qimg.pixel(ix, iy))
                                rgb_text = f"RGB: ({c.red()},{c.green()},{c.blue()})"
                            else:
                                rgb_text = "RGB: (Invalid QImg Coord)"
                    except Exception as e:
                         # print(f"Statusbar: Error getting pixel data: {e}")
                         rgb_text = "RGB: (Error)"
                else:
                    coords_text = f"Coords: (Out of bounds) / ({w}x{h})"

        self.lbl_status_coords.setText(coords_text)
        self.lbl_status_rgb.setText(rgb_text)


    def on_size_adjust_changed(self, index):
        """Handles selection change in the size adjustment combo box."""
        key = self.combo_size_adjust.itemData(index)
        if key != self.size_adjust_mode:
            print(f"Size adjustment mode changed to: {key} ({self.size_adjust_options[key]})")
            self.size_adjust_mode = key
            # Re-prepare and update display with new sizing
            self.update_display()


    # create_ab_blend_image (No longer needed, remove)
    # pil_to_qimage (No longer needed, remove)

    # -----------------------------------------------------------
    # Defect Detection Functionality (NEW)
    # -----------------------------------------------------------
    def run_defect_detection(self):
        """Initiates the defect detection process."""
        if not OPENCV_AVAILABLE:
            QtWidgets.QMessageBox.warning(self, "OpenCV Missing", "OpenCV (cv2) library is required for defect detection but was not found.")
            return
        if not self.pil_image1_orig or not self.pil_image2_orig:
             QtWidgets.QMessageBox.warning(self, "Missing Images", "Please load both a Reference (Image 1) and a Test (Image 2) image before detecting defects.")
             return

        self.statusBar.showMessage("Detecting defects...", 0) # Persistent message
        QtWidgets.QApplication.processEvents() # Allow UI to update status

        try:
            # Perform detection (call the core logic function)
            result_pixmap = self.detect_defects(
                self.pil_image1_orig,
                self.pil_image2_orig,
                threshold=self.defect_threshold,
                kernel_size=self.morph_kernel_size,
                iterations=self.morph_iterations
            )

            if result_pixmap and not result_pixmap.isNull():
                # --- Display the result ---
                # 1. Switch to the combined view
                self.view_stack.setCurrentIndex(1)

                # 2. Clear any previous items (slider, A/B items)
                self.interactive_slider.setVisible(False)
                self.item1.setVisible(False)
                self.item2.setVisible(False)

                # 3. Set the result on the *standard* pixmap item of view_combined
                combined_standard_item = self.view_combined.get_pixmap_item()
                self.view_combined.set_pixmap(result_pixmap) # set_pixmap handles scene rect

                # 4. Reset the view to fit the result image
                self.view_combined.reset_view()

                self.statusBar.showMessage("Defect detection complete. Result displayed.", 5000)
                print("Defect detection finished, result shown in combined view.")
                # Note: We are not setting a specific "defect mode". The result is just displayed.
                # User can then switch back to other modes if desired.
            else:
                 # Handle cases where detection failed or returned no result
                 QtWidgets.QMessageBox.information(self, "Detection Result", "Defect detection process did not produce a valid result image.")
                 self.statusBar.showMessage("Defect detection failed or produced no result.", 5000)


        except Exception as e:
            print(f"Error during defect detection process: {e}")
            import traceback
            traceback.print_exc() # Print detailed traceback for debugging
            QtWidgets.QMessageBox.critical(self, "Detection Error", f"An error occurred during defect detection:\n{e}")
            self.statusBar.showMessage("Defect detection encountered an error.", 5000)


    def detect_defects(self, pil_ref, pil_test, threshold=30, kernel_size=(3,3), iterations=2):
        """
        Performs defect detection using OpenCV.
        Args:
            pil_ref (PIL.Image): Reference image.
            pil_test (PIL.Image): Test image.
            threshold (int): Threshold value for difference image.
            kernel_size (tuple): Kernel size for morphological closing.
            iterations (int): Number of iterations for closing.
        Returns:
            QtGui.QPixmap: Reference image with detected defect contours, or None on error.
        """
        if not OPENCV_AVAILABLE or cv2 is None or Image is None:
            print("Error: OpenCV or Pillow not available for detect_defects.")
            return None

        print(f"Starting defect detection: threshold={threshold}, kernel={kernel_size}, iterations={iterations}")

        # 1. Convert PIL Images to NumPy arrays (OpenCV format - BGR)
        # Using COLOR_RGB2BGR because PIL images are RGB(A)
        np_ref_rgb = self.pil_to_numpy(pil_ref)
        np_test_rgb = self.pil_to_numpy(pil_test)

        if np_ref_rgb is None or np_test_rgb is None:
            print("Error converting PIL images to NumPy arrays.")
            return None

        # Ensure 3 channels (BGR) before conversion
        if np_ref_rgb.shape[-1] == 4: np_ref_rgb = cv2.cvtColor(np_ref_rgb, cv2.COLOR_RGBA2BGR)
        if np_test_rgb.shape[-1] == 4: np_test_rgb = cv2.cvtColor(np_test_rgb, cv2.COLOR_RGBA2BGR)

        np_ref_bgr = np_ref_rgb # Already BGR if converted correctly
        np_test_bgr = np_test_rgb


        # 2. Resize Test image to match Reference image if needed
        h_ref, w_ref = np_ref_bgr.shape[:2]
        h_test, w_test = np_test_bgr.shape[:2]
        if (h_ref, w_ref) != (h_test, w_test):
            print(f"Resizing test image ({w_test}x{h_test}) to match reference ({w_ref}x{h_ref}) for detection.")
            np_test_bgr = cv2.resize(np_test_bgr, (w_ref, h_ref), interpolation=cv2.INTER_LANCZOS4) # Use high-quality resize

        # 3. Convert to Grayscale
        gray_ref = cv2.cvtColor(np_ref_bgr, cv2.COLOR_BGR2GRAY)
        gray_test = cv2.cvtColor(np_test_bgr, cv2.COLOR_BGR2GRAY)

        # --- Optional: Apply Gaussian Blur ---
        # Can help reduce noise sensitivity before diffing
        # blur_ksize = (5, 5)
        # gray_ref = cv2.GaussianBlur(gray_ref, blur_ksize, 0)
        # gray_test = cv2.GaussianBlur(gray_test, blur_ksize, 0)
        # print("Applied Gaussian Blur")

        # 4. Calculate Absolute Difference
        diff = cv2.absdiff(gray_ref, gray_test)
        # print(f"Difference calculated. Max diff value: {cv2.minMaxLoc(diff)[1]}")


        # 5. Threshold the Difference Image
        # _, thresh = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
        # Adaptive thresholding might be better if lighting varies across the board
        thresh = cv2.adaptiveThreshold(diff, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                      cv2.THRESH_BINARY_INV, 11, threshold) # Block size 11, C=threshold
        # Note: Using THRESH_BINARY_INV because adaptive often finds dark areas on light bg
        # We might need THRESH_BINARY depending on the image nature (defects brighter or darker?)
        # Let's stick to simple threshold for now as requested:
        _, thresh = cv2.threshold(diff, threshold, 255, cv2.THRESH_BINARY)
        print(f"Threshold applied at {threshold}.")

        # 6. Morphological Operations (Closing)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, kernel_size)
        closed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=iterations)
        # Optional: Add dilation to make contours slightly larger/more visible
        # closed = cv2.dilate(closed, kernel, iterations=1)
        print(f"Morphological closing performed with kernel {kernel_size}, {iterations} iterations.")


        # 7. Find Contours
        contours, _ = cv2.findContours(closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        print(f"Found {len(contours)} potential defect contours.")

        # 8. Draw Contours on the original Reference Image (Color)
        # Create a color copy of the reference image to draw on
        result_img_bgr = np_ref_bgr.copy()
        contour_color = (0, 0, 255) # Red in BGR
        contour_thickness = 1       # Use 1 or 2 pixels
        defects_found = 0
        min_contour_area = 10 # Ignore very small contours (noise)

        for cnt in contours:
             area = cv2.contourArea(cnt)
             if area >= min_contour_area:
                 cv2.drawContours(result_img_bgr, [cnt], -1, contour_color, contour_thickness)
                 defects_found += 1

        print(f"Drew {defects_found} contours (area >= {min_contour_area}) onto the reference image.")

        # 9. Convert the result back to QPixmap (via RGB NumPy)
        result_img_rgb = cv2.cvtColor(result_img_bgr, cv2.COLOR_BGR2RGB)
        result_pixmap = self.numpy_to_qpixmap(result_img_rgb)

        return result_pixmap


# -------------------------------------------------------------
# Point d'entrée (Keep as is)
# -------------------------------------------------------------
if __name__ == "__main__":
    # Ensure Pillow and OpenCV are checked early
    if Image is None:
         print("CRITICAL ERROR: Pillow library not found. Application cannot run.")
         # Show a simple message box if Qt is available
         try:
             app_check = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
             msg_box = QtWidgets.QMessageBox()
             msg_box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
             msg_box.setWindowTitle("Missing Dependency")
             msg_box.setText("The Pillow library is required but not installed.\nPlease install it (e.g., 'pip install Pillow') and restart.")
             msg_box.exec()
         except Exception:
             pass # If Qt itself fails, just exit
         sys.exit(1)


    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    window = ImageComparerApp()
    window.show()
    sys.exit(app.exec())

# --- END OF FILE image_compare.py ---