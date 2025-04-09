import sys
import os
import numpy as np
# Utiliser PySide6
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt, QPointF, QRectF, Signal, QSize, QTimer
from PySide6.QtGui import QImage, QPixmap, QPainter, QPen, QBrush, QColor, QTransform, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QRadioButton, QSlider, QComboBox,
    QCheckBox, QFrame, QGraphicsView, QGraphicsScene, QGraphicsPixmapItem,
    QGraphicsLineItem, QSizePolicy, QStatusBar, QMessageBox, QGridLayout,
    QStyle, QStackedWidget
)
# Try importing ImageQt
try:
    from PIL import ImageQt
except ImportError:
    print("Warning: PIL.ImageQt not found directly. Ensure Pillow is up-to-date.")
    ImageQt = None

from PIL import Image, ImageOps # ImageChops n'est plus nécessaire

# --- Configuration ---
MAX_IMAGE_DIM_LOAD = 3000
DEFAULT_AB_SWITCH_INTERVAL = 500 # Millisecondes
MIN_AB_SWITCH_INTERVAL = 100
MAX_AB_SWITCH_INTERVAL = 2000

# --- Custom Graphics View ---
class ImageViewer(QtWidgets.QGraphicsView):
    """ QGraphicsView customisé pour afficher une image avec zoom/pan """
    viewChanged = Signal()
    mouseMoved = Signal(QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self.setScene(self._scene)

        self.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setBackgroundBrush(QBrush(QColor(70, 70, 70)))
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setDragMode(QtWidgets.QGraphicsView.DragMode.ScrollHandDrag)

        self._zoom = 1.0
        self._panning = False
        self._last_pan_point = QtCore.QPoint()

        self.setMouseTracking(True)

    def set_pixmap(self, pixmap):
        if pixmap and not pixmap.isNull():
            current_transform = self.transform()
            is_empty = self._pixmap_item.pixmap().isNull()
            self._pixmap_item.setPixmap(pixmap)
            self._scene.setSceneRect(QRectF(pixmap.rect()))
            if is_empty:
                 self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                 self._zoom = self.transform().m11()
            else:
                 self.setTransform(current_transform)
        else:
            self._pixmap_item.setPixmap(QPixmap())
            self._scene.setSceneRect(QRectF())

    def get_pixmap_item(self):
        return self._pixmap_item

    def wheelEvent(self, event: QtGui.QWheelEvent):
        zoom_factor = 1.15
        # Utiliser angleDelta().y()
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor); self._zoom *= zoom_factor
        else:
            self.scale(1 / zoom_factor, 1 / zoom_factor); self._zoom /= zoom_factor
        self.viewChanged.emit()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
             # Vérifier si le clic est sur un item qui n'est pas le fond (le pixmap)
             # pour permettre le pan uniquement sur l'image et pas sur le slider
             item = self.itemAt(event.position().toPoint())
             if item == self._pixmap_item or item is None: # Si on clique sur l'image ou le fond
                 self._panning = True
                 self._last_pan_point = event.position().toPoint()
                 self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
             else: # Si on clique sur un autre item (le slider), ne pas initier le pan de la vue
                 self._panning = False
                 # Laisser l'item gérer son propre mousePressEvent (appelé via super)
        super().mousePressEvent(event) # Important pour les items et autres boutons

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        scene_pos = self.mapToScene(event.position().toPoint())
        self.mouseMoved.emit(scene_pos)
        if self._panning: # Seulement si le pan a été initié dans mousePressEvent
             delta = event.position().toPoint() - self._last_pan_point
             self._last_pan_point = event.position().toPoint()
             self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
             self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
             self.viewChanged.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._panning: # Si on était en train de panner
                self._panning = False
                self.setCursor(QtCore.Qt.CursorShape.ArrowCursor) # Restaurer curseur normal
        super().mouseReleaseEvent(event)

    def reset_view(self):
        if not self._pixmap_item.pixmap().isNull():
            self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom = self.transform().m11(); self.viewChanged.emit()

    def get_transform(self) -> QTransform: return self.transform()
    def set_transform(self, transform: QTransform):
        super().setTransform(transform); self._zoom = self.transform().m11()

