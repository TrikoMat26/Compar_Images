import sys
import os
import math
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal

try:
    from PIL import Image, ImageQt
except ImportError:
    print("Warning: Pillow not found. Please install it if needed.")
    ImageQt = None

# Import du gestionnaire de fichiers récents
try:
    from recent_files import RecentFilesManager, RecentFilesMenu
except ImportError:
    print("Warning: recent_files.py not found. Recent files functionality will be disabled.")
    RecentFilesManager = None
    RecentFilesMenu = None

# --- Configuration ---
MAX_IMAGE_DIM_LOAD = 5000  # Augmenté de 3000 à 5000
DEFAULT_AB_SWITCH_INTERVAL = 500
MIN_AB_SWITCH_INTERVAL = 100
MAX_AB_SWITCH_INTERVAL = 2000
LIMIT_IMAGE_RESOLUTION = False  # Par défaut, on charge à pleine résolution

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
        self._rotation_angle = 0.0  # Angle de rotation en degrés
        self._rotation_mode = False  # Mode rotation avec Ctrl
        self._rotation_center = QtCore.QPointF()  # Centre de rotation
        self._last_rotation_pos = QtCore.QPointF()  # Dernière position pour le calcul de rotation

    def set_use_mask(self, use_mask: bool):
        self._use_mask = use_mask
        self.update()

    def set_slider_ratio(self, ratio: float):
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()
        
    def set_rotation(self, angle: float):
        """Définit l'angle de rotation en degrés."""
        self._rotation_angle = angle
        self.update()
        
    def get_rotation(self) -> float:
        """Retourne l'angle de rotation actuel en degrés."""
        return self._rotation_angle

    def paint(self, painter: QtGui.QPainter, option, widget=None):
        pm = self.pixmap()
        if pm.isNull():
            return
        w = pm.width()
        h = pm.height()
        if w <= 0 or h <= 0:
            return
            
        # Sauvegarder l'état du peintre
        painter.save()

        if not self._use_mask:
            # Pas de masquage => on dessine tout
            
            # Appliquer la rotation
            if self._rotation_angle != 0.0:
                # Calculer le centre de l'image
                center_x = w / 2
                center_y = h / 2
                # Transformer le peintre pour effectuer la rotation
                painter.translate(center_x, center_y)
                painter.rotate(self._rotation_angle)
                painter.translate(-center_x, -center_y)
            
            painter.drawPixmap(0, 0, pm)
            
        else:
            # Mode masqué => couper selon ratio (moitié gauche/droite)
            split_x = int(self._ratio * w)
            
            if self._rotation_angle != 0.0:
                # Avec rotation, on utilise un masque QPainterPath pour éviter les zones grises
                
                # Créer des chemins (paths) de masquage pour isoler la partie gauche ou droite
                path = QtGui.QPainterPath()
                
                if self._is_left:
                    # Pour l'image gauche, on crée un rectangle couvrant la partie gauche jusqu'à split_x
                    path.addRect(0, 0, split_x, h)
                else:
                    # Pour l'image droite, on crée un rectangle couvrant la partie droite à partir de split_x
                    path.addRect(split_x, 0, w - split_x, h)
                
                # Utiliser le chemin comme masque de découpe
                painter.setClipPath(path)
                
                # Calculer le centre de l'image pour la rotation
                center_x = w / 2
                center_y = h / 2
                
                # Appliquer la rotation
                painter.translate(center_x, center_y)
                painter.rotate(self._rotation_angle)
                painter.translate(-center_x, -center_y)
                
                # Dessiner le pixmap complet (sera masqué par le clipPath)
                painter.drawPixmap(0, 0, pm)
                
            else:
                # Sans rotation, on peut utiliser la méthode originale qui est plus efficace
                if self._is_left:
                    source_rect = QtCore.QRect(0, 0, split_x, h)
                    target_rect = QtCore.QRectF(0, 0, split_x, h)
                else:
                    source_rect = QtCore.QRect(split_x, 0, w - split_x, h)
                    target_rect = QtCore.QRectF(split_x, 0, w - split_x, h)

                if source_rect.width() > 0:
                    painter.drawPixmap(target_rect, pm, source_rect)
                
        # Restaurer l'état du peintre
        painter.restore()

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        # Vérifie si Ctrl est enfoncé pour le mode rotation
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if modifiers & QtCore.Qt.KeyboardModifier.ControlModifier:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._rotation_mode = True
                # Mémoriser le centre de l'item pour la rotation
                rect = self.boundingRect()
                self._rotation_center = rect.center()
                # Mémoriser la position initiale pour calculer l'angle
                self._last_rotation_pos = event.scenePos()
                event.accept()
                return
        # Si pas en mode rotation, comportement normal
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if self._rotation_mode and self.controller:
            # Calcul de l'angle de rotation basé sur le mouvement par rapport au centre
            current_pos = event.scenePos()
            
            # Convertir les positions en positions relatives au centre de l'item
            scene_center = self.mapToScene(self._rotation_center)
            
            # Calculer les vecteurs depuis le centre jusqu'aux positions
            vector_last = self._last_rotation_pos - scene_center
            vector_current = current_pos - scene_center
            
            # Calculer l'angle entre les deux vecteurs (en radians)
            # Utiliser atan2 pour obtenir l'angle signé
            angle_last = math.atan2(vector_last.y(), vector_last.x())
            angle_current = math.atan2(vector_current.y(), vector_current.x())
            
            # Calculer la différence d'angle en degrés
            angle_delta = (angle_current - angle_last) * (180.0 / math.pi)
            
            # Facteur de sensibilité pour contrôler la vitesse de rotation
            # Plus le facteur est petit, plus la rotation est lente et précise
            sensitivity = 0.2  # Réduit de 1.0 à 0.2 pour une rotation plus précise
            angle_delta *= sensitivity
            
            # Mettre à jour l'angle de rotation total
            new_angle = self._rotation_angle + angle_delta
            
            # Limiter l'angle entre -180 et 180 degrés
            while new_angle > 180.0:
                new_angle -= 360.0
            while new_angle < -180.0:
                new_angle += 360.0
                
            # Informer le contrôleur du changement d'angle
            self.controller.on_rotation_changed(self.item_id, new_angle)
            
            # Mettre à jour la position pour le prochain calcul
            self._last_rotation_pos = current_pos
            
            event.accept()
            return
        
        # Si pas en mode rotation, comportement normal
        super().mouseMoveEvent(event)
        
    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if self._rotation_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._rotation_mode = False
            event.accept()
            return
        
        # Si pas en mode rotation, comportement normal
        super().mouseReleaseEvent(event)


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
# 4) GridItem - Grille de référence
# -------------------------------------------------------------
class GridItem(QtWidgets.QGraphicsItem):
    """Affiche une grille de référence sur les images."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rect = QtCore.QRectF(0, 0, 100, 100)  # Rectangle par défaut
        self._grid_size = 50  # Taille des cellules de la grille en pixels
        self._color = QtGui.QColor(255, 0, 0, 100)  # Rouge semi-transparent
        self._line_width = 1.0
        self._visible = False
        self.setZValue(1000)  # S'assurer que la grille est au-dessus des images
        self.setVisible(self._visible)

    def boundingRect(self):
        return self._rect

    def paint(self, painter, option, widget=None):
        if not self._visible:
            return

        # Configurer le pinceau
        pen = QtGui.QPen(self._color)
        pen.setWidthF(self._line_width)
        pen.setStyle(QtCore.Qt.PenStyle.DashLine)  # Ligne pointillée
        painter.setPen(pen)

        # Dessiner les lignes horizontales
        y = 0
        while y <= self._rect.height():
            painter.drawLine(QtCore.QLineF(0, y, self._rect.width(), y))
            y += self._grid_size

        # Dessiner les lignes verticales
        x = 0
        while x <= self._rect.width():
            painter.drawLine(QtCore.QLineF(x, 0, x, self._rect.height()))
            x += self._grid_size

    def set_rect(self, rect):
        """Définit le rectangle de la grille."""
        self._rect = rect
        self.update()

    def set_grid_size(self, size):
        """Définit la taille des cellules de la grille."""
        self._grid_size = max(10, size)  # Taille minimale de 10 pixels
        self.update()

    def set_color(self, color):
        """Définit la couleur de la grille."""
        self._color = color
        self.update()

    def set_line_width(self, width):
        """Définit la largeur des lignes de la grille."""
        self._line_width = max(0.5, width)  # Largeur minimale de 0.5 pixel
        self.update()

    def set_visible(self, visible):
        """Active ou désactive l'affichage de la grille."""
        self._visible = visible
        self.setVisible(visible)
        self.update()

    def is_visible(self):
        """Indique si la grille est visible."""
        return self._visible

