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

# --- Configuration ---
MAX_IMAGE_DIM_LOAD = 3000
DEFAULT_AB_SWITCH_INTERVAL = 500
MIN_AB_SWITCH_INTERVAL = 100
MAX_AB_SWITCH_INTERVAL = 2000

# -------------------------------------------------------------
# 1) DraggablePixmapItem
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
# 2) Masqué ou non (pour le slider)
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
# 3) InteractiveSliderItem (barre rouge)
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
# 4) ImageViewer
# -------------------------------------------------------------
class ImageViewer(QtWidgets.QGraphicsView):
    viewChanged = Signal()
    mouseMoved = Signal(QtCore.QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
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
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)

        self._zoom = 1.0
        self._panning = False
        self._last_pan_point = QtCore.QPoint()
        self.setMouseTracking(True)

    def set_pixmap(self, pixmap: QtGui.QPixmap):
        if self._pixmap_item:
            if pixmap and not pixmap.isNull():
                current_transform = self.transform()
                was_empty = self._pixmap_item.pixmap().isNull()
                self._pixmap_item.setPixmap(pixmap)
                self._scene.setSceneRect(QtCore.QRectF(pixmap.rect()))
                if was_empty:
                    self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                    self._zoom = self.transform().m11()
                else:
                    self.setTransform(current_transform)
            else:
                self._pixmap_item.setPixmap(QtGui.QPixmap())

    def get_pixmap_item(self):
        return self._pixmap_item

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
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item == self._pixmap_item or item is None:
                self._panning = True
                self._last_pan_point = event.position().toPoint()
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            else:
                self._panning = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        scene_pos = self.mapToScene(event.position().toPoint())
        self.mouseMoved.emit(scene_pos)
        if self._panning:
            delta = event.position().toPoint() - self._last_pan_point
            self._last_pan_point = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.viewChanged.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._panning:
                self._panning = False
                self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def reset_view(self):
        target_item = None
        if (self._pixmap_item and self._pixmap_item.isVisible()
            and not self._pixmap_item.pixmap().isNull()):
            target_item = self._pixmap_item

        if target_item:
            self.fitInView(target_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11()
        else:
            brect = self._scene.itemsBoundingRect()
            if not brect.isEmpty():
                self.fitInView(brect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                self._zoom = self.transform().m11()
        self.viewChanged.emit()

    def get_transform(self):
        return self.transform()

    def set_transform(self, transform: QtGui.QTransform):
        super().setTransform(transform)
        self._zoom = self.transform().m11()


# -------------------------------------------------------------
# 5) Classe Principale (Application)
# -------------------------------------------------------------
class ImageComparerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Comparer - Disable Drag in Slider Mode")
        self.setGeometry(100, 100, 1200, 700)

        # Etat
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
        
        # Options de redimensionnement
        self.size_adjust_mode = "resize2to1"  # Par défaut: redimensionner image 2 vers image 1
        self.size_adjust_options = {
            "resize2to1": "Redimensionner Image 2 → Image 1",
            "resize1to2": "Redimensionner Image 1 → Image 2",
            "resizeboth": "Redimensionner les deux (taille max)",
            "original": "Conserver tailles originales",
            "proportional": "Adapter proportionnellement"
        }

        # Timer A/B
        self.ab_timer = QtCore.QTimer(self)
        self.ab_timer.timeout.connect(self.switch_ab_image)
        self.ab_switch_interval = DEFAULT_AB_SWITCH_INTERVAL
        self.ab_showing_image1 = True

        # Offsets side_by_side
        self._offset_x = 0
        self._offset_y = 0

        # Offsets slider
        self._slider_offset_x = 0.0
        self._slider_offset_y = 0.0

        self.setup_ui()
        self.update_display()

    def setup_ui(self):
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QVBoxLayout(main_widget)

        control_panel = QtWidgets.QFrame()
        control_panel.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        control_layout = QtWidgets.QHBoxLayout(control_panel)
        main_layout.addWidget(control_panel)

        # Chargement
        load_group = QtWidgets.QWidget()
        load_layout = QtWidgets.QVBoxLayout(load_group)
        btn_load1 = QtWidgets.QPushButton("Load Image 1")
        btn_load1.clicked.connect(lambda: self.load_image(1))
        self.lbl_img1 = QtWidgets.QLabel("No Image 1")
        self.lbl_img1.setWordWrap(True)

        btn_load2 = QtWidgets.QPushButton("Load Image 2")
        btn_load2.clicked.connect(lambda: self.load_image(2))
        self.lbl_img2 = QtWidgets.QLabel("No Image 2")
        self.lbl_img2.setWordWrap(True)

        load_layout.addWidget(btn_load1)
        load_layout.addWidget(self.lbl_img1)
        load_layout.addStretch()
        load_layout.addWidget(btn_load2)
        load_layout.addWidget(self.lbl_img2)
        control_layout.addWidget(load_group)

        # Modes
        mode_group = QtWidgets.QFrame()
        mode_group.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        mode_layout = QtWidgets.QGridLayout(mode_group)
        control_layout.addWidget(mode_group, 1)

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
        self.radio_ab_switch.toggled.connect(lambda c:
        self.set_mode("ab_switch") if c else None)
        mode_layout.addWidget(self.radio_ab_switch, 1, 2)
        self.options_stack = QtWidgets.QStackedWidget()
        mode_layout.addWidget(self.options_stack, 3, 0, 1, 3)
        self.options_stack.addWidget(QtWidgets.QWidget())  # Page Vide

        # Page A/B switch
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
        self.options_stack.addWidget(ab_switch_widget)

        # Options d'ajustement
        adjust_group = QtWidgets.QWidget()
        adjust_layout = QtWidgets.QVBoxLayout(adjust_group)
        adjust_label = QtWidgets.QLabel("<b>Ajustement de taille:</b>")
        adjust_layout.addWidget(adjust_label)
        
        self.combo_size_adjust = QtWidgets.QComboBox()
        for key, label in self.size_adjust_options.items():
            self.combo_size_adjust.addItem(label, key)
        self.combo_size_adjust.setCurrentText(self.size_adjust_options[self.size_adjust_mode])
        self.combo_size_adjust.currentIndexChanged.connect(self.on_size_adjust_changed)
        adjust_layout.addWidget(self.combo_size_adjust)
        
        control_layout.addWidget(adjust_group)

        # Vue
        view_group = QtWidgets.QWidget()
        view_layout = QtWidgets.QVBoxLayout(view_group)
        self.check_link_views = QtWidgets.QCheckBox("Link Views")
        self.check_link_views.setChecked(self.link_views_enabled)
        self.check_link_views.toggled.connect(self.on_link_views_toggled)
        view_layout.addWidget(self.check_link_views)
        view_layout.addStretch()
        btn_reset_view = QtWidgets.QPushButton("Reset View")
        btn_reset_view.clicked.connect(self.reset_all_views)
        view_layout.addWidget(btn_reset_view)
        control_layout.addWidget(view_group)

        # Zone d'affichage
        self.view1 = ImageViewer()
        self.view2 = ImageViewer()
        self.view_combined = ImageViewer()

        self.view_stack = QtWidgets.QStackedWidget()
        side_by_side_widget = QtWidgets.QWidget()
        side_by_side_layout = QtWidgets.QHBoxLayout(side_by_side_widget)
        side_by_side_layout.setContentsMargins(0, 0, 0, 0)
        side_by_side_layout.setSpacing(1)
        side_by_side_layout.addWidget(self.view1)
        side_by_side_layout.addWidget(self.view2)
        self.view_stack.addWidget(side_by_side_widget)  # index 0
        self.view_stack.addWidget(self.view_combined)    # index 1
        main_layout.addWidget(self.view_stack, 1)

        # Signaux
        self.view1.viewChanged.connect(lambda: self.sync_views(self.view1))
        self.view2.viewChanged.connect(lambda: self.sync_views(self.view2))
        self.view1.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 1))
        self.view2.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 2))
        self.view_combined.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 0))

        # Items slider/AB
        scn = self.view_combined.scene()
        self.item1 = MaskedOrFullPixmapItem(controller=self, item_id=1, is_left=True)
        self.item2 = MaskedOrFullPixmapItem(controller=self, item_id=2, is_left=False)
        self.item1.setVisible(False)
        self.item2.setVisible(False)
        scn.addItem(self.item1)
        scn.addItem(self.item2)

        # Barre slider
        self.interactive_slider = InteractiveSliderItem(self.view_combined.sceneRect())
        self.interactive_slider.signals.positionChanged.connect(self.on_slider_ratio_update)
        self.interactive_slider.setVisible(False)
        scn.addItem(self.interactive_slider)

        # Barre de statut
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
    # Désactivation / Activation du drag sur un item
    # -----------------------------------------------------------
    def disable_drag_for_slider(self, item: QtWidgets.QGraphicsPixmapItem):
        """
        Retire le flag 'ItemIsMovable' pour empêcher le déplacement de l'image
        lorsque nous sommes en mode slider.
        """
        old_flags = item.flags()
        new_flags = old_flags & ~QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        item.setFlags(new_flags)

    def enable_drag(self, item: QtWidgets.QGraphicsPixmapItem):
        """
        Rétablit le flag 'ItemIsMovable' pour autoriser le drag.
        """
        old_flags = item.flags()
        new_flags = old_flags | QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable
        item.setFlags(new_flags)    # -----------------------------------------------------------
    # Changement de mode
    # -----------------------------------------------------------
    def set_mode(self, mode):
        if self.current_mode != mode:
            prev_mode = self.current_mode
            self.current_mode = mode
            print(f"Mode changed to: {mode}")
            
            # Nettoyer les éléments spécifiques au mode précédent
            if prev_mode == "slider":
                # Réinitialiser les propriétés du mode slider pour éviter des résidus visuels
                self.item1.set_use_mask(False)
                self.item2.set_use_mask(False)
                self.item1.setOpacity(1.0)
                self.item2.setOpacity(1.0)
                # S'assurer que l'élément standard est propre
                self.view_combined.get_pixmap_item().setPixmap(QtGui.QPixmap())
                
            if prev_mode == "ab_switch":
                self.ab_timer.stop()
                print("A/B Timer stopped.")
                # Désactiver le mode de recalage
                self._ab_recalage_actif = False
                # Réinitialiser les éléments pour s'assurer qu'ils sont dans un état connu
                self.item1.setOpacity(1.0)
                self.item2.setOpacity(1.0)
                self.item1.setVisible(False)
                self.item2.setVisible(False)
                self.view_combined.get_pixmap_item().setPixmap(QtGui.QPixmap())
                
            if mode == "ab_switch":
                self.options_stack.setCurrentIndex(1)
                # S'assurer de démarrer en mode standard (non recalé)
                self._ab_recalage_actif = False
            else:
                self.options_stack.setCurrentIndex(0)
                
            self.update_display()
    def on_ab_speed_changed(self, value):
        self.ab_switch_interval = value
        self.lbl_ab_speed_value.setText(str(value))
        if self.ab_timer.isActive():
            self.ab_timer.setInterval(self.ab_switch_interval)
            print(f"A/B Timer updated to: {self.ab_switch_interval} ms")

    def on_link_views_toggled(self, checked):
        self.link_views_enabled = checked
        print(f"Link Views -> {checked}")

        if self.current_mode == "slider":
            if checked:
                # Capture précise de l'offset actuel entre les images
                x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                x2, y2 = self.item2.pos().x(), self.item2.pos().y()
                self._slider_offset_x = x2 - x1
                self._slider_offset_y = y2 - y1
                
                # Force la synchronisation immédiate des positions
                self.move_pixmap_item(1, 0, 0)
                
                if self.interactive_slider:
                    # Mise à jour du rectangle de scène pour le slider
                    w1 = self.item1.pixmap().width()
                    h1 = self.item1.pixmap().height()
                    self.interactive_slider.set_scene_rect(QtCore.QRectF(x1, y1, w1, h1))
                    current_ratio = self.interactive_slider.get_position_ratio()
                    self.interactive_slider.set_position_ratio(current_ratio)
    
        elif self.current_mode == "ab_switch":
            if checked:
                # Capturer la position relative actuelle
                x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                x2, y2 = self.item2.pos().x(), self.item2.pos().y()
                self._slider_offset_x = x2 - x1
                self._slider_offset_y = y2 - y1
                
                # Réinitialiser l'affichage avec la position de l'image 1
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                standard_pixmap_item.setPixmap(self.display_pixmap1)
                standard_pixmap_item.setPos(x1, y1)
                
                # Masquer les items de recalage
                self.item1.setVisible(False)
                self.item2.setVisible(False)
                
                # Redémarrer le timer
                self.ab_showing_image1 = True
                if not self.ab_timer.isActive():
                    self.ab_timer.start()
            else:
                # Arrêter le timer
                self.ab_timer.stop()
                
                # Préparer pour le recalage manuel
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                standard_pixmap_item.setPixmap(QtGui.QPixmap())
                
                # Afficher les deux images pour le recalage
                self.item1.setPixmap(self.display_pixmap1)
                self.item2.setPixmap(self.display_pixmap2)
                self.item1.setVisible(True)
                self.item2.setVisible(True)
                self.item1.setOpacity(0.5)
                self.item2.setOpacity(0.5)

    def on_slider_ratio_update(self, ratio: float):
        if self.current_mode == "slider":
            self.item1.set_slider_ratio(ratio)
            self.item2.set_slider_ratio(ratio)
            # S'assurer que la ligne est toujours à la bonne position par rapport aux items
            if self.interactive_slider:
                # Recalculer le rectangle de scène basé sur les positions actuelles des items
                x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                w1 = self.item1.pixmap().width()
                h1 = self.item1.pixmap().height()
                self.interactive_slider.set_scene_rect(QtCore.QRectF(x1, y1, w1, h1))
    
    def switch_ab_image(self):
        if self.current_mode != "ab_switch":
            self.ab_timer.stop()
            return
        
        if not self.display_pixmap1 or not self.display_pixmap2:
            self.ab_timer.stop()
            return
        
        self.ab_showing_image1 = not self.ab_showing_image1
        pixmap_to_show = self.display_pixmap1 if self.ab_showing_image1 else self.display_pixmap2
        
        if pixmap_to_show and not pixmap_to_show.isNull():
            standard_pixmap_item = self.view_combined.get_pixmap_item()
            standard_pixmap_item.setPixmap(pixmap_to_show)
            
            if self.link_views_enabled:
                # Appliquer l'offset selon l'image affichée
                base_pos = standard_pixmap_item.pos()
                if not self.ab_showing_image1:
                    standard_pixmap_item.setPos(
                        base_pos.x() + self._slider_offset_x,
                        base_pos.y() + self._slider_offset_y
                    )
                else:
                    standard_pixmap_item.setPos(
                        base_pos.x() - self._slider_offset_x,
                        base_pos.y() - self._slider_offset_y
                    )
        else:
            self.ab_timer.stop()
            print("Warning: A/B switch stopped due to invalid pixmap.")

    # -----------------------------------------------------------
    # Chargement d'images
    # -----------------------------------------------------------
    def load_image(self, image_num):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Select Image {image_num}", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;All Files (*)"
        )
        if not filepath:
            return
        try:
            img = Image.open(filepath)
            if max(img.width, img.height) > MAX_IMAGE_DIM_LOAD:
                img.thumbnail((MAX_IMAGE_DIM_LOAD, MAX_IMAGE_DIM_LOAD), Image.Resampling.LANCZOS)
                print(f"Image {image_num} resized")
            pil_img_conv = img.convert("RGBA") if 'A' in img.getbands() else img.convert("RGB")
            qt_pixmap = self.pil_to_qpixmap(pil_img_conv)

            if image_num == 1:
                self.image_path1 = filepath
                self.pil_image1_orig = pil_img_conv
                self.qt_pixmap1_orig = qt_pixmap
                self.lbl_img1.setText(os.path.basename(filepath))
            else:
                self.image_path2 = filepath
                self.pil_image2_orig = pil_img_conv
                self.qt_pixmap2_orig = qt_pixmap
                self.lbl_img2.setText(os.path.basename(filepath))

            print(f"Loaded Image {image_num}: {filepath} ({pil_img_conv.width}x{pil_img_conv.height})")
            self.update_display()

            if self.current_mode == "side_by_side":
                if image_num == 1:
                    self.view1.reset_view()
                else:
                    self.view2.reset_view()
            else:
                self.view_combined.reset_view()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error Loading Image", f"Could not load image:\n{e}")
            if image_num == 1:
                self.image_path1 = None
                self.pil_image1_orig = None
                self.qt_pixmap1_orig = None
                self.lbl_img1.setText("No Image 1")
            else:
                self.image_path2 = None
                self.pil_image2_orig = None
                self.qt_pixmap2_orig = None
                self.lbl_img2.setText("No Image 2")
            self.update_display()

    def pil_to_qpixmap(self, pil_image):
        if pil_image is None:
            return QtGui.QPixmap()
        try:
            if pil_image.mode not in ["RGB", "RGBA"]:
                pil_image = pil_image.convert("RGB")
            if ImageQt:
                qimage = ImageQt.ImageQt(pil_image)
                if isinstance(qimage, QtGui.QImage):
                    return QtGui.QPixmap.fromImage(qimage)
                else:
                    return QtGui.QPixmap(qimage)
            else:
                print("Warning: ImageQt not available, using fallback conversion.")
                from PIL import Image
                if pil_image.mode == "RGB":
                    data = pil_image.tobytes("raw", "RGB")
                    qimg = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGB888)
                elif pil_image.mode == "RGBA":
                    data = pil_image.tobytes("raw", "RGBA")
                    qimg = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGBA8888)
                else:
                    return QtGui.QPixmap()
                return QtGui.QPixmap.fromImage(qimg)
        except Exception as e:
            print(f"Error converting PIL to QPixmap: {e}")
            return QtGui.QPixmap()

    # -----------------------------------------------------------
    # Mises à jour d'affichage
    # -----------------------------------------------------------
    def update_display(self):
        print(f"Updating display for mode: {self.current_mode}")
        if self.ab_timer.isActive():
            self.ab_timer.stop()

        # Cacher slider par défaut
        self.interactive_slider.setVisible(False)
        self.item1.setVisible(False)
        self.item2.setVisible(False)

        # Charger les images prêtes
        self.prepare_display_images()

        # Activer la vue correspondante
        if self.current_mode == "side_by_side":
            self.view_stack.setCurrentIndex(0)
            self.view1.set_pixmap(self.display_pixmap1)
            self.view2.set_pixmap(self.display_pixmap2)
            # Réactiver le drag si on veut
            self.enable_drag(self.item1)
            self.enable_drag(self.item2)
            if self.link_views_enabled:
                self.sync_views(self.view1, force_sync=True)

        else:
            self.view_stack.setCurrentIndex(1)
            self.item1.setPixmap(self.display_pixmap1 if self.display_pixmap1 else QtGui.QPixmap())
            self.item2.setPixmap(self.display_pixmap2 if self.display_pixmap2 else QtGui.QPixmap())
            self.item1.setPos(0, 0)
            self.item2.setPos(0, 0)

            w1 = self.item1.pixmap().width()
            h1 = self.item1.pixmap().height()
            w2 = self.item2.pixmap().width()
            h2 = self.item2.pixmap().height()
            scene_w = max(w1, w2)
            scene_h = max(h1, h2)
            self.view_combined.setSceneRect(0, 0, scene_w, scene_h)

            if self.current_mode == "slider":
                # Désactiver le drag des images
                self.disable_drag_for_slider(self.item1)
                self.disable_drag_for_slider(self.item2)

                # Effacer l'image standard qui pourrait rester du mode A/B switch
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                standard_pixmap_item.setPixmap(QtGui.QPixmap())

                self.item1.set_use_mask(True)
                self.item2.set_use_mask(True)
                self.item1.setVisible(True)
                self.item2.setVisible(True)
                self.interactive_slider.setVisible(True)
                self.interactive_slider.set_scene_rect(QtCore.QRectF(0, 0, scene_w, scene_h))
                ratio = self.interactive_slider.get_position_ratio()
                self.on_slider_ratio_update(ratio)            
            elif self.current_mode == "ab_switch":
                # Mode A/B Switch - utiliser l'élément pixmap standard
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                self.item1.setVisible(False)
                self.item2.setVisible(False)
                
                if self.display_pixmap1 and not self.display_pixmap1.isNull() and self.display_pixmap2 and not self.display_pixmap2.isNull():
                    self.ab_showing_image1 = True
                    initial_pixmap = self.display_pixmap1
                    standard_pixmap_item.setPixmap(initial_pixmap)
                    self.ab_timer.setInterval(self.ab_switch_interval)
                    self.ab_timer.start()
                    print(f"A/B Timer started: {self.ab_switch_interval} ms")
                elif self.display_pixmap1 and not self.display_pixmap1.isNull():
                    standard_pixmap_item.setPixmap(self.display_pixmap1)
                    print("A/B Switch: Only image 1 available.")
                elif self.display_pixmap2 and not self.display_pixmap2.isNull():
                    standard_pixmap_item.setPixmap(self.display_pixmap2)
                    print("A/B Switch: Only image 2 available.")
                else:
                    standard_pixmap_item.setPixmap(QtGui.QPixmap())
                    print("A/B Switch: No images available.")

            self.view_combined.reset_view()
    
    def prepare_display_images(self):
        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig
        self.display_pixmap1 = self.qt_pixmap1_orig if self.qt_pixmap1_orig else QtGui.QPixmap()
        self.display_pixmap2 = self.qt_pixmap2_orig if self.qt_pixmap2_orig else QtGui.QPixmap()

        # Si l'une des images est manquante ou si elles ont la même taille, pas besoin d'ajuster
        if not pil1 or not pil2 or pil1.size == pil2.size:
            return

        adjust_mode = self.size_adjust_mode
        print(f"Ajustement de taille: {adjust_mode}")
        
        # Redimensionner selon le mode sélectionné
        if adjust_mode == "resize2to1":
            # Redimensionner l'image 2 à la taille de l'image 1 (comportement par défaut)
            print(f"Redimensionnement de l'image 2 ({pil2.width}x{pil2.height}) → image 1 ({pil1.width}x{pil1.height})")
            pil2_resized = pil2.resize(pil1.size, Image.Resampling.LANCZOS)
            self.display_pixmap2 = self.pil_to_qpixmap(pil2_resized)

        elif adjust_mode == "resize1to2":
            # Redimensionner l'image 1 à la taille de l'image 2
            print(f"Redimensionnement de l'image 1 ({pil1.width}x{pil1.height}) → image 2 ({pil2.width}x{pil2.height})")
            pil1_resized = pil1.resize(pil2.size, Image.Resampling.LANCZOS)
            self.display_pixmap1 = self.pil_to_qpixmap(pil1_resized)

        elif adjust_mode == "resizeboth":
            # Redimensionner les deux images à la taille maximale
            max_width = max(pil1.width, pil2.width)
            max_height = max(pil1.height, pil2.height)
            new_size = (max_width, max_height)
            
            print(f"Redimensionnement des deux images à la taille maximale: {max_width}x{max_height}")
            if pil1.size != new_size:
                pil1_resized = pil1.resize(new_size, Image.Resampling.LANCZOS)
                self.display_pixmap1 = self.pil_to_qpixmap(pil1_resized)
            
            if pil2.size != new_size:
                pil2_resized = pil2.resize(new_size, Image.Resampling.LANCZOS)
                self.display_pixmap2 = self.pil_to_qpixmap(pil2_resized)

        elif adjust_mode == "proportional":
            # Adapter proportionnellement (préserver le ratio)
            w1, h1 = pil1.size
            w2, h2 = pil2.size
            
            # Trouver le ratio commun en conservant l'aspect ratio des deux images
            ratio1 = w1 / h1
            ratio2 = w2 / h2
            
            # Calcul des nouvelles dimensions pour que les deux images aient des tailles compatibles
            # tout en préservant leurs proportions
            if ratio1 > ratio2:  # Image 1 plus large proportionnellement
                new_h2 = h2
                new_w2 = int(h2 * ratio1)
                new_h1 = h1
                new_w1 = w1
            else:  # Image 2 plus large proportionnellement
                new_h1 = h1
                new_w1 = int(h1 * ratio2)
                new_h2 = h2
                new_w2 = w2
                
            print(f"Adaptation proportionnelle: Image 1 → {new_w1}x{new_h1}, Image 2 → {new_w2}x{new_h2}")
            
            # Redimensionner uniquement si la taille a changé
            if (w1, h1) != (new_w1, new_h1):
                pil1_resized = pil1.resize((new_w1, new_h1), Image.Resampling.LANCZOS)
                self.display_pixmap1 = self.pil_to_qpixmap(pil1_resized)
                
            if (w2, h2) != (new_w2, new_h2):
                pil2_resized = pil2.resize((new_w2, new_h2), Image.Resampling.LANCZOS)
                self.display_pixmap2 = self.pil_to_qpixmap(pil2_resized)
                
        # Pour le mode "original", on ne fait rien car on veut garder les tailles originales

    def update_comparison_image(self):
        if self.current_mode != "opacity":
            self.comparison_pixmap = None
            return
        if not self.pil_image1_orig and not self.pil_image2_orig:
            self.comparison_pixmap = None
            return

        from PIL import Image
        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig
        if pil1 and pil2:
            try:
                im1 = pil1.convert("RGB")
                im2 = pil2.convert("RGB")
                alpha = self.opacity_value
                result = Image.blend(im1, im2, alpha)
                self.comparison_pixmap = self.pil_to_qpixmap(result)
            except Exception as e:
                print(f"Error blending: {e}")
                self.comparison_pixmap = None
        elif pil1:
            self.comparison_pixmap = self.pil_to_qpixmap(pil1)
        elif pil2:
            self.comparison_pixmap = self.pil_to_qpixmap(pil2)

    def reset_all_views(self):
        if self.current_mode == "side_by_side":
            self.view1.reset_view()
            self.view2.reset_view()
        else:
            self.view_combined.reset_view()

        if self.interactive_slider:
            self.interactive_slider.set_position_ratio(0.5)
            if self.current_mode == "slider":
                self.on_slider_ratio_update(0.5)   
    def move_pixmap_item(self, item_id: int, dx: float, dy: float):
        if self.current_mode not in ("slider", "ab_switch"):
            return

        needs_slider_update = (self.current_mode == "slider")

        if not self.link_views_enabled:
            # En mode slider sans Link Views, on ne permet que le déplacement vertical
            if self.current_mode == "slider":
                dx = 0  # Ignorer le déplacement horizontal
            
            # Déplacer seulement l'item cliqué
            if item_id == 1:
                p1 = self.item1.pos()
                self.item1.setPos(p1.x() + dx, p1.y() + dy)
            else:
                p2 = self.item2.pos()
                self.item2.setPos(p2.x() + dx, p2.y() + dy)
        else:
            # LinkViews => maintien précis de l'offset
            if item_id == 1:
                p1 = self.item1.pos()
                newp1 = QtCore.QPointF(p1.x() + dx, p1.y() + dy)
                self.item1.setPos(newp1)
                # Utilisation directe des coordonnées pour plus de précision
                self.item2.setPos(newp1.x() + self._slider_offset_x,
                                newp1.y() + self._slider_offset_y)
            else:
                p2 = self.item2.pos()
                newp2 = QtCore.QPointF(p2.x() + dx, p2.y() + dy)
                self.item2.setPos(newp2)
                # Utilisation directe des coordonnées pour plus de précision
                self.item1.setPos(newp2.x() - self._slider_offset_x,
                                newp2.y() - self._slider_offset_y)

        # Mise à jour du slider si nécessaire
        if needs_slider_update and self.interactive_slider:
            x1, y1 = self.item1.pos().x(), self.item1.pos().y()
            w1 = self.item1.pixmap().width()
            h1 = self.item1.pixmap().height()
            current_ratio = self.interactive_slider.get_position_ratio()
            self.interactive_slider.set_scene_rect(QtCore.QRectF(x1, y1, w1, h1))
            self.interactive_slider.set_position_ratio(current_ratio)

    def sync_views(self, source_view, force_sync=False):
        if self._is_updating_views or self.current_mode != "side_by_side":
            return
        self._is_updating_views = True

        if not self.link_views_enabled:
            h1 = self.view1.horizontalScrollBar().value()
            v1 = self.view1.verticalScrollBar().value()
            h2 = self.view2.horizontalScrollBar().value()
            v2 = self.view2.verticalScrollBar().value()
            self._offset_x = h2 - h1
            self._offset_y = v2 - v1
            self._is_updating_views = False
            return

        target_view = self.view2 if source_view == self.view1 else self.view1
        target_view.set_transform(source_view.get_transform())

        s_hmax = source_view.horizontalScrollBar().maximum()
        s_vmax = source_view.verticalScrollBar().maximum()
        target_view.horizontalScrollBar().setMaximum(s_hmax)
        target_view.verticalScrollBar().setMaximum(s_vmax)

        s_hval = source_view.horizontalScrollBar().value()
        s_vval = source_view.verticalScrollBar().value()

        if source_view == self.view1:
            new_h = s_hval + self._offset_x
            new_v = s_vval + self._offset_y
        else:
            new_h = s_hval - self._offset_x
            new_v = s_vval - self._offset_y

        target_view.horizontalScrollBar().setValue(new_h)
        target_view.verticalScrollBar().setValue(new_v)

        self._is_updating_views = False

    def update_status_bar(self, scene_pos, view_index):
        pix_item = None
        if view_index == 1 and self.current_mode == "side_by_side":
            pix_item = self.view1.get_pixmap_item()
        elif view_index == 2 and self.current_mode == "side_by_side":
            pix_item = self.view2.get_pixmap_item()
        elif view_index == 0 and self.current_mode != "side_by_side":
            if self.current_mode in ("slider", "ab_switch"):
                # On affiche la position sur l'item visible
                if self.item1.isVisible():
                    pix_item = self.item1
                else:
                    pix_item = self.item2
            else:
                pix_item = self.view_combined.get_pixmap_item()

        coords_text = "Coords: (N/A)"
        rgb_text = "RGB: (N/A)"

        if pix_item and isinstance(pix_item, QtWidgets.QGraphicsPixmapItem):
            pm = pix_item.pixmap()
            if not pm.isNull():
                item_pt = pix_item.mapFromScene(scene_pos)
                ix, iy = int(item_pt.x()), int(item_pt.y())
                w, h = pm.width(), pm.height()
                if 0 <= ix < w and 0 <= iy < h:
                    coords_text = f"Coords: ({ix},{iy}) / ({w}x{h})"
                    qimg = pm.toImage()
                    if qimg.valid(ix, iy):
                        c = QtGui.QColor(qimg.pixel(ix, iy))
                        rgb_text = f"RGB: ({c.red()},{c.green()},{c.blue()})"
                    else:
                        rgb_text = "RGB: (Invalid)"
                else:
                    coords_text = f"Coords: (N/A) / ({w}x{h})"

        self.lbl_status_coords.setText(coords_text)
        self.lbl_status_rgb.setText(rgb_text)

    def on_size_adjust_changed(self, index):
        """Gère le changement de méthode d'ajustement de taille."""
        key = self.combo_size_adjust.itemData(index)
        if key != self.size_adjust_mode:
            self.size_adjust_mode = key
            print(f"Mode d'ajustement changé: {self.size_adjust_mode}")
            self.update_display()

    def create_ab_blend_image(self):
        """Crée une image combinée avec 50% de transparence pour chaque image."""
        if not self.pil_image1_orig or not self.pil_image2_orig:
            return None
            
        from PIL import Image
        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig
        
        try:
            # On utilise déjà les images préparées qui ont été ajustées selon l'option d'ajustement de taille
            im1 = self.pil_to_qimage(self.display_pixmap1).convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
            im2 = self.pil_to_qimage(self.display_pixmap2).convertToFormat(QtGui.QImage.Format.Format_RGBA8888)
            
            # Créer un QImage résultat avec le même format
            width = im1.width()
            height = im1.height()
            result = QtGui.QImage(width, height, QtGui.QImage.Format.Format_RGBA8888)
            
            # Mélanger les deux images pixel par pixel avec 50% de transparence
            for y in range(height):
                for x in range(width):
                    color1 = QtGui.QColor(im1.pixel(x, y))
                    color2 = QtGui.QColor(im2.pixel(x, y))
                    
                    # Mélange à 50/50
                    r = int((color1.red() + color2.red()) / 2)
                    g = int((color1.green() + color2.green()) / 2)
                    b = int((color1.blue() + color2.blue()) / 2)
                    a = int((color1.alpha() + color2.alpha()) / 2)
                    
                    result.setPixelColor(x, y, QtGui.QColor(r, g, b, a))
            
            return QtGui.QPixmap.fromImage(result)
        except Exception as e:
            print(f"Erreur lors de la création de l'image combinée: {e}")
            return None
            
    def pil_to_qimage(self, pixmap):
        """Convertit un QPixmap en QImage."""
        if pixmap.isNull():
            return QtGui.QImage()
        return pixmap.toImage()


# -------------------------------------------------------------
# Point d'entrée
# -------------------------------------------------------------
if __name__ == "__main__":
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    window = ImageComparerApp()
    window.show()
    sys.exit(app.exec())
