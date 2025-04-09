import sys
import os
import numpy as np
# Utiliser PySide6
from PySide6 import QtCore, QtGui, QtWidgets
# Importer Signal explicitement
from PySide6.QtCore import Signal

# Try importing ImageQt
try:
    from PIL import ImageQt
except ImportError:
    print("Warning: PIL.ImageQt not found directly. Ensure Pillow is up-to-date.")
    ImageQt = None

from PIL import Image, ImageOps

# --- Configuration ---
MAX_IMAGE_DIM_LOAD = 3000
DEFAULT_AB_SWITCH_INTERVAL = 500 # Millisecondes
MIN_AB_SWITCH_INTERVAL = 100
MAX_AB_SWITCH_INTERVAL = 2000

# --- Custom Graphics View ---
# (ImageViewer reste identique)
class ImageViewer(QtWidgets.QGraphicsView):
    viewChanged = Signal()
    mouseMoved = Signal(QtCore.QPointF)
    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem() # Item standard pour les modes simples
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)
        self.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QtGui.QBrush(QtGui.QColor(70, 70, 70)))
        self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)
        self._zoom = 1.0; self._panning = False; self._last_pan_point = QtCore.QPoint()
        self.setMouseTracking(True)
    def set_pixmap(self, pixmap): # Met à jour l'item standard
        if self._pixmap_item: # Vérifier si l'item existe
            if pixmap and not pixmap.isNull():
                current_transform = self.transform()
                is_empty = self._pixmap_item.pixmap().isNull()
                self._pixmap_item.setPixmap(pixmap)
                self._scene.setSceneRect(QtCore.QRectF(pixmap.rect())) # Ajuster la scène à cet item
                if is_empty:
                     self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                     self._zoom = self.transform().m11()
                else: self.setTransform(current_transform)
            else:
                self._pixmap_item.setPixmap(QtGui.QPixmap())
                # Ne pas réinitialiser sceneRect ici si d'autres items (comme CombinedSliderItem) existent
                # self._scene.setSceneRect(QtCore.QRectF())
    def get_pixmap_item(self): return self._pixmap_item
    def wheelEvent(self, event: QtGui.QWheelEvent):
        zoom_factor = 1.15
        if event.angleDelta().y() > 0: self.scale(zoom_factor, zoom_factor); self._zoom *= zoom_factor
        else: self.scale(1 / zoom_factor, 1 / zoom_factor); self._zoom /= zoom_factor
        self.viewChanged.emit()
    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
             item = self.itemAt(event.position().toPoint())
             # Permettre le pan si on clique sur le fond ou l'item pixmap standard
             # Ne pas panner si on clique sur un autre item (slider, combined item)
             if item == self._pixmap_item or isinstance(item, CombinedSliderItem) or item is None:
                 # Correction: Ne panner que si on clique sur le fond ou l'item standard
                 if item == self._pixmap_item or item is None:
                     self._panning = True
                     self._last_pan_point = event.position().toPoint()
                     self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
                 else: # Clic sur CombinedSliderItem ou InteractiveSliderItem
                      self._panning = False
             else: # Clic sur un autre item (InteractiveSliderItem)
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
            if self._panning: self._panning = False; self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)
    def reset_view(self):
        # Ajuster la vue sur l'item actuellement visible et pertinent
        target_item = None
        if self._pixmap_item and self._pixmap_item.isVisible() and not self._pixmap_item.pixmap().isNull():
            target_item = self._pixmap_item
        else:
            # Chercher le CombinedSliderItem s'il existe et est visible
            for item in self._scene.items():
                if isinstance(item, CombinedSliderItem) and item.isVisible():
                    target_item = item
                    break
        if target_item:
            self.fitInView(target_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11(); self.viewChanged.emit()
    def get_transform(self) -> QtGui.QTransform: return self.transform()
    def set_transform(self, transform: QtGui.QTransform): super().setTransform(transform); self._zoom = self.transform().m11()

# --- Custom Slider Item ---
# (InteractiveSliderItem reste identique à la version précédente)
class InteractiveSliderItem(QtWidgets.QGraphicsLineItem):
    class Signals(QtCore.QObject):
        positionChanged = Signal(float)
    def __init__(self, scene_rect: QtCore.QRectF, parent=None):
        super().__init__(parent)
        self.scene_rect = scene_rect; self._position = 0.5; self.signals = self.Signals()
        self.positionChanged = self.signals.positionChanged; self._is_dragging = False
        pen = QtGui.QPen(QtCore.Qt.GlobalColor.red, 2, QtCore.Qt.PenStyle.SolidLine); self.setPen(pen)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor); self.setPos(QtCore.QPointF(0, 0))
        self.update_line_geometry(); self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton: self._is_dragging = True; event.accept()
        super().mousePressEvent(event)
    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if self._is_dragging:
            scene_x = event.scenePos().x(); min_x = self.scene_rect.left(); max_x = self.scene_rect.right()
            if max_x < min_x: max_x = min_x
            constrained_x = max(min_x, min(scene_x, max_x)); scene_width = self.scene_rect.width()
            new_position_ratio = (constrained_x - min_x) / scene_width if scene_width > 0 else 0.5
            if not np.isclose(new_position_ratio, self._position):
                self._position = new_position_ratio; self.update_line_geometry(); self.signals.positionChanged.emit(self._position)
            event.accept()
        super().mouseMoveEvent(event)
    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False; print("Slider released."); event.accept()
        super().mouseReleaseEvent(event)
    def update_line_geometry(self):
        x = self.scene_rect.left() + self.scene_rect.width() * self._position
        self.setLine(x, self.scene_rect.top(), x, self.scene_rect.bottom())
        if self.pos() != QtCore.QPointF(0, 0): self.setPos(QtCore.QPointF(0, 0))
    def set_scene_rect(self, rect: QtCore.QRectF): self.scene_rect = rect; self.update_line_geometry()
    def set_position_ratio(self, ratio):
        new_pos = max(0.0, min(1.0, ratio))
        if not np.isclose(new_pos, self._position): self._position = new_pos; self.update_line_geometry()
    def get_position_ratio(self): return self._position
    def itemChange(self, change: QtWidgets.QGraphicsItem.GraphicsItemChange, value):
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionChange: return QtCore.QPointF(0, 0)
        return super().itemChange(change, value)