# -------------------------------------------------------------
# 5) ImageViewer
# -------------------------------------------------------------
class ImageViewer(QtWidgets.QGraphicsView):
    viewChanged = Signal()
    mouseMoved = Signal(QtCore.QPointF)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self._pixmap_item = QtWidgets.QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)

        # Ajouter la grille
        self._grid_item = GridItem()
        self._scene.addItem(self._grid_item)

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
                rect = QtCore.QRectF(pixmap.rect())
                self._scene.setSceneRect(rect)

                # Mettre à jour la taille de la grille pour qu'elle corresponde à l'image
                self._grid_item.set_rect(rect)

                if was_empty:
                    self.fitInView(self._pixmap_item, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
                    self._zoom = self.transform().m11()
                else:
                    self.setTransform(current_transform)
            else:
                self._pixmap_item.setPixmap(QtGui.QPixmap())

    def set_grid_visible(self, visible):
        """Active ou désactive l'affichage de la grille."""
        self._grid_item.set_visible(visible)

    def set_grid_size(self, size):
        """Définit la taille des cellules de la grille."""
        self._grid_item.set_grid_size(size)

    def set_grid_color(self, color):
        """Définit la couleur de la grille."""
        self._grid_item.set_color(color)

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
        self.setWindowTitle("Image Comparer")
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
        
        # État pour les modes de recalage
        self._ab_recalage_actif = False
        self._slider_recalage_actif = False

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

        # Initialiser le gestionnaire de fichiers récents
        if RecentFilesManager is not None:
            self.recent_files_manager = RecentFilesManager()
            self.has_recent_files = True
        else:
            self.has_recent_files = False

        # Appliquer le style moderne
        self.apply_modern_style()

        self.setup_ui()
        self.update_display()

    def apply_modern_style(self):
        """Applique un style moderne à l'application"""
        # Palette de couleurs moderne
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor(53, 53, 53))
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.ColorRole.Base, QtGui.QColor(25, 25, 25))
        palette.setColor(QtGui.QPalette.ColorRole.AlternateBase, QtGui.QColor(53, 53, 53))
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipBase, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.ColorRole.ToolTipText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.ColorRole.Text, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.ColorRole.Button, QtGui.QColor(53, 53, 53))
        palette.setColor(QtGui.QPalette.ColorRole.ButtonText, QtGui.QColor(255, 255, 255))
        palette.setColor(QtGui.QPalette.ColorRole.BrightText, QtGui.QColor(255, 0, 0))
        palette.setColor(QtGui.QPalette.ColorRole.Link, QtGui.QColor(42, 130, 218))
        palette.setColor(QtGui.QPalette.ColorRole.Highlight, QtGui.QColor(42, 130, 218))
        palette.setColor(QtGui.QPalette.ColorRole.HighlightedText, QtGui.QColor(255, 255, 255))

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
        # Configuration du menu principal
        self.setup_menu()

        # Configuration de la barre d'outils
        self.setup_toolbar()

        # Widget central
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QVBoxLayout(main_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # Panneau de contrôle
        control_panel = QtWidgets.QFrame()
        control_panel.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        control_panel.setFrameShadow(QtWidgets.QFrame.Shadow.Raised)
        control_layout = QtWidgets.QHBoxLayout(control_panel)
        control_layout.setContentsMargins(5, 5, 5, 5)
        control_layout.setSpacing(10)
        main_layout.addWidget(control_panel)

        # Chargement
        load_group = QtWidgets.QGroupBox("Images")
        load_layout = QtWidgets.QVBoxLayout(load_group)
        btn_load1 = QtWidgets.QPushButton("Charger Image 1")
        btn_load1.clicked.connect(lambda: self.load_image(1))
        btn_load1.setToolTip("Charger la première image à comparer (Image A)")
        self.lbl_img1 = QtWidgets.QLabel("Aucune image 1")
        self.lbl_img1.setWordWrap(True)

        btn_load2 = QtWidgets.QPushButton("Charger Image 2")
        btn_load2.clicked.connect(lambda: self.load_image(2))
        btn_load2.setToolTip("Charger la seconde image à comparer (Image B)")
        self.lbl_img2 = QtWidgets.QLabel("Aucune image 2")
        self.lbl_img2.setWordWrap(True)

        load_layout.addWidget(btn_load1)
        load_layout.addWidget(self.lbl_img1)
        load_layout.addStretch()
        load_layout.addWidget(btn_load2)
        load_layout.addWidget(self.lbl_img2)
        control_layout.addWidget(load_group)

        # Modes de comparaison
        mode_group = QtWidgets.QGroupBox("Mode de comparaison")
        mode_layout = QtWidgets.QVBoxLayout(mode_group)
        control_layout.addWidget(mode_group, 1)

        # Boutons radio avec disposition verticale
        self.radio_side = QtWidgets.QRadioButton("Côte à côte")
        self.radio_side.setChecked(True)
        self.radio_side.toggled.connect(lambda c: self.set_mode("side_by_side") if c else None)
        self.radio_side.setToolTip("Affiche les deux images côte à côte pour une comparaison directe")
        mode_layout.addWidget(self.radio_side)

        self.radio_slider = QtWidgets.QRadioButton("Curseur")
        self.radio_slider.toggled.connect(lambda c: self.set_mode("slider") if c else None)
        self.radio_slider.setToolTip("Affiche une barre de séparation glissable entre les deux images")
        mode_layout.addWidget(self.radio_slider)

        self.radio_ab_switch = QtWidgets.QRadioButton("A/B Switch")
        self.radio_ab_switch.toggled.connect(lambda c: self.set_mode("ab_switch") if c else None)
        self.radio_ab_switch.setToolTip("Alterne automatiquement entre les deux images pour détecter les différences")
        mode_layout.addWidget(self.radio_ab_switch)

        # Options spécifiques au mode
        self.options_stack = QtWidgets.QStackedWidget()
        mode_layout.addWidget(self.options_stack)

        # Page vide pour les modes sans options
        self.options_stack.addWidget(QtWidgets.QWidget())

        # Page A/B switch
        ab_switch_widget = QtWidgets.QWidget()
        ab_switch_layout = QtWidgets.QVBoxLayout(ab_switch_widget)

        speed_label = QtWidgets.QLabel("Vitesse de basculement :")
        ab_switch_layout.addWidget(speed_label)

        speed_control_layout = QtWidgets.QHBoxLayout()
        self.slider_ab_speed = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_ab_speed.setRange(MIN_AB_SWITCH_INTERVAL, MAX_AB_SWITCH_INTERVAL)
        self.slider_ab_speed.setValue(self.ab_switch_interval)
        self.slider_ab_speed.valueChanged.connect(self.on_ab_speed_changed)
        self.slider_ab_speed.setToolTip("Ajuste la vitesse de basculement entre les images A et B")
        speed_control_layout.addWidget(self.slider_ab_speed)

        self.lbl_ab_speed_value = QtWidgets.QLabel(f"{self.ab_switch_interval} ms")
        speed_control_layout.addWidget(self.lbl_ab_speed_value)

        ab_switch_layout.addLayout(speed_control_layout)
        self.options_stack.addWidget(ab_switch_widget)

        # Options d'ajustement
        adjust_group = QtWidgets.QGroupBox("Ajustement de taille")
        adjust_layout = QtWidgets.QVBoxLayout(adjust_group)

        self.combo_size_adjust = QtWidgets.QComboBox()
        for key, label in self.size_adjust_options.items():
            self.combo_size_adjust.addItem(label, key)
        self.combo_size_adjust.setCurrentText(self.size_adjust_options[self.size_adjust_mode])
        self.combo_size_adjust.currentIndexChanged.connect(self.on_size_adjust_changed)
        self.combo_size_adjust.setToolTip("Définit comment les images de tailles différentes sont ajustées pour la comparaison")
        adjust_layout.addWidget(self.combo_size_adjust)

        control_layout.addWidget(adjust_group)

        # Options de vue
        view_group = QtWidgets.QGroupBox("Options de vue")
        view_layout = QtWidgets.QVBoxLayout(view_group)

        self.check_link_views = QtWidgets.QCheckBox("Lier les vues")
        self.check_link_views.setChecked(self.link_views_enabled)
        self.check_link_views.toggled.connect(self.on_link_views_toggled)
        self.check_link_views.setToolTip("Synchronise le zoom et le déplacement des deux vues")
        view_layout.addWidget(self.check_link_views)

        # Option pour limiter la résolution des images
        self.check_limit_resolution = QtWidgets.QCheckBox("Limiter la résolution")
        self.check_limit_resolution.setChecked(LIMIT_IMAGE_RESOLUTION)
        self.check_limit_resolution.toggled.connect(self.on_limit_resolution_toggled)
        self.check_limit_resolution.setToolTip("Limite la résolution des images pour améliorer les performances")
        view_layout.addWidget(self.check_limit_resolution)

        self.check_high_quality = QtWidgets.QCheckBox("Rendu haute qualité")
        self.check_high_quality.setChecked(True)
        self.check_high_quality.setToolTip("Améliore la qualité du rendu des images (peut ralentir l'affichage)")
        view_layout.addWidget(self.check_high_quality)

        view_layout.addStretch()

        btn_reset_view = QtWidgets.QPushButton("Réinitialiser la vue")
        btn_reset_view.clicked.connect(self.reset_all_views)
        btn_reset_view.setToolTip("Réinitialise le zoom et la position des images")
        view_layout.addWidget(btn_reset_view)

        control_layout.addWidget(view_group)

        # Zone d'affichage
        self.view1 = ImageViewer()
        self.view2 = ImageViewer()
        self.view_combined = ImageViewer()

        # Connecter l'option de qualité
        self.check_high_quality.toggled.connect(self.on_high_quality_toggled)

        # Créer le widget de contrôle de rotation (initialement masqué)
        self.rotation_controls_widget = QtWidgets.QWidget()
        rotation_controls_layout = QtWidgets.QVBoxLayout(self.rotation_controls_widget)
        
        # Combo pour sélectionner l'image active pour la rotation
        self.combo_active_image = QtWidgets.QComboBox()
        self.combo_active_image.addItem("Image 1", 1)
        self.combo_active_image.addItem("Image 2", 2)
        rotation_controls_layout.addWidget(QtWidgets.QLabel("Rotation rapide:"))
        rotation_controls_layout.addWidget(self.combo_active_image)
        
        # Slider pour la rotation rapide
        rotation_slider_layout = QtWidgets.QHBoxLayout()
        self.slider_quick_rotation = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_quick_rotation.setRange(-180, 180)
        self.slider_quick_rotation.setValue(0)
        self.slider_quick_rotation.setTickPosition(QtWidgets.QSlider.TickPosition.TicksBelow)
        self.slider_quick_rotation.setTickInterval(45)
        self.slider_quick_rotation.valueChanged.connect(self.on_quick_rotation_changed)
        rotation_slider_layout.addWidget(self.slider_quick_rotation)
        self.lbl_rotation_value = QtWidgets.QLabel("0°")
        rotation_slider_layout.addWidget(self.lbl_rotation_value)
        rotation_controls_layout.addLayout(rotation_slider_layout)
        
        # Boutons de contrôle de rotation
        rotation_buttons_layout = QtWidgets.QHBoxLayout()
        btn_reset_rotation = QtWidgets.QPushButton("Réinitialiser")
        btn_reset_rotation.clicked.connect(lambda: self.reset_rotation(self.combo_active_image.currentData()))
        rotation_buttons_layout.addWidget(btn_reset_rotation)
        
        btn_copy_1to2 = QtWidgets.QPushButton("1 → 2")
        btn_copy_1to2.setToolTip("Copier l'angle de l'image 1 vers l'image 2")
        btn_copy_1to2.clicked.connect(lambda: self.copy_rotation(1, 2))
        rotation_buttons_layout.addWidget(btn_copy_1to2)
        
        btn_copy_2to1 = QtWidgets.QPushButton("2 → 1")
        btn_copy_2to1.setToolTip("Copier l'angle de l'image 2 vers l'image 1")
        btn_copy_2to1.clicked.connect(lambda: self.copy_rotation(2, 1))
        rotation_buttons_layout.addWidget(btn_copy_2to1)
        
        rotation_controls_layout.addLayout(rotation_buttons_layout)
        rotation_controls_layout.addStretch()
        
        # Ajouter des informations sur l'utilisation
        help_label = QtWidgets.QLabel("Pour une rotation précise, maintenez Ctrl+Clic gauche sur l'image et déplacez la souris")
        help_label.setWordWrap(True)
        rotation_controls_layout.addWidget(help_label)
        
        # Ajouter le widget de contrôle au layout principal
        main_layout.addWidget(self.rotation_controls_widget)
        self.rotation_controls_widget.setVisible(False)  # Masqué par défaut

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

        # Barre de statut améliorée
        self.statusBar = QtWidgets.QStatusBar()
        self.setStatusBar(self.statusBar)
        self.lbl_status_coords = QtWidgets.QLabel("Coords: (N/A, N/A)")
        self.lbl_status_rgb = QtWidgets.QLabel("RGB: (N/A)")
        self.lbl_status_zoom = QtWidgets.QLabel("Zoom: 100%")
        self.statusBar.addPermanentWidget(self.lbl_status_coords)
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding, QtWidgets.QSizePolicy.Policy.Preferred)
        self.statusBar.addPermanentWidget(spacer, 1)
        self.statusBar.addPermanentWidget(self.lbl_status_rgb)
        self.statusBar.addPermanentWidget(self.lbl_status_zoom)

    def setup_toolbar(self):
        """Configure la barre d'outils principale."""
        self.toolbar = QtWidgets.QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QtCore.QSize(24, 24))
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        # Actions de la barre d'outils
        self.action_open_image1 = QtGui.QAction("Ouvrir Image 1", self)
        self.action_open_image1.setIcon(QtGui.QIcon.fromTheme("document-open"))
        self.action_open_image1.triggered.connect(lambda: self.load_image(1))
        self.toolbar.addAction(self.action_open_image1)

        self.action_open_image2 = QtGui.QAction("Ouvrir Image 2", self)
        self.action_open_image2.setIcon(QtGui.QIcon.fromTheme("document-open"))
        self.action_open_image2.triggered.connect(lambda: self.load_image(2))
        self.toolbar.addAction(self.action_open_image2)

        self.toolbar.addSeparator()

        self.action_reset_view = QtGui.QAction("Réinitialiser la vue", self)
        self.action_reset_view.setIcon(QtGui.QIcon.fromTheme("view-refresh"))
        self.action_reset_view.triggered.connect(self.reset_all_views)
        self.toolbar.addAction(self.action_reset_view)

    def setup_menu(self):
        """Configure le menu principal."""
        menubar = self.menuBar()

        # Menu Fichier
        file_menu = menubar.addMenu("&Fichier")

        open_image1_action = QtGui.QAction("Ouvrir Image &1...", self)
        open_image1_action.setShortcut("Ctrl+1")
        open_image1_action.triggered.connect(lambda: self.load_image(1))
        file_menu.addAction(open_image1_action)

        open_image2_action = QtGui.QAction("Ouvrir Image &2...", self)
        open_image2_action.setShortcut("Ctrl+2")
        open_image2_action.triggered.connect(lambda: self.load_image(2))
        file_menu.addAction(open_image2_action)

        file_menu.addSeparator()

        # Menu des fichiers récents
        if self.has_recent_files:
            self.recent_files_menu = RecentFilesMenu(self, self.recent_files_manager)

            # Ajouter un raccourci clavier pour accéder au menu des fichiers récents
            recent_files_action = QtGui.QAction("Fichiers &récents", self)
            recent_files_action.setShortcut("Ctrl+R")
            recent_files_action.setIcon(QtGui.QIcon.fromTheme("document-open-recent", QtGui.QIcon.fromTheme("document-open")))

            # Ajouter directement les actions des fichiers récents au menu principal
            # pour une meilleure visibilité
            file_menu.addAction(recent_files_action)

            # Ajouter le sous-menu des fichiers récents
            recent_files_action.setMenu(self.recent_files_menu.recent_menu)

            # Ajouter un séparateur
            file_menu.addSeparator()

            # Afficher un message de débogage
            print("Menu des fichiers récents ajouté au menu principal")

        exit_action = QtGui.QAction("&Quitter", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        # Menu Vue
        view_menu = menubar.addMenu("&Vue")

        zoom_in_action = QtGui.QAction("Zoom &avant", self)
        zoom_in_action.setShortcut("Ctrl++")
        zoom_in_action.triggered.connect(self.zoom_in)
        view_menu.addAction(zoom_in_action)

        zoom_out_action = QtGui.QAction("Zoom &arrière", self)
        zoom_out_action.setShortcut("Ctrl+-")
        zoom_out_action.triggered.connect(self.zoom_out)
        view_menu.addAction(zoom_out_action)

        reset_zoom_action = QtGui.QAction("&Réinitialiser le zoom", self)
        reset_zoom_action.setShortcut("Ctrl+0")
        reset_zoom_action.triggered.connect(self.reset_all_views)
        view_menu.addAction(reset_zoom_action)

        view_menu.addSeparator()

        side_by_side_action = QtGui.QAction("Mode &côte à côte", self)
        side_by_side_action.setShortcut("Ctrl+S")
        side_by_side_action.triggered.connect(lambda: self.set_mode_from_menu("side_by_side"))
        view_menu.addAction(side_by_side_action)

        slider_action = QtGui.QAction("Mode &curseur", self)
        slider_action.setShortcut("Ctrl+L")
        slider_action.triggered.connect(lambda: self.set_mode_from_menu("slider"))
        view_menu.addAction(slider_action)

        ab_switch_action = QtGui.QAction("Mode &A/B Switch", self)
        ab_switch_action.setShortcut("Ctrl+A")
        ab_switch_action.triggered.connect(lambda: self.set_mode_from_menu("ab_switch"))
        view_menu.addAction(ab_switch_action)

        # Menu Aide
        help_menu = menubar.addMenu("&Aide")

        about_action = QtGui.QAction("&À propos", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        keyboard_shortcuts_action = QtGui.QAction("&Raccourcis clavier", self)
        keyboard_shortcuts_action.triggered.connect(self.show_keyboard_shortcuts)
        help_menu.addAction(keyboard_shortcuts_action)

    def zoom_in(self):
        """Zoom avant sur la vue active."""
        if self.current_mode == "side_by_side":
            zoom_factor = 1.15
            self.view1.scale(zoom_factor, zoom_factor)
            self.view1._zoom *= zoom_factor
            if self.link_views_enabled:
                self.view2.scale(zoom_factor, zoom_factor)
                self.view2._zoom *= zoom_factor
            self.update_zoom_status()
        else:
            zoom_factor = 1.15
            self.view_combined.scale(zoom_factor, zoom_factor)
            self.view_combined._zoom *= zoom_factor
            self.update_zoom_status()

    def zoom_out(self):
        """Zoom arrière sur la vue active."""
        if self.current_mode == "side_by_side":
            zoom_factor = 1.15
            self.view1.scale(1/zoom_factor, 1/zoom_factor)
            self.view1._zoom /= zoom_factor
            if self.link_views_enabled:
                self.view2.scale(1/zoom_factor, 1/zoom_factor)
                self.view2._zoom /= zoom_factor
            self.update_zoom_status()
        else:
            zoom_factor = 1.15
            self.view_combined.scale(1/zoom_factor, 1/zoom_factor)
            self.view_combined._zoom /= zoom_factor
            self.update_zoom_status()

    def update_zoom_status(self):
        """Met à jour l'affichage du niveau de zoom dans la barre d'état."""
        if self.current_mode == "side_by_side":
            zoom_level = int(self.view1._zoom * 100)
        else:
            zoom_level = int(self.view_combined._zoom * 100)
        self.lbl_status_zoom.setText(f"Zoom: {zoom_level}%")

    def set_mode_from_menu(self, mode):
        """Change le mode de comparaison depuis le menu."""
        if mode == "side_by_side":
            self.radio_side.setChecked(True)
        elif mode == "slider":
            self.radio_slider.setChecked(True)
        elif mode == "ab_switch":
            self.radio_ab_switch.setChecked(True)

    def show_about_dialog(self):
        """Affiche la boîte de dialogue 'À propos'."""
        QtWidgets.QMessageBox.about(self, "À propos de Image Comparer",
                                  "<h3>Image Comparer</h3>"
                                  "<p>Une application de comparaison d'images avec plusieurs modes de visualisation.</p>"
                                  "<p>Version: 1.0</p>")

    def show_keyboard_shortcuts(self):
        """Affiche la liste des raccourcis clavier."""
        shortcuts_text = """
        <h3>Raccourcis clavier</h3>
        <table>
            <tr><td colspan="2"><b>Fichiers</b></td></tr>
            <tr><td><b>Ctrl+1</b></td><td>Ouvrir Image 1</td></tr>
            <tr><td><b>Ctrl+2</b></td><td>Ouvrir Image 2</td></tr>
            <tr><td><b>Ctrl+R</b></td><td>Menu des fichiers récents</td></tr>
            <tr><td><b>Ctrl+Alt+1..9</b></td><td>Ouvrir l'image 1 récente correspondante</td></tr>
            <tr><td><b>Ctrl+Shift+1..9</b></td><td>Ouvrir la paire d'images récente correspondante</td></tr>
            <tr><td><b>Ctrl+Q</b></td><td>Quitter</td></tr>

            <tr><td colspan="2"><b>Modes de visualisation</b></td></tr>
            <tr><td><b>Ctrl+S</b></td><td>Mode côte à côte</td></tr>
            <tr><td><b>Ctrl+L</b></td><td>Mode curseur</td></tr>
            <tr><td><b>Ctrl+A</b></td><td>Mode A/B Switch</td></tr>

            <tr><td colspan="2"><b>Navigation</b></td></tr>
            <tr><td><b>Ctrl++</b></td><td>Zoom avant</td></tr>
            <tr><td><b>Ctrl+-</b></td><td>Zoom arrière</td></tr>
            <tr><td><b>Ctrl+0</b></td><td>Réinitialiser le zoom</td></tr>
        </table>
        """
        msg_box = QtWidgets.QMessageBox(self)
        msg_box.setWindowTitle("Raccourcis clavier")
        msg_box.setTextFormat(QtCore.Qt.TextFormat.RichText)
        msg_box.setText(shortcuts_text)
        msg_box.exec()

    def load_recent_file(self, filepath, is_image1):
        """Charge un fichier récent."""
        print(f"Tentative de chargement du fichier récent : {filepath} (Image {1 if is_image1 else 2})")

        if not filepath:
            print("Erreur : Chemin de fichier vide")
            return False

        if os.path.exists(filepath):
            image_num = 1 if is_image1 else 2
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

                # Mettre à jour la barre d'état
                self.statusBar.showMessage(f"Image {image_num} chargée : {os.path.basename(filepath)}", 3000)

                # Ajouter aux fichiers récents
                if self.has_recent_files:
                    self.recent_files_manager.add_recent_file(filepath, is_image1=(image_num == 1))
                    self.recent_files_menu.update_menus()
                    # Configurer les gestionnaires d'événements pour les fichiers récents
                    self.setup_recent_files_handlers()

                return True

            except Exception as e:
                error_msg = f"Impossible de charger l'image :\n{e}"
                print(error_msg)
                QtWidgets.QMessageBox.critical(self, "Erreur de chargement", error_msg)
                return False
        else:
            error_msg = f"Le fichier {filepath} n'existe plus."
            print(error_msg)
            QtWidgets.QMessageBox.warning(
                self,
                "Fichier introuvable",
                error_msg
            )
            # Supprimer le fichier de la liste des fichiers récents
            if self.has_recent_files:
                self.recent_files_manager.load_recent_files()  # Recharger pour supprimer les fichiers inexistants
                self.recent_files_menu.update_menus()
            return False

    def load_recent_pair(self, image1_path, image2_path):
        """Charge une paire d'images récente."""
        print(f"Tentative de chargement de la paire récente : {image1_path} & {image2_path}")

        if not image1_path or not image2_path:
            print("Erreur : Chemins de fichiers vides")
            return False

        if os.path.exists(image1_path) and os.path.exists(image2_path):
            success1 = self.load_recent_file(image1_path, True)
            success2 = self.load_recent_file(image2_path, False)

            if success1 and success2:
                # Ajouter la paire aux paires récentes
                if self.has_recent_files:
                    self.recent_files_manager.add_recent_pair(image1_path, image2_path)
                    self.recent_files_menu.update_menus()

                self.statusBar.showMessage(f"Paire d'images chargée", 3000)
                return True
            else:
                print("Erreur lors du chargement d'un ou plusieurs fichiers de la paire")
                return False
        else:
            error_msg = "Un ou plusieurs fichiers de cette paire n'existent plus."
            print(error_msg)
            QtWidgets.QMessageBox.warning(
                self,
                "Fichier(s) introuvable(s)",
                error_msg
            )
            # Supprimer la paire de la liste des paires récentes
            if self.has_recent_files:
                self.recent_files_manager.load_recent_files()  # Recharger pour supprimer les paires invalides
                self.recent_files_menu.update_menus()
            return False

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
        self.lbl_ab_speed_value.setText(f"{value} ms")
        if self.ab_timer.isActive():
            self.ab_timer.setInterval(self.ab_switch_interval)
            print(f"A/B Timer updated to: {self.ab_switch_interval} ms")

    def on_high_quality_toggled(self, checked):
        """Active ou désactive le rendu haute qualité."""
        # Appliquer le paramètre à toutes les vues
        # Antialiasing pour les lignes et formes
        self.view1.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, checked)
        self.view2.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, checked)
        self.view_combined.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, checked)

        # SmoothPixmapTransform pour les images
        self.view1.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, checked)
        self.view2.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, checked)
        self.view_combined.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, checked)

        # TextAntialiasing pour le texte
        self.view1.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, checked)
        self.view2.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, checked)
        self.view_combined.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, checked)

        # Définir la qualité de transformation
        if checked:
            # Haute qualité - utiliser une transformation bilinéaire
            self.view1._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
            self.view2._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
            self.view_combined._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
        else:
            # Qualité standard - utiliser une transformation rapide
            self.view1._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.FastTransformation)
            self.view2._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.FastTransformation)
            self.view_combined._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.FastTransformation)

        # Mettre à jour l'affichage
        self.view1.viewport().update()
        self.view2.viewport().update()
        self.view_combined.viewport().update()

        # Afficher un message dans la barre d'état
        quality_text = "haute" if checked else "standard"
        self.statusBar.showMessage(f"Qualité de rendu : {quality_text}", 2000)

    def on_show_grid_toggled(self, checked):
        """Active ou désactive l'affichage de la grille.

        Note: Cette fonctionnalité est désactivée dans cette version.
        """
        # Fonctionnalité désactivée
        pass

    def on_link_views_toggled(self, checked):
        """Gère l'activation/désactivation de la liaison des vues."""
        self.link_views_enabled = checked
        print(f"Link Views -> {checked}")

        # Afficher un message dans la barre d'état
        if checked:
            self.statusBar.showMessage("Vues liées : les deux images se déplacent ensemble", 2000)
        else:
            self.statusBar.showMessage("Vues indépendantes : chaque image peut être déplacée et pivotée séparément", 2000)

        if self.current_mode == "slider":
            # ... code existant pour le mode slider ...
            if checked:
                # Sortie du mode recalage
                self._slider_recalage_actif = False
                
                # Capture précise de l'offset actuel entre les images
                x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                x2, y2 = self.item2.pos().x(), self.item2.pos().y()
                self._slider_offset_x = x2 - x1
                self._slider_offset_y = y2 - y1
                
                # Mémoriser l'angle de rotation pour le passage au mode normal
                rotation_angle = self.item2.get_rotation() - self.item1.get_rotation()
                
                # Calcul de la position centrale entre les deux images
                w1 = self.item1.pixmap().width()
                h1 = self.item1.pixmap().height()
                
                # Rétablir le masquage des images
                self.item1.set_use_mask(True)
                self.item2.set_use_mask(True)
                self.item1.setOpacity(1.0)
                self.item2.setOpacity(1.0)
                
                # Désactiver le déplacement des images en mode curseur normal
                self.disable_drag_for_slider(self.item1)
                self.disable_drag_for_slider(self.item2)
                
                # Mise à jour du rectangle de scène pour le slider
                self.interactive_slider.set_scene_rect(QtCore.QRectF(x1, y1, w1, h1))
                
                # Si les images ont été décalées horizontalement pendant le recalage,
                # nous devons ajuster la position du ratio du slider pour qu'elle
                # corresponde à la jonction visuelle entre les deux images
                if abs(self._slider_offset_x) > 0.5:  # S'il y a eu un décalage horizontal significatif
                    # Calculer le nouveau ratio pour que la ligne du slider corresponde à la jonction
                    # Le ratio est calculé pour que:
                    # - Si image2 est décalée vers la droite (offset_x positif), le slider est plus à droite
                    # - Si image2 est décalée vers la gauche (offset_x négatif), le slider est plus à gauche
                    offset_ratio = self._slider_offset_x / w1
                    new_ratio = 0.5 - offset_ratio / 2
                    # Limiter le ratio entre 0.1 et 0.9 pour éviter des situations extrêmes
                    new_ratio = max(0.1, min(0.9, new_ratio))
                    
                    # Définir le nouveau ratio
                    self.interactive_slider.set_position_ratio(new_ratio)
                else:
                    # Récupérer la position actuelle du ratio (milieu par défaut si nouveau)
                    current_ratio = self.interactive_slider.get_position_ratio()
                    self.interactive_slider.set_position_ratio(current_ratio)
                
                # Récupérer le ratio final (qu'il ait été ajusté ou non)
                final_ratio = self.interactive_slider.get_position_ratio()
                
                # Réactiver la visibilité du slider
                self.interactive_slider.setVisible(True)
                
                # Appliquer le ratio aux masques des images
                self.on_slider_ratio_update(final_ratio)
                
                # Cacher les contrôles de rotation
                self.rotation_controls_widget.setVisible(False)
            else:
                # Activer le mode recalage
                self._slider_recalage_actif = True
                
                # Désactiver le masquage et régler la transparence
                self.item1.set_use_mask(False)
                self.item2.set_use_mask(False)
                self.item1.setOpacity(0.5)
                self.item2.setOpacity(0.5)
                
                # Cacher le slider pendant le recalage
                self.interactive_slider.setVisible(False)
                
                # Réactiver le déplacement libre des images
                self.enable_drag(self.item1)
                self.enable_drag(self.item2)
                
                # Afficher les contrôles de rotation
                self.rotation_controls_widget.setVisible(True)

        elif self.current_mode == "ab_switch":
            if checked:
                # Sortie du mode recalage -> mode normal AB switch
                self._ab_recalage_actif = False
                
                # Capturer la position relative actuelle
                x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                x2, y2 = self.item2.pos().x(), self.item2.pos().y()
                
                # Pour garantir que les centres des images restent alignés après rotation,
                # on calcule l'offset entre leurs centres plutôt qu'entre leurs coins
                w1 = self.item1.pixmap().width()
                h1 = self.item1.pixmap().height()
                w2 = self.item2.pixmap().width()
                h2 = self.item2.pixmap().height()
                
                # Calculer les centres des deux images
                center_x1 = x1 + w1/2
                center_y1 = y1 + h1/2
                center_x2 = x2 + w2/2
                center_y2 = y2 + h2/2
                
                # Calculer l'offset entre les centres
                center_offset_x = center_x2 - center_x1
                center_offset_y = center_y2 - center_y1
                
                # Mémoriser l'offset pour l'utiliser dans switch_ab_image
                # Offset ajusté pour tenir compte des dimensions des images
                self._slider_offset_x = center_offset_x
                self._slider_offset_y = center_offset_y
                
                # Réinitialiser l'affichage avec l'image 1 et sa rotation
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                
                # Créer une version transformée du pixmap si nécessaire (pour la rotation)
                current_rotation1 = self.item1.get_rotation()
                if abs(current_rotation1) > 0.01:
                    # Appliquer la rotation à l'image 1
                    transform = QtGui.QTransform()
                    w = self.display_pixmap1.width()
                    h = self.display_pixmap1.height()
                    center_x = w / 2
                    center_y = h / 2
                    transform.translate(center_x, center_y)
                    transform.rotate(current_rotation1)
                    transform.translate(-center_x, -center_y)
                    rotated_pixmap = self.display_pixmap1.transformed(transform, QtCore.Qt.TransformationMode.SmoothTransformation)
                    standard_pixmap_item.setPixmap(rotated_pixmap)
                else:
                    standard_pixmap_item.setPixmap(self.display_pixmap1)
                
                # Positionner l'image au centre calculé de l'image 1
                # Tenir compte du décalage potentiel causé par la rotation
                if abs(current_rotation1) > 0.01:
                    # Si l'image est pivotée, utiliser la position du centre original
                    standard_pixmap_item.setPos(x1, y1)
                else:
                    standard_pixmap_item.setPos(x1, y1)

                # Masquer les items de recalage
                self.item1.setVisible(False)
                self.item2.setVisible(False)

                # Cacher les contrôles de rotation
                self.rotation_controls_widget.setVisible(False)

                # Démarrer le timer
                self.ab_showing_image1 = True
                if not self.ab_timer.isActive():
                    self.ab_timer.start()
                    print("A/B Timer started after recalage")
            else:
                # Activer le mode recalage manuel
                self._ab_recalage_actif = True
                
                # Arrêter le timer
                self.ab_timer.stop()
                print("A/B Timer stopped for recalage")

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
                
                # Afficher les contrôles de rotation
                self.rotation_controls_widget.setVisible(True)

    def on_slider_ratio_update(self, ratio: float):
        if self.current_mode == "slider":
            if self.link_views_enabled:
                # En mode normal (avec vues liées), nous devons ajuster le ratio en fonction de l'offset
                x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                x2, y2 = self.item2.pos().x(), self.item2.pos().y()
                w1 = self.item1.pixmap().width()
                
                # Calcul du décalage relatif pour ajuster où la coupure apparaît visuellement
                if abs(self._slider_offset_x) > 0.5:  # S'il y a un offset horizontal significatif
                    # Ajuster le ratio de chaque item individuellement pour tenir compte du décalage
                    # L'idée est que la même position physique dans la vue correspond à des ratios 
                    # différents pour chaque item, en raison de leur décalage
                    ratio1 = ratio
                    ratio2 = ratio
                    
                    # Si l'image 2 est décalée vers la droite, son ratio doit être plus petit
                    # que le ratio de l'image 1 pour que la coupe visuelle soit alignée
                    if self._slider_offset_x > 0:
                        # Calculer le décalage en proportion de la largeur de l'image
                        offset_proportion = self._slider_offset_x / w1
                        ratio2 = max(0.0, min(1.0, ratio - offset_proportion))
                    # Si l'image 2 est décalée vers la gauche, son ratio doit être plus grand
                    elif self._slider_offset_x < 0:
                        offset_proportion = -self._slider_offset_x / w1
                        ratio2 = max(0.0, min(1.0, ratio + offset_proportion))
                    
                    self.item1.set_slider_ratio(ratio1)
                    self.item2.set_slider_ratio(ratio2)
                else:
                    # Si le décalage est négligeable, utiliser le même ratio
                    self.item1.set_slider_ratio(ratio)
                    self.item2.set_slider_ratio(ratio)
                
            else:
                # En mode recalage (vues non liées) ou sans décalage significatif,
                # on applique simplement le même ratio aux deux items
                self.item1.set_slider_ratio(ratio)
                self.item2.set_slider_ratio(ratio)
                
            # S'assurer que la ligne est toujours à la bonne position par rapport aux items
            if self.interactive_slider:
                # Recalculer le rectangle de scène basé sur les positions actuelles des items
                x1, y1 = self.item1.pos().x(), self.item1.pos().y()
                w1 = self.item1.pixmap().width()
                h1 = self.item1.pixmap().height()
                current_ratio = self.interactive_slider.get_position_ratio()
                self.interactive_slider.set_scene_rect(QtCore.QRectF(x1, y1, w1, h1))
                self.interactive_slider.set_position_ratio(current_ratio)

    def switch_ab_image(self):
        if self.current_mode != "ab_switch":
            self.ab_timer.stop()
            return

        if not self.display_pixmap1 or not self.display_pixmap2:
            self.ab_timer.stop()
            return

        self.ab_showing_image1 = not self.ab_showing_image1
        
        # En mode recalage (lier les vues désactivé) on utilise des MaskedOrFullPixmapItem,
        # qui gèrent déjà la rotation correctement. Rien à faire ici.
        if not self.link_views_enabled:
            return
        
        # En mode normal (lier les vues activé), on alterne entre les images
        # Il faut prendre en compte la rotation configurée pour chaque image
        pixmap_to_show = self.display_pixmap1 if self.ab_showing_image1 else self.display_pixmap2
        current_rotation = self.item1.get_rotation() if self.ab_showing_image1 else self.item2.get_rotation()

        if pixmap_to_show and not pixmap_to_show.isNull():
            standard_pixmap_item = self.view_combined.get_pixmap_item()
            
            # Appliquer d'abord la rotation si nécessaire
            if abs(current_rotation) > 0.01:  # Seuil pour éviter des transformations inutiles
                # Créer une transformation pour appliquer la rotation
                transform = QtGui.QTransform()
                
                # Calculer le centre de l'image
                w = pixmap_to_show.width()
                h = pixmap_to_show.height()
                center_x = w / 2
                center_y = h / 2
                
                # Appliquer la rotation autour du centre
                transform.translate(center_x, center_y)
                transform.rotate(current_rotation)
                transform.translate(-center_x, -center_y)
                
                # Appliquer la transformation à l'image
                rotated_pixmap = pixmap_to_show.transformed(transform, QtCore.Qt.TransformationMode.SmoothTransformation)
                standard_pixmap_item.setPixmap(rotated_pixmap)
            else:
                # Pas de rotation nécessaire
                standard_pixmap_item.setPixmap(pixmap_to_show)

            # IMPORTANT: Conserver les positions de référence des deux images
            # pour placer correctement l'image courante
            x1 = 0  # Position initiale de l'image 1
            y1 = 0
            
            # Calculer les positions et dimensins des images
            w1 = self.display_pixmap1.width()
            h1 = self.display_pixmap1.height()
            w2 = self.display_pixmap2.width()
            h2 = self.display_pixmap2.height()
            
            # Déterminer les dimensions du pixmap après rotation (si applicable)
            current_pixmap = standard_pixmap_item.pixmap()
            actual_w = current_pixmap.width()
            actual_h = current_pixmap.height()
            
            # Si nous sommes sur l'image 1
            if self.ab_showing_image1:
                # Image 1 - position de base, avec ajustement pour la rotation si nécessaire
                if abs(current_rotation) > 0.01:
                    # Calculer l'ajustement pour maintenir le centre au même endroit
                    # après rotation (différence entre taille originale et taille après rotation)
                    offset_x = (actual_w - w1) / 2
                    offset_y = (actual_h - h1) / 2
                    standard_pixmap_item.setPos(x1 - offset_x, y1 - offset_y)
                else:
                    standard_pixmap_item.setPos(x1, y1)
            else:
                # Image 2 - position avec l'offset relatif et ajustement pour la rotation
                if abs(current_rotation) > 0.01:
                    # Appliquer l'offset entre les centres des images
                    offset_x = (actual_w - w2) / 2
                    offset_y = (actual_h - h2) / 2
                    standard_pixmap_item.setPos(
                        x1 + self._slider_offset_x - offset_x,
                        y1 + self._slider_offset_y - offset_y
                    )
                else:
                    standard_pixmap_item.setPos(x1 + self._slider_offset_x, y1 + self._slider_offset_y)
        else:
            self.ab_timer.stop()
            print("Warning: A/B switch stopped due to invalid pixmap.")

    # -----------------------------------------------------------
    # Chargement d'images
    # -----------------------------------------------------------
    def load_image(self, image_num):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, f"Sélectionner Image {image_num}", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;Tous les fichiers (*)"
        )
        if not filepath:
            return
        try:
            img = Image.open(filepath)
            # Vérifier si on doit limiter la résolution
            if LIMIT_IMAGE_RESOLUTION and max(img.width, img.height) > MAX_IMAGE_DIM_LOAD:
                img.thumbnail((MAX_IMAGE_DIM_LOAD, MAX_IMAGE_DIM_LOAD), Image.Resampling.LANCZOS)
                print(f"Image {image_num} resized (limitation activée)")
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

            # Ajouter aux fichiers récents
            if self.has_recent_files:
                print(f"Ajout du fichier {filepath} aux fichiers récents (image {image_num})")
                success = self.recent_files_manager.add_recent_file(filepath, is_image1=(image_num == 1))

                # Si les deux images sont chargées, ajouter la paire
                if self.image_path1 and self.image_path2:
                    print(f"Ajout de la paire {self.image_path1} & {self.image_path2} aux paires récentes")
                    self.recent_files_manager.add_recent_pair(self.image_path1, self.image_path2)

                # Mettre à jour le menu
                self.recent_files_menu.update_menus()
                # Configurer les gestionnaires d'événements pour les fichiers récents
                self.setup_recent_files_handlers()

                if success:
                    print("Fichier récent ajouté avec succès")
                else:
                    print("Erreur lors de l'ajout du fichier récent")

            self.update_display()

            if self.current_mode == "side_by_side":
                if image_num == 1:
                    self.view1.reset_view()
                else:
                    self.view2.reset_view()
            else:
                self.view_combined.reset_view()

            # Mettre à jour la barre d'état
            self.statusBar.showMessage(f"Image {image_num} chargée : {os.path.basename(filepath)}", 3000)

            # Mettre à jour l'affichage du zoom
            self.update_zoom_status()

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Erreur de chargement", f"Impossible de charger l'image :\n{e}")
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
                # Effacer l'image standard qui pourrait rester du mode A/B switch
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                standard_pixmap_item.setPixmap(QtGui.QPixmap())

                # Vérifier si nous sommes en mode recalage ou normal
                if not self.link_views_enabled and self._slider_recalage_actif:
                    # Mode recalage - semi-transparent avec items complets
                    self.item1.set_use_mask(False)
                    self.item2.set_use_mask(False)
                    self.item1.setOpacity(0.5)
                    self.item2.setOpacity(0.5)
                    self.interactive_slider.setVisible(False)
                    self.enable_drag(self.item1)
                    self.enable_drag(self.item2)
                else:
                    # Mode normal avec curseur
                    self.item1.set_use_mask(True)
                    self.item2.set_use_mask(True)
                    self.item1.setOpacity(1.0)
                    self.item2.setOpacity(1.0)
                    self.disable_drag_for_slider(self.item1)
                    self.disable_drag_for_slider(self.item2)
                    self.interactive_slider.setVisible(True)
                    self.interactive_slider.set_scene_rect(QtCore.QRectF(0, 0, scene_w, scene_h))
                    ratio = self.interactive_slider.get_position_ratio()
                    self.on_slider_ratio_update(ratio)
                
                # Dans tous les cas, on rend les items visibles
                self.item1.setVisible(True)
                self.item2.setVisible(True)
                
            elif self.current_mode == "ab_switch":
                # Mode A/B Switch - utiliser l'élément pixmap standard
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                
                if not self.link_views_enabled:
                    # Mode recalage pour A/B switch
                    standard_pixmap_item.setPixmap(QtGui.QPixmap())
                    self.item1.setPixmap(self.display_pixmap1)
                    self.item2.setPixmap(self.display_pixmap2)
                    self.item1.setVisible(True)
                    self.item2.setVisible(True)
                    self.item1.setOpacity(0.5)
                    self.item2.setOpacity(0.5)
                else:
                    # Mode normal A/B switch
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
        """Réinitialise toutes les vues à leur état par défaut et les images à leur position de départ."""
        # Réinitialiser les rotations
        self.reset_all_rotations()

        # Réinitialiser les offsets
        self._offset_x = 0
        self._offset_y = 0
        self._slider_offset_x = 0.0
        self._slider_offset_y = 0.0

        # Si on est en mode slider ou ab_switch, repositionner les items
        if self.current_mode in ["slider", "ab_switch"]:
            if self.item1 and self.item2:
                self.item1.setPos(0, 0)
                self.item2.setPos(0, 0)

        if self.current_mode == "side_by_side":
            self.view1.reset_view()
            self.view2.reset_view()
        else:
            self.view_combined.reset_view()

        if self.interactive_slider:
            self.interactive_slider.set_position_ratio(0.5)
            if self.current_mode == "slider":
                self.on_slider_ratio_update(0.5)

        # Mettre à jour l'affichage du zoom
        self.update_zoom_status()

        # Afficher un message dans la barre d'état
        self.statusBar.showMessage("Vues et positions réinitialisées", 2000)

    def move_pixmap_item(self, item_id: int, dx: float, dy: float):
        if self.current_mode not in ("slider", "ab_switch"):
            return

        needs_slider_update = (self.current_mode == "slider")

        if not self.link_views_enabled:
            # En mode recalage (lier les vues désactivé)
            if self.current_mode == "slider" and not self._slider_recalage_actif:
                # Mode slider normal (sans recalage) - bloquer le déplacement horizontal
                dx = 0  # Ignorer le déplacement horizontal
            # En mode recalage (curseur ou AB), permettre le déplacement libre

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

    def setup_recent_files_handlers(self):
        """Configure les gestionnaires d'événements pour les fichiers récents."""
        if not self.has_recent_files or not hasattr(self, 'recent_files_menu'):
            return

        # Réassigner directement les gestionnaires d'événements aux actions du menu
        # Désactiver temporairement les signaux pour éviter les boucles d'appels
        self.blockSignals(True)
        try:
            # Configurer les actions pour les images individuelles
            for menu, is_image1 in [(self.recent_files_menu.recent_image1_menu, True), 
                                  (self.recent_files_menu.recent_image2_menu, False)]:
                for action in menu.actions():
                    if action.isEnabled() and action.data():  # Ignorer les actions désactivées ou sans données
                        # Déconnecter tous les signaux existants
                        try:
                            action.triggered.disconnect()
                        except TypeError:
                            pass  # L'action pourrait ne pas avoir de connexions
                        
                        # Vérifier si les données de l'action sont valides et contiennent un chemin
                        data = action.data()
                        if isinstance(data, dict) and "path" in data:
                            path = data["path"]
                            # Vérifier si le chemin existe
                            if os.path.exists(path):
                                # Créer une fonction de rappel spécifique pour cette action
                                def create_callback(file_path, is_img1):
                                    return lambda: self.load_recent_file(file_path, is_img1)
                                
                                # Connecter l'action avec la fonction créée
                                callback = create_callback(path, is_image1)
                                action.triggered.connect(callback)
                                print(f"Action connectée pour le fichier: {path} (is_image1={is_image1})")
                            else:
                                print(f"Le fichier {path} n'existe pas, l'action ne sera pas connectée")
            
            # Configurer les actions pour les paires d'images
            for action in self.recent_files_menu.recent_pairs_menu.actions():
                if action.isEnabled() and action.data():
                    # Déconnecter tous les signaux existants
                    try:
                        action.triggered.disconnect()
                    except TypeError:
                        pass
                    
                    # Vérifier si les données de l'action sont valides
                    data = action.data()
                    if isinstance(data, dict) and "image1" in data and "image2" in data:
                        img1_path = data["image1"]
                        img2_path = data["image2"]
                        
                        # Vérifier si les deux fichiers existent
                        if os.path.exists(img1_path) and os.path.exists(img2_path):
                            # Créer une fonction de rappel spécifique pour cette paire
                            def create_pair_callback(path1, path2):
                                return lambda: self.load_recent_pair(path1, path2)
                            
                            # Connecter l'action avec la fonction créée
                            callback = create_pair_callback(img1_path, img2_path)
                            action.triggered.connect(callback)
                            print(f"Action connectée pour la paire: {img1_path} & {img2_path}")
                        else:
                            print(f"Un ou les deux fichiers n'existent pas: {img1_path} & {img2_path}")
            
            print("Gestionnaires d'événements pour les fichiers récents configurés avec succès")
        finally:
            # Réactiver les signaux
            self.blockSignals(False)

    def on_rotation_changed(self, item_id: int, angle: float):
        """
        Applique une rotation à l'image spécifiée.
        
        Args:
            item_id: L'ID de l'item (1 ou 2)
            angle: L'angle de rotation en degrés
        """
        if item_id == 1:
            self.item1.set_rotation(angle)
        else:
            self.item2.set_rotation(angle)
            
        # Afficher un message dans la barre d'état
        self.statusBar.showMessage(f"Image {item_id} : rotation de {angle:.1f}°", 2000)
        
    def on_quick_rotation_changed(self, angle: int):
        """
        Gère le changement de rotation via le slider rapide.
        
        Args:
            angle: L'angle de rotation en degrés (entier)
        """
        # Obtenir l'ID de l'image active
        active_image_id = self.combo_active_image.currentData()
        
        # Convertir l'angle entier du slider en valeur flottante plus précise
        angle_float = float(angle)
        
        # Appliquer la rotation à l'image active
        self.on_rotation_changed(active_image_id, angle_float)
        
    def reset_rotation(self, item_id: int):
        """
        Réinitialise la rotation de l'image spécifiée à 0 degré.
        
        Args:
            item_id: L'ID de l'item (1 ou 2)
        """
        self.on_rotation_changed(item_id, 0.0)
        
    def reset_all_rotations(self):
        """Réinitialise la rotation des deux images à 0 degré."""
        self.reset_rotation(1)
        self.reset_rotation(2)
        self.slider_quick_rotation.setValue(0)
        
    def copy_rotation(self, source_id: int, target_id: int):
        """
        Copie l'angle de rotation d'une image à l'autre.
        
        Args:
            source_id: L'ID de l'image source (1 ou 2)
            target_id: L'ID de l'image cible (1 ou 2)
        """
        # Obtenir l'angle de rotation de la source
        if source_id == 1:
            angle = self.item1.get_rotation()
        else:
            angle = self.item2.get_rotation()
            
        # Appliquer l'angle à la cible
        self.on_rotation_changed(target_id, angle)
        
        # Afficher un message dans la barre d'état
        self.statusBar.showMessage(f"Angle de rotation copié de l'image {source_id} vers l'image {target_id}", 2000)

    def on_limit_resolution_toggled(self, checked):
        """Gère l'activation/désactivation de la limitation de résolution."""
        global LIMIT_IMAGE_RESOLUTION
        LIMIT_IMAGE_RESOLUTION = checked
        print(f"Limitation de résolution -> {checked}")

        # Afficher un message dans la barre d'état
        if checked:
            self.statusBar.showMessage("Limitation de résolution activée : les images seront redimensionnées si nécessaire", 2000)
        else:
            self.statusBar.showMessage("Limitation de résolution désactivée : les images seront chargées à pleine résolution", 2000)

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