# --- Custom Slider Item ---
class InteractiveSliderItem(QtWidgets.QGraphicsLineItem):
    class Signals(QtCore.QObject):
        positionChanged = Signal(float)

    def __init__(self, scene_rect, parent=None):
        super().__init__(parent)
        self.scene_rect = scene_rect
        self._position = 0.5
        self.signals = self.Signals()
        self.positionChanged = self.signals.positionChanged

        pen = QPen(QtCore.Qt.GlobalColor.red, 2, QtCore.Qt.PenStyle.SolidLine)
        self.setPen(pen)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        self.setPos(0, 0)
        self.update_line_geometry()
        # Accepter le bouton gauche pour pouvoir intercepter l'événement
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        """
        Accepte l'événement pour empêcher la vue de faire un panoramique,
        mais appelle la base pour activer le déplacement de l'item.
        """
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            event.accept() # Empêche la propagation vers ImageViewer (pas de pan)
        # Appeler la méthode de base est crucial pour que ItemIsMovable fonctionne !
        super().mousePressEvent(event)

    def update_line_geometry(self):
        x = self.scene_rect.left() + self.scene_rect.width() * self._position
        self.setLine(x, self.scene_rect.top(), x, self.scene_rect.bottom())
        if self.pos() != QPointF(0, 0): self.setPos(0, 0)

    def set_scene_rect(self, rect):
        self.scene_rect = rect; self.update_line_geometry()
    def set_position_ratio(self, ratio):
        self._position = max(0.0, min(1.0, ratio)); self.update_line_geometry()
    def get_position_ratio(self): return self._position

    def itemChange(self, change: QtWidgets.QGraphicsItem.GraphicsItemChange, value):
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionChange and self.scene():
            requested_line_x = value.x()
            min_x = self.scene_rect.left(); max_x = self.scene_rect.right()
            if max_x < min_x: max_x = min_x
            constrained_line_x = max(min_x, min(requested_line_x, max_x))
            scene_width = self.scene_rect.width()
            new_position_ratio = (constrained_line_x - min_x) / scene_width if scene_width > 0 else 0.5
            if not np.isclose(new_position_ratio, self._position):
                self._position = new_position_ratio
                self.update_line_geometry()
                self.signals.positionChanged.emit(self._position)
            return QPointF(0, 0) # Toujours retourner 0,0 pour que l'item ne bouge pas
        return super().itemChange(change, value)