# --- NOUVEL ITEM GRAPHIQUE pour le rendu Slider ---
class CombinedSliderItem(QtWidgets.QGraphicsItem):
    """ Item qui dessine deux pixmaps côte à côte séparés par un ratio. """
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap1 = QtGui.QPixmap()
        self._pixmap2 = QtGui.QPixmap()
        self._ratio = 0.5
        self._bounding_rect = QtCore.QRectF()

    def set_data(self, pixmap1: QtGui.QPixmap, pixmap2: QtGui.QPixmap, ratio: float):
        """ Met à jour les pixmaps sources et le ratio. """
        # print(f"CombinedSliderItem: Updating data - Ratio: {ratio}")
        ratio_changed = not np.isclose(self._ratio, ratio)
        pixmap1_changed = pixmap1.cacheKey() != self._pixmap1.cacheKey()
        pixmap2_changed = pixmap2.cacheKey() != self._pixmap2.cacheKey()

        if ratio_changed or pixmap1_changed or pixmap2_changed:
            self.prepareGeometryChange() # Nécessaire si le boundingRect change

            self._pixmap1 = pixmap1 if pixmap1 else QtGui.QPixmap()
            self._pixmap2 = pixmap2 if pixmap2 else QtGui.QPixmap()
            self._ratio = max(0.0, min(1.0, ratio))

            # Mettre à jour le boundingRect basé sur la taille de pixmap1 (ou pixmap2 si 1 est nulle)
            if not self._pixmap1.isNull():
                self._bounding_rect = QtCore.QRectF(self._pixmap1.rect())
            elif not self._pixmap2.isNull():
                self._bounding_rect = QtCore.QRectF(self._pixmap2.rect())
            else:
                self._bounding_rect = QtCore.QRectF()

            self.update() # Demander un redessin

    def boundingRect(self) -> QtCore.QRectF:
        """ Retourne le rectangle englobant l'item. """
        return self._bounding_rect

    def paint(self, painter: QtGui.QPainter, option: QtWidgets.QStyleOptionGraphicsItem, widget: QtWidgets.QWidget = None):
        """ Dessine les portions des deux pixmaps. """
        if self._bounding_rect.isEmpty():
            return

        width = self._bounding_rect.width()
        height = self._bounding_rect.height()
        split_x = width * self._ratio

        # --- Dessiner Pixmap 1 (partie gauche) ---
        if not self._pixmap1.isNull():
            source_rect1 = QtCore.QRectF(0, 0, split_x, height)
            target_rect1 = QtCore.QRectF(0, 0, split_x, height)
            # Vérifier si les rectangles sont valides avant de dessiner
            if source_rect1.isValid() and target_rect1.isValid() and source_rect1.width() > 0:
                 painter.drawPixmap(target_rect1, self._pixmap1, source_rect1)

        # --- Dessiner Pixmap 2 (partie droite) ---
        if not self._pixmap2.isNull():
            source_rect2 = QtCore.QRectF(split_x, 0, width - split_x, height)
            target_rect2 = QtCore.QRectF(split_x, 0, width - split_x, height)
            # Vérifier si les rectangles sont valides avant de dessiner
            if source_rect2.isValid() and target_rect2.isValid() and source_rect2.width() > 0:
                 painter.drawPixmap(target_rect2, self._pixmap2, source_rect2)


# --- Classe Principale de l'Application ---
class ImageComparerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Comparer (PySide6 Replica)")
        self.setGeometry(100, 100, 1200, 700)

        # --- Variables d'état ---
        self.image_path1 = None; self.image_path2 = None
        self.pil_image1_orig = None; self.pil_image2_orig = None
        self.qt_pixmap1_orig = None; self.qt_pixmap2_orig = None
        self.display_pixmap1 = None; self.display_pixmap2 = None
        self.comparison_pixmap = None # Utilisé seulement pour Opacity maintenant
        self.current_mode = "side_by_side"
        self.opacity_value = 0.5
        self.link_views_enabled = True
        self._is_updating_views = False
        self.ab_timer = QtCore.QTimer(self)
        self.ab_timer.timeout.connect(self.switch_ab_image)
        self.ab_switch_interval = DEFAULT_AB_SWITCH_INTERVAL
        self.ab_showing_image1 = True

        # --- Items graphiques spécifiques ---
        self.interactive_slider = None # Initialisé dans setup_ui
        self.combined_slider_item = None # Initialisé dans setup_ui

        self.setup_ui()
        self.update_display()

    def setup_ui(self):
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QVBoxLayout(main_widget)
        control_panel = QtWidgets.QFrame(); control_panel.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        control_layout = QtWidgets.QHBoxLayout(control_panel); main_layout.addWidget(control_panel)

        # --- Contrôles de Chargement ---
        load_group = QtWidgets.QWidget(); load_layout = QtWidgets.QVBoxLayout(load_group)
        btn_load1 = QtWidgets.QPushButton("Load Image 1"); btn_load1.clicked.connect(lambda: self.load_image(1))
        self.lbl_img1 = QtWidgets.QLabel("No Image 1"); self.lbl_img1.setWordWrap(True)
        btn_load2 = QtWidgets.QPushButton("Load Image 2"); btn_load2.clicked.connect(lambda: self.load_image(2))
        self.lbl_img2 = QtWidgets.QLabel("No Image 2"); self.lbl_img2.setWordWrap(True)
        load_layout.addWidget(btn_load1); load_layout.addWidget(self.lbl_img1)
        load_layout.addStretch(); load_layout.addWidget(btn_load2); load_layout.addWidget(self.lbl_img2)
        control_layout.addWidget(load_group)

        # --- Contrôles de Mode ---
        mode_group = QtWidgets.QFrame(); mode_group.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        mode_layout = QtWidgets.QGridLayout(mode_group); control_layout.addWidget(mode_group, 1)
        mode_label = QtWidgets.QLabel("<b>Comparison Mode:</b>"); mode_layout.addWidget(mode_label, 0, 0, 1, 3)
        self.radio_side = QtWidgets.QRadioButton("Side by Side"); self.radio_side.setChecked(True)
        self.radio_side.toggled.connect(lambda checked: self.set_mode("side_by_side") if checked else None)
        mode_layout.addWidget(self.radio_side, 1, 0)
        self.radio_slider = QtWidgets.QRadioButton("Slider")
        self.radio_slider.toggled.connect(lambda checked: self.set_mode("slider") if checked else None)
        mode_layout.addWidget(self.radio_slider, 1, 1)
        self.radio_opacity = QtWidgets.QRadioButton("Opacity")
        self.radio_opacity.toggled.connect(lambda checked: self.set_mode("opacity") if checked else None)
        mode_layout.addWidget(self.radio_opacity, 1, 2)
        self.radio_ab_switch = QtWidgets.QRadioButton("A/B Switch")
        self.radio_ab_switch.toggled.connect(lambda checked: self.set_mode("ab_switch") if checked else None)
        mode_layout.addWidget(self.radio_ab_switch, 2, 0)

        # --- Options Spécifiques aux Modes ---
        self.options_stack = QtWidgets.QStackedWidget()
        mode_layout.addWidget(self.options_stack, 3, 0, 1, 3)
        self.options_stack.addWidget(QtWidgets.QWidget()) # Page Vide
        opacity_widget = QtWidgets.QWidget(); opacity_layout = QtWidgets.QHBoxLayout(opacity_widget)
        opacity_layout.addWidget(QtWidgets.QLabel("Opacity:"))
        self.slider_opacity = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100); self.slider_opacity.setValue(int(self.opacity_value * 100))
        self.slider_opacity.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.slider_opacity)
        self.lbl_opacity_value = QtWidgets.QLabel(f"{self.opacity_value:.2f}")
        opacity_layout.addWidget(self.lbl_opacity_value)
        self.options_stack.addWidget(opacity_widget) # Page Opacity
        ab_switch_widget = QtWidgets.QWidget(); ab_switch_layout = QtWidgets.QHBoxLayout(ab_switch_widget)
        ab_switch_layout.addWidget(QtWidgets.QLabel("Switch Speed (ms):"))
        self.slider_ab_speed = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_ab_speed.setRange(MIN_AB_SWITCH_INTERVAL, MAX_AB_SWITCH_INTERVAL)
        self.slider_ab_speed.setValue(self.ab_switch_interval)
        self.slider_ab_speed.valueChanged.connect(self.on_ab_speed_changed)
        ab_switch_layout.addWidget(self.slider_ab_speed)
        self.lbl_ab_speed_value = QtWidgets.QLabel(str(self.ab_switch_interval))
        ab_switch_layout.addWidget(self.lbl_ab_speed_value)
        self.options_stack.addWidget(ab_switch_widget) # Page A/B

        # --- Contrôles de Vue ---
        view_group = QtWidgets.QWidget(); view_layout = QtWidgets.QVBoxLayout(view_group)
        self.check_link_views = QtWidgets.QCheckBox("Link Views")
        self.check_link_views.setChecked(self.link_views_enabled)
        self.check_link_views.toggled.connect(self.on_link_views_toggled)
        self.check_link_views.setToolTip(
            "Synchronize pan/zoom between views in 'Side by Side' mode.\n"
            "Note: In 'Opacity' mode, images are always blended based on their full extent.\n"
            "Use 'Side by Side' with Link Views unchecked to align images first."
        )
        btn_reset_view = QtWidgets.QPushButton("Reset View"); btn_reset_view.clicked.connect(self.reset_all_views)
        view_layout.addWidget(self.check_link_views); view_layout.addStretch(); view_layout.addWidget(btn_reset_view)
        control_layout.addWidget(view_group)

        # --- Zone d'Affichage ---
        self.view1 = ImageViewer(); self.view2 = ImageViewer(); self.view_combined = ImageViewer()
        self.view_stack = QtWidgets.QStackedWidget()
        side_by_side_widget = QtWidgets.QWidget(); side_by_side_layout = QtWidgets.QHBoxLayout(side_by_side_widget)
        side_by_side_layout.setContentsMargins(0,0,0,0); side_by_side_layout.setSpacing(1)
        side_by_side_layout.addWidget(self.view1); side_by_side_layout.addWidget(self.view2)
        self.view_stack.addWidget(side_by_side_widget) # Index 0
        self.view_stack.addWidget(self.view_combined)   # Index 1
        main_layout.addWidget(self.view_stack, 1)

        # Connecter les signaux
        self.view1.viewChanged.connect(lambda: self.sync_views(source_view=self.view1))
        self.view2.viewChanged.connect(lambda: self.sync_views(source_view=self.view2))
        self.view1.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 1))
        self.view2.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 2))
        self.view_combined.mouseMoved.connect(lambda pos: self.update_status_bar(pos, 0))

        # --- Items Graphiques Spéciaux (Slider) ---
        # Créer l'item qui dessinera les pixmaps combinés
        self.combined_slider_item = CombinedSliderItem()
        self.combined_slider_item.setVisible(False) # Caché par défaut
        self.view_combined.scene().addItem(self.combined_slider_item)

        # Créer l'item ligne rouge interactif
        self.interactive_slider = InteractiveSliderItem(self.view_combined.sceneRect()) # Utiliser sceneRect initial
        self.interactive_slider.signals.positionChanged.connect(self.on_slider_ratio_update) # Connecter à un slot dédié
        self.interactive_slider.setVisible(False) # Caché par défaut
        # Mettre le slider *au-dessus* de l'item combiné
        self.interactive_slider.setZValue(1)
        self.view_combined.scene().addItem(self.interactive_slider)


        # --- Barre de Statut ---
        self.statusBar = QtWidgets.QStatusBar(); self.setStatusBar(self.statusBar)
        self.lbl_status_coords = QtWidgets.QLabel("Coords: (N/A, N/A)")
        self.lbl_status_rgb = QtWidgets.QLabel("RGB: (N/A)")
        self.statusBar.addPermanentWidget(self.lbl_status_coords)
        spacer = QtWidgets.QWidget(); spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.statusBar.addPermanentWidget(spacer, 1)
        self.statusBar.addPermanentWidget(self.lbl_status_rgb)

    # --- Fonctions Logiques ---

    def set_mode(self, mode):
        if self.current_mode != mode:
            previous_mode = self.current_mode
            self.current_mode = mode
            print(f"Mode changed to: {mode}")
            if previous_mode == "ab_switch": self.ab_timer.stop(); print("A/B Timer stopped.")
            if mode == "opacity": self.options_stack.setCurrentIndex(1)
            elif mode == "ab_switch": self.options_stack.setCurrentIndex(2)
            else: self.options_stack.setCurrentIndex(0)
            self.update_display()

    def on_opacity_changed(self, value):
        self.opacity_value = value / 100.0
        self.lbl_opacity_value.setText(f"{self.opacity_value:.2f}")
        if self.current_mode == "opacity": self.update_comparison_image() # Recalculer l'image Opacity

    def on_ab_speed_changed(self, value):
        self.ab_switch_interval = value
        self.lbl_ab_speed_value.setText(str(value))
        if self.ab_timer.isActive():
            self.ab_timer.setInterval(self.ab_switch_interval)
            print(f"A/B Timer interval updated to: {self.ab_switch_interval} ms")

    def on_link_views_toggled(self, checked):
        self.link_views_enabled = checked
        print(f"Link Views: {self.link_views_enabled}")
        if checked and self.current_mode == "side_by_side":
            self.sync_views(self.view1, force_sync=True)

    # def on_interactive_slider_moved(self, position_ratio):
    #     # OBSOLÈTE - Remplacé par on_slider_ratio_update
    #     # if self.current_mode == "slider": self.update_comparison_image()
    #     pass

    def on_slider_ratio_update(self, ratio: float):
        """ Slot appelé par le signal positionChanged de InteractiveSliderItem. """
        if self.current_mode == "slider" and self.combined_slider_item:
            # Mettre à jour l'item qui dessine les deux images avec le nouveau ratio
            self.combined_slider_item.set_data(self.display_pixmap1, self.display_pixmap2, ratio)
            # Pas besoin d'appeler update_comparison_image ici

    def switch_ab_image(self):
        if self.current_mode != "ab_switch" or not self.display_pixmap1 or not self.display_pixmap2:
            self.ab_timer.stop(); return
        self.ab_showing_image1 = not self.ab_showing_image1
        pixmap_to_show = self.display_pixmap1 if self.ab_showing_image1 else self.display_pixmap2
        if pixmap_to_show and not pixmap_to_show.isNull():
            # Utiliser l'item standard de view_combined pour afficher l'image A ou B
            self.view_combined.set_pixmap(pixmap_to_show)
        else:
             self.ab_timer.stop(); print("Warning: A/B switch stopped due to invalid pixmap.")

    def pil_to_qpixmap(self, pil_image):
        if pil_image is None: return QtGui.QPixmap()
        try:
            if pil_image.mode not in ["RGB", "RGBA"]: pil_image = pil_image.convert("RGB")
            if ImageQt:
                qimage = ImageQt.ImageQt(pil_image)
                if isinstance(qimage, QtGui.QImage): return QtGui.QPixmap.fromImage(qimage)
                else: return QtGui.QPixmap(qimage)
            else:
                print("Warning: ImageQt not available, using fallback conversion.")
                if pil_image.mode == "RGB": data = pil_image.tobytes("raw", "RGB"); qimage = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGB888)
                elif pil_image.mode == "RGBA": data = pil_image.tobytes("raw", "RGBA"); qimage = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGBA8888)
                else: return QtGui.QPixmap()
                return QtGui.QPixmap.fromImage(qimage)
        except Exception as e: print(f"Error converting PIL to QPixmap: {e}"); return QtGui.QPixmap()

    def load_image(self, image_num):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(self, f"Select Image {image_num}", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;All Files (*)")
        if not filepath: return
        try:
            img = Image.open(filepath)
            if max(img.width, img.height) > MAX_IMAGE_DIM_LOAD: img.thumbnail((MAX_IMAGE_DIM_LOAD, MAX_IMAGE_DIM_LOAD), Image.Resampling.LANCZOS); print(f"Image {image_num} resized")
            pil_img_conv = img.convert("RGBA") if 'A' in img.getbands() else img.convert("RGB")
            qt_pixmap = self.pil_to_qpixmap(pil_img_conv)
            view_to_reset = None
            if image_num == 1: self.image_path1 = filepath; self.pil_image1_orig = pil_img_conv; self.qt_pixmap1_orig = qt_pixmap; self.lbl_img1.setText(os.path.basename(filepath)); view_to_reset = self.view1
            else: self.image_path2 = filepath; self.pil_image2_orig = pil_img_conv; self.qt_pixmap2_orig = qt_pixmap; self.lbl_img2.setText(os.path.basename(filepath)); view_to_reset = self.view2
            print(f"Loaded Image {image_num}: {filepath} ({pil_img_conv.width}x{pil_img_conv.height})")
            self.update_display()
            if view_to_reset: view_to_reset.reset_view()
            if self.current_mode != "side_by_side": self.view_combined.reset_view()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error Loading Image", f"Could not load image:\n{e}")
            if image_num == 1: self.image_path1 = None; self.pil_image1_orig = None; self.qt_pixmap1_orig = None; self.lbl_img1.setText("No Image 1")
            else: self.image_path2 = None; self.pil_image2_orig = None; self.qt_pixmap2_orig = None; self.lbl_img2.setText("No Image 2")
            self.update_display()

    def prepare_display_images(self):
        pil1 = self.pil_image1_orig; pil2 = self.pil_image2_orig
        self.display_pixmap1 = self.qt_pixmap1_orig.copy() if self.qt_pixmap1_orig else QtGui.QPixmap()
        self.display_pixmap2 = self.qt_pixmap2_orig.copy() if self.qt_pixmap2_orig else QtGui.QPixmap()
        # Redimensionner pour TOUS les modes combinés pour assurer la cohérence
        is_combined_mode = self.current_mode in ['slider', 'opacity', 'ab_switch']
        pil1_for_comp = pil1; pil2_for_comp = pil2
        if is_combined_mode and pil1 and pil2 and pil1.size != pil2.size:
            print(f"Resizing Image 2 ({pil2.width}x{pil2.height}) to match Image 1 ({pil1.width}x{pil1.height}) for combined mode.")
            pil2_resized = pil2.resize(pil1.size, Image.Resampling.LANCZOS)
            self.display_pixmap2 = self.pil_to_qpixmap(pil2_resized) # Mettre à jour le pixmap utilisé
            pil2_for_comp = pil2_resized # Utiliser le redimensionné pour la comparaison (Opacity)
        return pil1_for_comp, pil2_for_comp # Retourne les versions PIL (potentiellement redim pour img2)

    def update_display(self):
        print(f"Updating display for mode: {self.current_mode}")
        pil1_comp, pil2_comp = self.prepare_display_images() # Prépare self.display_pixmap1/2
        if self.ab_timer.isActive(): self.ab_timer.stop(); print("A/B Timer stopped during display update.")

        # Cacher/Montrer les items spécifiques
        standard_pixmap_item = self.view_combined.get_pixmap_item()
        standard_pixmap_item.setVisible(self.current_mode != "slider")
        self.combined_slider_item.setVisible(self.current_mode == "slider")
        self.interactive_slider.setVisible(self.current_mode == "slider")

        if self.current_mode == "side_by_side":
            self.view_stack.setCurrentIndex(0)
            self.view1.set_pixmap(self.display_pixmap1); self.view2.set_pixmap(self.display_pixmap2)
            if self.link_views_enabled: self.sync_views(self.view1, force_sync=True)
        else: # Modes combinés (slider, opacity, ab_switch)
            self.view_stack.setCurrentIndex(1)

            # Déterminer la taille de la scène basée sur l'image 1 (ou 2 si 1 manque)
            scene_rect = QtCore.QRectF()
            if self.display_pixmap1 and not self.display_pixmap1.isNull():
                scene_rect = QtCore.QRectF(self.display_pixmap1.rect())
            elif self.display_pixmap2 and not self.display_pixmap2.isNull():
                 scene_rect = QtCore.QRectF(self.display_pixmap2.rect())
            self.view_combined.setSceneRect(scene_rect) # Mettre à jour la taille de la scène

            if self.current_mode == "slider":
                # Mettre à jour l'item combiné avec les pixmaps et le ratio actuel du slider
                current_ratio = self.interactive_slider.get_position_ratio()
                self.combined_slider_item.set_data(self.display_pixmap1, self.display_pixmap2, current_ratio)
                # Mettre à jour la géométrie de la ligne rouge interactive
                self.interactive_slider.set_scene_rect(scene_rect)

            elif self.current_mode == "ab_switch":
                # Gérer l'affichage initial et le timer A/B
                if self.display_pixmap1 and not self.display_pixmap1.isNull() and self.display_pixmap2 and not self.display_pixmap2.isNull():
                    self.ab_showing_image1 = True; initial_pixmap = self.display_pixmap1
                    standard_pixmap_item.setPixmap(initial_pixmap) # Afficher dans l'item standard
                    self.ab_timer.setInterval(self.ab_switch_interval); self.ab_timer.start()
                    print(f"A/B Timer started. Interval: {self.ab_switch_interval} ms")
                elif self.display_pixmap1 and not self.display_pixmap1.isNull(): standard_pixmap_item.setPixmap(self.display_pixmap1); print("A/B Switch: Only image 1 available.")
                elif self.display_pixmap2 and not self.display_pixmap2.isNull(): standard_pixmap_item.setPixmap(self.display_pixmap2); print("A/B Switch: Only image 2 available.")
                else: standard_pixmap_item.setPixmap(QtGui.QPixmap()); print("A/B Switch: No images available.")

            elif self.current_mode == "opacity":
                # Générer l'image mélangée et l'afficher dans l'item standard
                self.update_comparison_image(pil1_comp, pil2_comp) # Met à jour self.comparison_pixmap
                pix_to_show = self.comparison_pixmap if self.comparison_pixmap else QtGui.QPixmap()
                standard_pixmap_item.setPixmap(pix_to_show)
                # Fallbacks si la comparaison échoue
                if pix_to_show.isNull():
                    if self.display_pixmap1 and not self.display_pixmap1.isNull(): standard_pixmap_item.setPixmap(self.display_pixmap1)
                    elif self.display_pixmap2 and not self.display_pixmap2.isNull(): standard_pixmap_item.setPixmap(self.display_pixmap2)


    def update_comparison_image(self, pil1_comp=None, pil2_comp=None):
        # Ne générer que pour Opacity maintenant
        if self.current_mode != "opacity":
            self.comparison_pixmap = None; return

        if pil1_comp is None and pil2_comp is None:
             pil1_comp, pil2_comp = self.prepare_display_images()
        pil_result = None

        if self.current_mode == "opacity":
             if pil1_comp and pil2_comp:
                 try: pil_result = Image.blend(pil1_comp.convert("RGB"), pil2_comp.convert("RGB"), alpha=self.opacity_value)
                 except Exception as e: print(f"Error blending: {e}"); pil_result = pil1_comp
             elif pil1_comp: pil_result = pil1_comp
             elif pil2_comp: pil_result = pil2_comp

        if pil_result: self.comparison_pixmap = self.pil_to_qpixmap(pil_result)
        elif pil1_comp: self.comparison_pixmap = self.display_pixmap1
        elif pil2_comp: self.comparison_pixmap = self.display_pixmap2
        else: self.comparison_pixmap = QtGui.QPixmap()
        # L'affichage se fait dans update_display après cet appel

    def reset_all_views(self):
        target_view = None
        if self.current_mode == "side_by_side":
            self.view1.reset_view(); self.view2.reset_view()
            target_view = self.view1 # Utiliser comme référence pour le slider
        else:
            self.view_combined.reset_view()
            target_view = self.view_combined

        # Remettre le slider au centre si on reset
        if self.interactive_slider: # S'assurer qu'il est initialisé
             self.interactive_slider.set_position_ratio(0.5)
             # Mettre à jour l'affichage du slider si on est dans ce mode
             if self.current_mode == "slider":
                  self.on_slider_ratio_update(0.5) # Mettre à jour l'item combiné


    def sync_views(self, source_view, force_sync=False):
        if not self.link_views_enabled or self._is_updating_views or self.current_mode != "side_by_side": return
        self._is_updating_views = True
        target_view = self.view2 if source_view == self.view1 else self.view1
        if target_view:
            source_transform = source_view.transform(); target_view.set_transform(source_transform)
            h_val, v_val = source_view.horizontalScrollBar().value(), source_view.verticalScrollBar().value()
            h_max, v_max = source_view.horizontalScrollBar().maximum(), source_view.verticalScrollBar().maximum()
            if target_view.horizontalScrollBar().maximum() != h_max: target_view.horizontalScrollBar().setMaximum(h_max)
            if target_view.horizontalScrollBar().value() != h_val: target_view.horizontalScrollBar().setValue(h_val)
            if target_view.verticalScrollBar().maximum() != v_max: target_view.verticalScrollBar().setMaximum(v_max)
            if target_view.verticalScrollBar().value() != v_val: target_view.verticalScrollBar().setValue(v_val)
        self._is_updating_views = False

    def update_status_bar(self, scene_pos, view_index):
        img_coords, pixel_value = None, None; img_w, img_h = 0, 0
        pixmap_item = None; active_pixmap = None; target_item_for_coords = None

        if view_index == 1 and self.current_mode == "side_by_side":
            pixmap_item = self.view1.get_pixmap_item()
            target_item_for_coords = pixmap_item
        elif view_index == 2 and self.current_mode == "side_by_side":
            pixmap_item = self.view2.get_pixmap_item()
            target_item_for_coords = pixmap_item
        elif view_index == 0 and self.current_mode != "side_by_side": # Vue combinée
            if self.current_mode == "slider":
                 pixmap_item = self.combined_slider_item # Lire depuis l'item combiné
                 target_item_for_coords = pixmap_item # Coords relatives à cet item
            else: # Opacity ou A/B
                 pixmap_item = self.view_combined.get_pixmap_item() # Lire depuis l'item standard
                 target_item_for_coords = pixmap_item

        if pixmap_item:
             # Pour la couleur, on lit toujours le pixmap actuellement affiché si possible
             if isinstance(pixmap_item, QtWidgets.QGraphicsPixmapItem):
                 active_pixmap = pixmap_item.pixmap()
             # Pour CombinedSliderItem, on doit choisir une source pour la couleur (ou la calculer?)
             # Simplification: on ne lit pas la couleur en mode slider pour l'instant
             elif isinstance(pixmap_item, CombinedSliderItem):
                  active_pixmap = None # Pas de pixmap unique à lire facilement

        # Calcul des coordonnées basé sur target_item_for_coords
        if target_item_for_coords and target_item_for_coords.scene() is not None:
            item_pos = target_item_for_coords.mapFromScene(scene_pos)
            brect = target_item_for_coords.boundingRect()
            x, y = int(item_pos.x()), int(item_pos.y())
            img_w, img_h = int(brect.width()), int(brect.height())

            if brect.contains(item_pos): # Vérifier si dans le boundingRect
                img_coords = (x, y)
                # Essayer de lire la couleur si on a un active_pixmap
                if active_pixmap and not active_pixmap.isNull():
                    try:
                        qimg_to_read = active_pixmap.toImage()
                        if not qimg_to_read.isNull() and qimg_to_read.valid(x,y):
                            color = QtGui.QColor(qimg_to_read.pixel(x, y))
                            pixel_value = (color.red(), color.green(), color.blue())
                        else: pixel_value = "Invalid"
                    except Exception: pixel_value = "Error"
                elif isinstance(target_item_for_coords, CombinedSliderItem):
                     pixel_value = "N/A (Slider)" # Indiquer qu'on ne lit pas en mode slider

        coords_text = f"Coords: ({img_coords[0]}, {img_coords[1]}) / ({img_w}x{img_h})" if img_coords else f"Coords: (N/A) / ({img_w}x{img_h})" if img_w and img_h else "Coords: (N/A)"
        rgb_text = f"RGB: {str(pixel_value)}" if pixel_value and pixel_value not in ["Error", "Out", "Invalid", "N/A (Slider)"] else f"RGB: ({pixel_value or 'N/A'})"
        self.lbl_status_coords.setText(coords_text); self.lbl_status_rgb.setText(rgb_text)


# --- Point d'Entrée ---
if __name__ == "__main__":
    if hasattr(QtCore.Qt, 'ApplicationAttribute'):
         QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
         QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    elif hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
         QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
         QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv); window = ImageComparerApp(); window.show(); sys.exit(app.exec())