# --- Classe Principale de l'Application ---
class ImageComparerApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Image Comparer (PySide6 Replica)")
        self.setGeometry(100, 100, 1200, 700)

        # --- Variables d'état ---
        self.image_path1 = None; self.image_path2 = None
        self.pil_image1_orig = None; self.pil_image2_orig = None
        self.qt_pixmap1_orig = None; self.qt_pixmap2_orig = None
        self.display_pixmap1 = None; self.display_pixmap2 = None
        self.comparison_pixmap = None
        self.current_mode = "side_by_side"
        self.opacity_value = 0.5
        self.link_views_enabled = True
        self._is_updating_views = False
        self.ab_timer = QTimer(self)
        self.ab_timer.timeout.connect(self.switch_ab_image)
        self.ab_switch_interval = DEFAULT_AB_SWITCH_INTERVAL
        self.ab_showing_image1 = True

        self.setup_ui()
        self.update_display()

    def setup_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        control_panel = QFrame(); control_panel.setFrameShape(QFrame.Shape.StyledPanel)
        control_layout = QHBoxLayout(control_panel); main_layout.addWidget(control_panel)

        # --- Contrôles de Chargement ---
        load_group = QWidget(); load_layout = QVBoxLayout(load_group)
        btn_load1 = QPushButton("Load Image 1"); btn_load1.clicked.connect(lambda: self.load_image(1))
        self.lbl_img1 = QLabel("No Image 1"); self.lbl_img1.setWordWrap(True)
        btn_load2 = QPushButton("Load Image 2"); btn_load2.clicked.connect(lambda: self.load_image(2))
        self.lbl_img2 = QLabel("No Image 2"); self.lbl_img2.setWordWrap(True)
        load_layout.addWidget(btn_load1); load_layout.addWidget(self.lbl_img1)
        load_layout.addStretch(); load_layout.addWidget(btn_load2); load_layout.addWidget(self.lbl_img2)
        control_layout.addWidget(load_group)

        # --- Contrôles de Mode ---
        mode_group = QFrame(); mode_group.setFrameShape(QFrame.Shape.StyledPanel)
        mode_layout = QGridLayout(mode_group); control_layout.addWidget(mode_group, 1)
        mode_label = QLabel("<b>Comparison Mode:</b>"); mode_layout.addWidget(mode_label, 0, 0, 1, 3)

        # Row 1
        self.radio_side = QRadioButton("Side by Side"); self.radio_side.setChecked(True)
        self.radio_side.toggled.connect(lambda checked: self.set_mode("side_by_side") if checked else None)
        mode_layout.addWidget(self.radio_side, 1, 0)

        self.radio_slider = QRadioButton("Slider")
        self.radio_slider.toggled.connect(lambda checked: self.set_mode("slider") if checked else None)
        mode_layout.addWidget(self.radio_slider, 1, 1)

        self.radio_opacity = QRadioButton("Opacity")
        self.radio_opacity.toggled.connect(lambda checked: self.set_mode("opacity") if checked else None)
        mode_layout.addWidget(self.radio_opacity, 1, 2)

        # Row 2
        self.radio_ab_switch = QRadioButton("A/B Switch")
        self.radio_ab_switch.toggled.connect(lambda checked: self.set_mode("ab_switch") if checked else None)
        mode_layout.addWidget(self.radio_ab_switch, 2, 0)

        # --- Options Spécifiques aux Modes ---
        self.options_stack = QStackedWidget()
        mode_layout.addWidget(self.options_stack, 3, 0, 1, 3)

        # Page Vide (Index 0 - pour SideBySide, Slider)
        self.options_stack.addWidget(QWidget())

        # Page Opacity (Index 1)
        opacity_widget = QWidget(); opacity_layout = QHBoxLayout(opacity_widget)
        opacity_layout.addWidget(QLabel("Opacity:"))
        self.slider_opacity = QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_opacity.setRange(0, 100); self.slider_opacity.setValue(int(self.opacity_value * 100))
        self.slider_opacity.valueChanged.connect(self.on_opacity_changed)
        opacity_layout.addWidget(self.slider_opacity)
        self.lbl_opacity_value = QLabel(f"{self.opacity_value:.2f}")
        opacity_layout.addWidget(self.lbl_opacity_value)
        self.options_stack.addWidget(opacity_widget)

        # Page A/B Switch (Index 2)
        ab_switch_widget = QWidget(); ab_switch_layout = QHBoxLayout(ab_switch_widget)
        ab_switch_layout.addWidget(QLabel("Switch Speed (ms):"))
        self.slider_ab_speed = QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_ab_speed.setRange(MIN_AB_SWITCH_INTERVAL, MAX_AB_SWITCH_INTERVAL)
        self.slider_ab_speed.setValue(self.ab_switch_interval)
        self.slider_ab_speed.valueChanged.connect(self.on_ab_speed_changed)
        ab_switch_layout.addWidget(self.slider_ab_speed)
        self.lbl_ab_speed_value = QLabel(str(self.ab_switch_interval))
        ab_switch_layout.addWidget(self.lbl_ab_speed_value)
        self.options_stack.addWidget(ab_switch_widget)

        # --- Contrôles de Vue ---
        view_group = QWidget(); view_layout = QVBoxLayout(view_group)
        self.check_link_views = QCheckBox("Link Views")
        self.check_link_views.setChecked(self.link_views_enabled)
        self.check_link_views.toggled.connect(self.on_link_views_toggled)
        self.check_link_views.setToolTip(
            "Synchronize pan/zoom between views in 'Side by Side' mode.\n"
            "Note: In 'Opacity' mode, images are always blended based on their full extent.\n"
            "Use 'Side by Side' with Link Views unchecked to align images first."
        )
        btn_reset_view = QPushButton("Reset View"); btn_reset_view.clicked.connect(self.reset_all_views)
        view_layout.addWidget(self.check_link_views); view_layout.addStretch(); view_layout.addWidget(btn_reset_view)
        control_layout.addWidget(view_group)

        # --- Zone d'Affichage ---
        self.view1 = ImageViewer(); self.view2 = ImageViewer(); self.view_combined = ImageViewer()
        self.view_stack = QStackedWidget()
        side_by_side_widget = QWidget(); side_by_side_layout = QHBoxLayout(side_by_side_widget)
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

        # --- Slider Item ---
        self.interactive_slider = InteractiveSliderItem(self.view_combined.sceneRect())
        self.interactive_slider.signals.positionChanged.connect(self.on_interactive_slider_moved)
        self.interactive_slider.setVisible(False)
        self.view_combined.scene().addItem(self.interactive_slider)

        # --- Barre de Statut ---
        self.statusBar = QStatusBar(); self.setStatusBar(self.statusBar)
        self.lbl_status_coords = QLabel("Coords: (N/A, N/A)")
        self.lbl_status_rgb = QLabel("RGB: (N/A)")
        self.statusBar.addPermanentWidget(self.lbl_status_coords)
        spacer = QWidget(); spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.statusBar.addPermanentWidget(spacer, 1)
        self.statusBar.addPermanentWidget(self.lbl_status_rgb)

    # --- Fonctions Logiques ---

    def set_mode(self, mode):
        if self.current_mode != mode:
            previous_mode = self.current_mode
            self.current_mode = mode
            print(f"Mode changed to: {mode}")
            if previous_mode == "ab_switch": self.ab_timer.stop(); print("A/B Timer stopped.")

            # Mettre à jour l'index du QStackedWidget pour les options
            if mode == "opacity": self.options_stack.setCurrentIndex(1)
            elif mode == "ab_switch": self.options_stack.setCurrentIndex(2)
            else: self.options_stack.setCurrentIndex(0) # side_by_side, slider

            self.update_display()

    # --- Slots pour les contrôles d'options ---
    def on_opacity_changed(self, value):
        self.opacity_value = value / 100.0
        self.lbl_opacity_value.setText(f"{self.opacity_value:.2f}")
        if self.current_mode == "opacity": self.update_comparison_image()

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

    def on_interactive_slider_moved(self, position_ratio):
        if self.current_mode == "slider": self.update_comparison_image()

    # --- Logique A/B Switch ---
    def switch_ab_image(self):
        if self.current_mode != "ab_switch" or not self.display_pixmap1 or not self.display_pixmap2:
            self.ab_timer.stop(); return
        self.ab_showing_image1 = not self.ab_showing_image1
        pixmap_to_show = self.display_pixmap1 if self.ab_showing_image1 else self.display_pixmap2
        if pixmap_to_show and not pixmap_to_show.isNull():
            self.view_combined.set_pixmap(pixmap_to_show)
        else:
             self.ab_timer.stop(); print("Warning: A/B switch stopped due to invalid pixmap.")

    # --- Conversion et Chargement ---
    def pil_to_qpixmap(self, pil_image):
        if pil_image is None: return QPixmap()
        try:
            if pil_image.mode not in ["RGB", "RGBA"]: pil_image = pil_image.convert("RGB")
            if ImageQt:
                qimage = ImageQt.ImageQt(pil_image)
                if isinstance(qimage, QtGui.QImage): return QPixmap.fromImage(qimage)
                else: return QPixmap(qimage)
            else:
                print("Warning: ImageQt not available, using fallback conversion.")
                if pil_image.mode == "RGB": data = pil_image.tobytes("raw", "RGB"); qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGB888)
                elif pil_image.mode == "RGBA": data = pil_image.tobytes("raw", "RGBA"); qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
                else: return QPixmap()
                return QPixmap.fromImage(qimage)
        except Exception as e: print(f"Error converting PIL to QPixmap: {e}"); return QPixmap()

    def load_image(self, image_num):
        filepath, _ = QFileDialog.getOpenFileName(self, f"Select Image {image_num}", "", "Image Files (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;All Files (*)")
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
            QMessageBox.critical(self, "Error Loading Image", f"Could not load image:\n{e}")
            if image_num == 1: self.image_path1 = None; self.pil_image1_orig = None; self.qt_pixmap1_orig = None; self.lbl_img1.setText("No Image 1")
            else: self.image_path2 = None; self.pil_image2_orig = None; self.qt_pixmap2_orig = None; self.lbl_img2.setText("No Image 2")
            self.update_display()

    # --- Préparation et Mise à Jour Affichage ---
    def prepare_display_images(self):
        pil1 = self.pil_image1_orig; pil2 = self.pil_image2_orig
        self.display_pixmap1 = self.qt_pixmap1_orig.copy() if self.qt_pixmap1_orig else QPixmap()
        self.display_pixmap2 = self.qt_pixmap2_orig.copy() if self.qt_pixmap2_orig else QPixmap()
        is_combined_mode = self.current_mode in ['slider', 'opacity', 'ab_switch']
        pil1_for_comp = pil1; pil2_for_comp = pil2
        if is_combined_mode and pil1 and pil2 and pil1.size != pil2.size:
            print(f"Resizing Image 2 ({pil2.width}x{pil2.height}) to match Image 1 ({pil1.width}x{pil1.height}) for combined mode.")
            pil2_resized = pil2.resize(pil1.size, Image.Resampling.LANCZOS)
            self.display_pixmap2 = self.pil_to_qpixmap(pil2_resized)
            pil2_for_comp = pil2_resized
        return pil1_for_comp, pil2_for_comp

    def update_display(self):
        print(f"Updating display for mode: {self.current_mode}")
        pil1_comp, pil2_comp = self.prepare_display_images()
        if self.ab_timer.isActive(): self.ab_timer.stop(); print("A/B Timer stopped during display update.")

        if self.current_mode == "side_by_side":
            self.view_stack.setCurrentIndex(0); self.interactive_slider.setVisible(False)
            self.view1.set_pixmap(self.display_pixmap1); self.view2.set_pixmap(self.display_pixmap2)
            if self.link_views_enabled: self.sync_views(self.view1, force_sync=True)
        else: # Modes combinés (slider, opacity, ab_switch)
            self.view_stack.setCurrentIndex(1); self.interactive_slider.setVisible(self.current_mode == "slider")

            if self.current_mode == "ab_switch":
                self.comparison_pixmap = None
                if self.display_pixmap1 and not self.display_pixmap1.isNull() and self.display_pixmap2 and not self.display_pixmap2.isNull():
                    self.ab_showing_image1 = True; initial_pixmap = self.display_pixmap1
                    self.view_combined.set_pixmap(initial_pixmap)
                    self.ab_timer.setInterval(self.ab_switch_interval); self.ab_timer.start()
                    print(f"A/B Timer started. Interval: {self.ab_switch_interval} ms")
                elif self.display_pixmap1 and not self.display_pixmap1.isNull(): self.view_combined.set_pixmap(self.display_pixmap1); print("A/B Switch: Only image 1 available.")
                elif self.display_pixmap2 and not self.display_pixmap2.isNull(): self.view_combined.set_pixmap(self.display_pixmap2); print("A/B Switch: Only image 2 available.")
                else: self.view_combined.set_pixmap(QPixmap()); print("A/B Switch: No images available.")
            else: # Slider ou Opacity
                self.update_comparison_image(pil1_comp, pil2_comp)
                current_comparison_pixmap = self.comparison_pixmap if self.comparison_pixmap else QPixmap()
                if not current_comparison_pixmap.isNull():
                    scene_rect = QRectF(current_comparison_pixmap.rect())
                    if self.current_mode == "slider": self.interactive_slider.set_scene_rect(scene_rect)
                    self.view_combined.setSceneRect(scene_rect)
                    self.view_combined.set_pixmap(current_comparison_pixmap)
                elif self.display_pixmap1 and not self.display_pixmap1.isNull(): self.view_combined.set_pixmap(self.display_pixmap1)
                elif self.display_pixmap2 and not self.display_pixmap2.isNull(): self.view_combined.set_pixmap(self.display_pixmap2)
                else: self.view_combined.set_pixmap(QPixmap())

    def update_comparison_image(self, pil1_comp=None, pil2_comp=None):
        if self.current_mode not in ["slider", "opacity"]:
            self.comparison_pixmap = None; return
        if pil1_comp is None and pil2_comp is None:
             pil1_comp, pil2_comp = self.prepare_display_images()
        pil_result = None; mode = self.current_mode

        if mode == "slider":
            if pil1_comp:
                pil_result = pil1_comp.copy()
                if pil2_comp:
                    slider_ratio = self.interactive_slider.get_position_ratio()
                    width, height = pil_result.size; split_x = int(width * slider_ratio)
                    if split_x < width:
                        img2_part = pil2_comp.crop((split_x, 0, width, height))
                        try: pil_result.paste(img2_part, (split_x, 0))
                        except ValueError: pil_result.paste(img2_part.convert("RGB"), (split_x, 0))
            elif pil2_comp: pil_result = pil2_comp.copy()
        elif mode == "opacity":
             if pil1_comp and pil2_comp:
                 try: pil_result = Image.blend(pil1_comp.convert("RGB"), pil2_comp.convert("RGB"), alpha=self.opacity_value)
                 except Exception as e: print(f"Error blending: {e}"); pil_result = pil1_comp
             elif pil1_comp: pil_result = pil1_comp
             elif pil2_comp: pil_result = pil2_comp

        if pil_result: self.comparison_pixmap = self.pil_to_qpixmap(pil_result)
        elif pil1_comp: self.comparison_pixmap = self.display_pixmap1
        elif pil2_comp: self.comparison_pixmap = self.display_pixmap2
        else: self.comparison_pixmap = QPixmap()

        if self.view_stack.currentIndex() == 1 and self.current_mode != "ab_switch":
            pix_to_show = self.comparison_pixmap if self.comparison_pixmap else QPixmap()
            self.view_combined.set_pixmap(pix_to_show)

    # --- Reset et Synchro ---
    def reset_all_views(self):
        if self.current_mode == "side_by_side": self.view1.reset_view(); self.view2.reset_view()
        else: self.view_combined.reset_view()

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

    # --- Barre de Statut ---
    def update_status_bar(self, scene_pos, view_index):
        img_coords, pixel_value = None, None; img_w, img_h = 0, 0
        pixmap_item = None; active_pixmap = None
        if view_index == 1 and self.current_mode == "side_by_side": pixmap_item = self.view1.get_pixmap_item()
        elif view_index == 2 and self.current_mode == "side_by_side": pixmap_item = self.view2.get_pixmap_item()
        elif view_index == 0 and self.current_mode != "side_by_side": pixmap_item = self.view_combined.get_pixmap_item()
        if pixmap_item: active_pixmap = pixmap_item.pixmap()
        if pixmap_item and active_pixmap and not active_pixmap.isNull():
            item_pos = pixmap_item.mapFromScene(scene_pos); x, y = int(item_pos.x()), int(item_pos.y())
            img_w, img_h = active_pixmap.width(), active_pixmap.height()
            if 0 <= x < img_w and 0 <= y < img_h:
                img_coords = (x, y)
                try:
                    qimg_to_read = active_pixmap.toImage()
                    if not qimg_to_read.isNull() and qimg_to_read.valid(x,y): color = QColor(qimg_to_read.pixel(x, y)); pixel_value = (color.red(), color.green(), color.blue())
                    else: pixel_value = "Invalid"
                except Exception: pixel_value = "Error"
        coords_text = f"Coords: ({img_coords[0]}, {img_coords[1]}) / ({img_w}x{img_h})" if img_coords else f"Coords: (N/A) / ({img_w}x{img_h})" if img_w and img_h else "Coords: (N/A)"
        rgb_text = f"RGB: {str(pixel_value)}" if pixel_value and pixel_value not in ["Error", "Out", "Invalid"] else f"RGB: ({pixel_value or 'N/A'})"
        self.lbl_status_coords.setText(coords_text); self.lbl_status_rgb.setText(rgb_text)

# --- Point d'Entrée ---
if __name__ == "__main__":
    if hasattr(QtCore.Qt, 'ApplicationAttribute'):
         QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
         QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    elif hasattr(QtCore.Qt, 'AA_EnableHighDpiScaling'):
         QApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling, True)
         QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps, True)
    app = QApplication(sys.argv); window = ImageComparerApp(); window.show(); sys.exit(app.exec())