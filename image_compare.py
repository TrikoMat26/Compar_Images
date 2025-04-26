import resources_rc
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
        self._scale_factor = 1.0  # Facteur d'échelle (1.0 = taille originale)

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

    def set_scale_factor(self, scale: float):
        """Définit le facteur d'échelle."""
        self._scale_factor = max(0.1, min(5.0, scale))  # Limiter entre 10% and 500%
        self.update()

    def get_scale_factor(self) -> float:
        """Retourne le facteur d'échelle actuel."""
        return self._scale_factor

    def paint(self, painter: QtGui.QPainter, option, widget=None):
        pm = self.pixmap()
        if (pm.isNull()):
            return
        w = pm.width()
        h = pm.height()
        if w <= 0 or h <= 0:
            return

        # Sauvegarder l'état du peintre
        painter.save()

        if not self._use_mask:
            # Pas de masquage => on dessine tout

            # Appliquer la mise à l'échelle
            if self._scale_factor != 1.0:
                painter.scale(self._scale_factor, self._scale_factor)

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

            # Appliquer la mise à l'échelle
            if self._scale_factor != 1.0:
                painter.scale(self._scale_factor, self._scale_factor)

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
        # Vérifie si Alt est enfoncé pour le mode échelle
        modifiers = QtWidgets.QApplication.keyboardModifiers()
        if modifiers & QtCore.Qt.KeyboardModifier.AltModifier:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._scale_mode = True
                self._last_scale_pos = event.screenPos().y()
                event.accept()
                return
        # Vérifie si Ctrl est enfoncé pour le mode rotation
        elif modifiers & QtCore.Qt.KeyboardModifier.ControlModifier:
            if event.button() == QtCore.Qt.MouseButton.LeftButton:
                self._rotation_mode = True
                # Mémoriser le centre de l'item pour la rotation
                rect = self.boundingRect()
                self._rotation_center = rect.center()
                # Mémoriser la position initiale pour calculer l'angle
                self._last_rotation_pos = event.scenePos()
                event.accept()
                return
        # Si pas en mode spécial, comportement normal
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        # Gérer le mode échelle
        if hasattr(self, '_scale_mode') and self._scale_mode and self.controller:
            # Calculer le facteur d'échelle basé sur le mouvement vertical
            current_y = event.screenPos().y()
            delta_y = self._last_scale_pos - current_y

            # Une sensibilité adaptée pour le changement d'échelle
            sensitivity = 0.005
            scale_change = 1.0 + (delta_y * sensitivity)

            # Calculer le nouveau facteur d'échelle
            new_scale = self._scale_factor * scale_change

            # Limiter l'échelle entre 0.1 (10%) et 5.0 (500%)
            new_scale = max(0.1, min(5.0, new_scale))

            # Informer le contrôleur du changement d'échelle
            self.controller.on_scale_changed(self.item_id, new_scale)

            # Mettre à jour la position pour le prochain calcul
            self._last_scale_pos = current_y

            event.accept()
            return
        elif self._rotation_mode and self.controller:
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

        # Si pas en mode spécial, comportement normal
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent):
        if hasattr(self, '_scale_mode') and self._scale_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._scale_mode = False
            event.accept()
            return
        elif self._rotation_mode and event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._rotation_mode = False
            event.accept()
            return

        # Si pas en mode spécial, comportement normal
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

    doubleClicked = Signal()  # ← nouveau

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self.doubleClicked.emit()              # émet le signal
        super().mouseDoubleClickEvent(event)


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
        # Couleur de fond dépendante du thème courant
        self.setBackgroundBrush(self.palette().window())
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
        self.is_dark_theme = False  # démarrage en clair
        self.apply_light_style()

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

        # Thème par défaut : clair
        self.is_dark_theme = False
        self.apply_light_style()

        self.setup_ui()
        self.update_display()



    def apply_light_style(self):
        """Palette et feuille de style thème **clair**."""
        # Palette lumineuse inspirée de Fluent / Windows 11
        accent = QtGui.QColor("#0078D7")
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window,          QtGui.QColor("#f9f9f9"))
        palette.setColor(QtGui.QPalette.WindowText,      QtGui.QColor("#000000"))
        palette.setColor(QtGui.QPalette.Base,            QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.AlternateBase,   QtGui.QColor("#f1f1f1"))
        palette.setColor(QtGui.QPalette.ToolTipBase,     QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.ToolTipText,     QtGui.QColor("#000000"))
        palette.setColor(QtGui.QPalette.Text,            QtGui.QColor("#000000"))
        palette.setColor(QtGui.QPalette.Button,          QtGui.QColor("#e1e1e1"))
        palette.setColor(QtGui.QPalette.ButtonText,      QtGui.QColor("#000000"))
        palette.setColor(QtGui.QPalette.BrightText,      QtGui.QColor("#ff0000"))
        palette.setColor(QtGui.QPalette.Link,            accent)
        palette.setColor(QtGui.QPalette.Highlight,       accent)
        palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#ffffff"))
        self.setPalette(palette)

        # -------------------  StyleSheet  -------------------
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background:#f9f9f9; color:#000; }
            QPushButton {
                background:#0078D7; color:#fff; border:none; padding:6px 16px;
                border-radius:4px; font-weight:600;
            }
            QPushButton:hover   { background:#0A84FF; }
            QPushButton:pressed { background:#005CB1; }
            QComboBox, QLineEdit, QTextEdit, QSpinBox {
                border:1px solid #C6C6C6; border-radius:4px; padding:4px; background:#fff;
            }
            QGroupBox {
                border:1px solid #C6C6C6; border-radius:6px; margin-top:12px; padding-top:20px;
            }
            QGroupBox::title { subcontrol-origin:margin; left:8px; top:4px; color:#0078D7; font-weight:600; }
            QStatusBar { background:#e1e1e1; color:#000; }
            """
        )
    def toggle_theme(self):
        """Bascule entre thème clair et sombre."""
        self.is_dark_theme = not getattr(self, "is_dark_theme", False)
        if self.is_dark_theme:
            self.apply_dark_style()
        else:
            self.apply_light_style()


    def setup_ui(self):


        # Configuration de la barre d'outils
        self.setup_toolbar()

        # Widget central avec layout horizontal pour le bandeau latéral et la zone d'affichage
        main_widget = QtWidgets.QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QtWidgets.QHBoxLayout(main_widget)  # Horizontal au lieu de vertical
        main_layout.setContentsMargins(0, 0, 0, 0)  # Minimiser les marges
        main_layout.setSpacing(0)  # Minimiser l'espace entre les éléments

        # --- B‑1 DOCK / SPLITTER -------------------------------- #
        self.sidebar = QtWidgets.QDockWidget("Panneau", self)   #  <<< Ici >>>
        self.sidebar.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea)
        self.sidebar.setFeatures(QtWidgets.QDockWidget.NoDockWidgetFeatures)
        self.addDockWidget(QtCore.Qt.LeftDockWidgetArea, self.sidebar)

        side_container = QtWidgets.QWidget()
        self.sidebar.setWidget(side_container)
        sidebar_layout = QtWidgets.QVBoxLayout(side_container)
        sidebar_layout.setContentsMargins(5, 5, 5, 5)
        sidebar_layout.setSpacing(5)
        # (tout le contenu existant du sidebar est simplement déplacé dans 
        #  *sidebar_layout* – pas besoin de réécrire, copie‑colle)

        # Boutons de chargement d'images
        load_group = QtWidgets.QGroupBox("Images")
        load_layout = QtWidgets.QVBoxLayout(load_group)
        load_layout.setContentsMargins(5, 10, 5, 5)
        load_layout.setSpacing(5)

        btn_load1 = QtWidgets.QPushButton("Charger Image 1")
        btn_load1.clicked.connect(lambda: self.load_image(1))
        btn_load1.setToolTip("Charger la première image à comparer (Image A)")
        self.lbl_img1 = QtWidgets.QLabel("Aucune image 1")
        self.lbl_img1.setWordWrap(True)
        self.lbl_img1.setStyleSheet("font-size: 9pt;")  # Texte plus petit

        btn_load2 = QtWidgets.QPushButton("Charger Image 2")
        btn_load2.clicked.connect(lambda: self.load_image(2))
        btn_load2.setToolTip("Charger la seconde image à comparer (Image B)")
        self.lbl_img2 = QtWidgets.QLabel("Aucune image 2")
        self.lbl_img2.setWordWrap(True)
        self.lbl_img2.setStyleSheet("font-size: 9pt;")  # Texte plus petit

        load_layout.addWidget(btn_load1)
        load_layout.addWidget(self.lbl_img1)
        load_layout.addWidget(btn_load2)
        load_layout.addWidget(self.lbl_img2)
        sidebar_layout.addWidget(load_group)

        # Modes de comparaison
        mode_group = QtWidgets.QGroupBox("Mode de comparaison")
        mode_layout = QtWidgets.QVBoxLayout(mode_group)
        mode_layout.setContentsMargins(5, 10, 5, 5)
        mode_layout.setSpacing(5)
        sidebar_layout.addWidget(mode_group)

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
        ab_switch_layout.setContentsMargins(0, 0, 0, 0)

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
        adjust_group = QtWidgets.QGroupBox("Ajustement")
        adjust_layout = QtWidgets.QVBoxLayout(adjust_group)
        adjust_layout.setContentsMargins(5, 10, 5, 5)
        adjust_layout.setSpacing(5)

        self.combo_size_adjust = QtWidgets.QComboBox()
        for key, label in self.size_adjust_options.items():
            self.combo_size_adjust.addItem(label, key)
        self.combo_size_adjust.setCurrentText(self.size_adjust_options[self.size_adjust_mode])
        self.combo_size_adjust.currentIndexChanged.connect(self.on_size_adjust_changed)
        self.combo_size_adjust.setToolTip("Définit comment les images de tailles différentes sont ajustées pour la comparaison")
        adjust_layout.addWidget(self.combo_size_adjust)

        sidebar_layout.addWidget(adjust_group)

        # Options de vue dans un accordion (collapsible section)
        view_group = QtWidgets.QGroupBox("Options")
        view_layout = QtWidgets.QVBoxLayout(view_group)
        view_layout.setContentsMargins(5, 10, 5, 5)
        view_layout.setSpacing(5)

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

        btn_reset_view = QtWidgets.QPushButton("Réinitialiser la vue")
        btn_reset_view.clicked.connect(self.reset_all_views)
        btn_reset_view.setToolTip("Réinitialise le zoom et la position des images")
        view_layout.addWidget(btn_reset_view)

        sidebar_layout.addWidget(view_group)

        # Widget de recalage (contrôles de rotation et échelle) - version compacte
        self.recalage_controls_widget = QtWidgets.QGroupBox("Recalage")
        self.recalage_controls_widget.setVisible(False)
        recalage_controls_layout = QtWidgets.QVBoxLayout(self.recalage_controls_widget)
        recalage_controls_layout.setContentsMargins(5, 10, 5, 5)
        recalage_controls_layout.setSpacing(5)

        # Information des raccourcis clavier pour le mode recalage
        shortcuts_info = QtWidgets.QLabel(
            "• Clic : Position\n"
            "• Ctrl+Clic : Rotation\n"
            "• Alt+Clic : Échelle"
        )
        shortcuts_info.setStyleSheet("margin-left: 5px; font-size: 9pt;")
        recalage_controls_layout.addWidget(shortcuts_info)

        # Affichage compact des valeurs
        values_layout = QtWidgets.QGridLayout()
        values_layout.addWidget(QtWidgets.QLabel("Image 1:"), 0, 0)
        values_layout.addWidget(QtWidgets.QLabel("Image 2:"), 1, 0)

        self.lbl_image1_rotation = QtWidgets.QLabel("R: 0°")
        self.lbl_image1_scale = QtWidgets.QLabel("S: 100%")
        self.lbl_image2_rotation = QtWidgets.QLabel("R: 0°")
        self.lbl_image2_scale = QtWidgets.QLabel("S: 100%")

        values_layout.addWidget(self.lbl_image1_rotation, 0, 1)
        values_layout.addWidget(self.lbl_image1_scale, 0, 2)
        values_layout.addWidget(self.lbl_image2_rotation, 1, 1)
        values_layout.addWidget(self.lbl_image2_scale, 1, 2)

        recalage_controls_layout.addLayout(values_layout)

        # Sélection de l'image active pour les rotations rapides
        active_image_layout = QtWidgets.QHBoxLayout()
        active_image_layout.addWidget(QtWidgets.QLabel("Image active:"))
        self.combo_active_image = QtWidgets.QComboBox()
        self.combo_active_image.addItem("Image 1", 1)
        self.combo_active_image.addItem("Image 2", 2)
        active_image_layout.addWidget(self.combo_active_image)
        recalage_controls_layout.addLayout(active_image_layout)

        # Boutons de rotation par cran de 90 degrés
        rotation_layout = QtWidgets.QGridLayout()

        # Rotation horaire et anti-horaire par 90°
        btn_rotate_ccw_90 = QtWidgets.QPushButton("↺ 90°")
        btn_rotate_ccw_90.setToolTip("Rotation anti-horaire de 90°")
        btn_rotate_ccw_90.clicked.connect(lambda: self.rotate_by_angle(-90))
        rotation_layout.addWidget(btn_rotate_ccw_90, 0, 0)

        btn_rotate_cw_90 = QtWidgets.QPushButton("↻ 90°")
        btn_rotate_cw_90.setToolTip("Rotation horaire de 90°")
        btn_rotate_cw_90.clicked.connect(lambda: self.rotate_by_angle(90))
        rotation_layout.addWidget(btn_rotate_cw_90, 0, 1)

        # Rotation 180° et Reset
        btn_rotate_180 = QtWidgets.QPushButton("↻ 180°")
        btn_rotate_180.setToolTip("Rotation de 180°")
        btn_rotate_180.clicked.connect(lambda: self.rotate_by_angle(180))
        rotation_layout.addWidget(btn_rotate_180, 1, 0)

        btn_reset_rotation = QtWidgets.QPushButton("R: 0°")
        btn_reset_rotation.setToolTip("Réinitialiser la rotation")
        btn_reset_rotation.clicked.connect(lambda: self.reset_rotation(self.combo_active_image.currentData()))
        rotation_layout.addWidget(btn_reset_rotation, 1, 1)

        recalage_controls_layout.addLayout(rotation_layout)

        # Bouton de réinitialisation compact
        btn_reset_all = QtWidgets.QPushButton("Réinitialiser")
        btn_reset_all.clicked.connect(self.reset_all_transformations)
        recalage_controls_layout.addWidget(btn_reset_all)

        sidebar_layout.addWidget(self.recalage_controls_widget)

        # Ajouter un espace extensible en bas du bandeau latéral
        sidebar_layout.addStretch(1)

        # Zone d'affichage principale (partie droite)
        display_widget = QtWidgets.QWidget()
        display_layout = QtWidgets.QVBoxLayout(display_widget)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(0)
        main_layout.addWidget(display_widget, 1)  # Prend tout l'espace disponible






        # Initialiser les viewers
        self.view1 = ImageViewer()
        self.view2 = ImageViewer()
        self.view_combined = ImageViewer()
        self.view_combined.doubleClicked.connect(self.check_link_views.toggle)


        # Connecter l'option de qualité
        self.check_high_quality.toggled.connect(self.on_high_quality_toggled)

        # Créer la pile de vues
        self.view_stack = QtWidgets.QStackedWidget()




        # Vue côte à côte
        side_by_side_widget = QtWidgets.QWidget()
        side_by_side_layout = QtWidgets.QHBoxLayout(side_by_side_widget)
        side_by_side_layout.setContentsMargins(0, 0, 0, 0)
        side_by_side_layout.setSpacing(1)
        side_by_side_layout.addWidget(self.view1)
        side_by_side_layout.addWidget(self.view2)
        self.view_stack.addWidget(side_by_side_widget)  # index 0

        # Vue combinée
        self.view_stack.addWidget(self.view_combined)    # index 1

        # --- splitter horizontal pour un futur panneau à droite si besoin
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)   #  <<< Ici >>>
        display_layout.addWidget(self.splitter)
        # Vue stack migre dans le splitter
        self.splitter.addWidget(self.view_stack)
        # pas d’autre widget si tu ne veux pas de zoom slider
        self.splitter.setStretchFactor(0, 1)      # occupe toute la largeur


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

        # Configuration du menu principal
        self.setup_menu()

    def setup_toolbar(self):
        """Configure la barre d'outils principale."""
        self.toolbar = QtWidgets.QToolBar("Main Toolbar")
        self.toolbar.setIconSize(QtCore.QSize(24, 24))
        self.toolbar.setMovable(False)
        self.addToolBar(self.toolbar)

        # Actions de la barre d'outils
        self.action_open_image1 = QtGui.QAction("Ouvrir Image 1", self)
        self.action_open_image1.setIcon(QtGui.QIcon(":/icons/open.svg"))
        self.action_open_image1.triggered.connect(lambda: self.load_image(1))
        self.toolbar.addAction(self.action_open_image1)

        self.action_open_image2 = QtGui.QAction("Ouvrir Image 2", self)
        self.action_open_image2.setIcon(QtGui.QIcon(":/icons/open.svg"))
        self.action_open_image2.triggered.connect(lambda: self.load_image(2))
        self.toolbar.addAction(self.action_open_image2)

        self.toolbar.addSeparator()

        self.action_reset_view = QtGui.QAction("Réinitialiser la vue", self)
        self.action_reset_view.setIcon(QtGui.QIcon(":/icons/refresh.svg"))
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
            recent_files_action.setIcon(QtGui.QIcon(":/icons/open.svg"))

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
        view_menu.addSeparator()                       # ← déjà existant ? sinon ajoute-le
        toggle_theme_action = QtGui.QAction("Basculer &Thème (Clair/Sombre)", self)
        toggle_theme_action.setShortcut("Ctrl+T")
        toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme_action)

        toggle_dock_act = QtGui.QAction("Afficher/masquer le &Panneau", self)
        toggle_dock_act.setShortcut("Ctrl+P")
        toggle_dock_act.setCheckable(True)
        toggle_dock_act.setChecked(True)
        toggle_dock_act.toggled.connect(self.sidebar.setVisible)
        view_menu.addAction(toggle_dock_act)

        # Maintenir la case à jour quand l’utilisateur ferme le dock
        self.sidebar.visibilityChanged.connect(toggle_dock_act.setChecked)
        

        slider_action = QtGui.QAction("Mode &curseur", self)
        slider_action.setShortcut("Ctrl+L")
        slider_action.triggered.connect(lambda: self.set_mode_from_menu("slider"))
        view_menu.addAction(slider_action)

        ab_switch_action = QtGui.QAction("Mode &A/B Switch", self)
        ab_switch_action.setShortcut("Ctrl+A")
        ab_switch_action.triggered.connect(lambda: self.set_mode_from_menu("ab_switch"))
        view_menu.addAction(ab_switch_action)
        view_menu.addSeparator()
        toggle_theme_action = QtGui.QAction("Basculer &Thème (Clair/Sombre)", self)
        toggle_theme_action.setShortcut("Ctrl+T")
        toggle_theme_action.triggered.connect(self.toggle_theme)
        view_menu.addAction(toggle_theme_action)

        # Menu Aide
        help_menu = menubar.addMenu("&Aide")

        about_action = QtGui.QAction("&À propos", self)
        about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)

        keyboard_shortcuts_action = QtGui.QAction("&Raccourcis clavier", self)
        keyboard_shortcuts_action.triggered.connect(self.show_keyboard_shortcuts)
        help_menu.addAction(keyboard_shortcuts_action)

    def apply_dark_style(self):
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
        self.setStyleSheet(open(os.path.join("style", "dark.qss"), "r", encoding="utf-8").read())

    def apply_light_style(self):
        """Palette *Fluent Light* + feuille de style claire."""
        accent = QtGui.QColor("#0A84FF")  # bleu Fluent
        palette = QtGui.QPalette()
        palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#f8f8f8"))
        palette.setColor(QtGui.QPalette.Base,   QtGui.QColor("#ffffff"))
        palette.setColor(QtGui.QPalette.Text,   QtGui.QColor("#000000"))
        # … (autres rôles comme dans l’exemple ci‑dessous)
        self.setPalette(palette)
        self.setStyleSheet(open(os.path.join("style", "light.qss"), "r", encoding="utf-8").read())

    def toggle_theme(self):
        self.is_dark_theme = not self.is_dark_theme
        if self.is_dark_theme:
            self.apply_dark_style()
        else:
            self.apply_light_style()

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
        item.setFlags(new_flags)

    # -----------------------------------------------------------
    #  Centre visuel réel (après scale et rotation centrée)
    # -----------------------------------------------------------
    def visual_center(self, item: QtWidgets.QGraphicsPixmapItem) -> QtCore.QPointF:
        """Retourne le centre de l’image telle qu’elle est peinte."""
        s   = item.get_scale_factor()
        w   = item.pixmap().width()  * s
        h   = item.pixmap().height() * s
        pos = item.pos()            # coin haut-gauche en scène
        return QtCore.QPointF(pos.x() + w/2, pos.y() + h/2)        

    def disable_drag(self, item: QtWidgets.QGraphicsPixmapItem):
        flags = item.flags()
        item.setFlags(flags & ~QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)


    # -----------------------------------------------------------
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

    def on_show_grid_toggled(self, _):
        """Active ou désactive l'affichage de la grille.

        Note: Cette fonctionnalité est désactivée dans cette version.
        """
        # Fonctionnalité désactivée - paramètre renommé en _ pour indiquer qu'il n'est pas utilisé
        pass

    def on_link_views_toggled(self, checked: bool):
        """
        Calcule désormais les offsets à partir du **centre visuel réel**
        de chaque item : centre = mapToScene(boundingRect().center()).
        Ainsi, l’offset reste exact après n’importe quelle rotation ou
        mise à l’échelle.  Le même centre est aussi utilisé pour
        repositionner la barre rouge (slider) et pour l’alternance A/B.
        """
        self.link_views_enabled = checked
        self.statusBar.showMessage(
            "Vues liées" if checked else "Vues indépendantes", 1500)

        # ------------------------------------------------------------------
        # outils : centre visuel et scène-rect tenant compte du scale
        # ------------------------------------------------------------------
        def center(item: QtWidgets.QGraphicsPixmapItem) -> QtCore.QPointF:
            return item.mapToScene(item.boundingRect().center())

        def scene_rect(item: QtWidgets.QGraphicsPixmapItem) -> QtCore.QRectF:
            return item.sceneBoundingRect()

        # ------------------------------------------------------------------
        # 1) MODE SLIDER
        # ------------------------------------------------------------------
        if self.current_mode == "slider":
            if checked:                           # ----- on RE-lie
                self._slider_recalage_actif = False

                c1, c2 = self.visual_center(self.item1), self.visual_center(self.item2)
                self._slider_offset_x = c2.x() - c1.x()
                self._slider_offset_y = c2.y() - c1.y()

                # retour au slider « standard »
                for it in (self.item1, self.item2):
                    it.set_use_mask(True)
                    it.setOpacity(1.0)
                self.disable_drag(self.item1)
                self.disable_drag(self.item2)

                # *** NOUVEAU *** : la barre rouge utilise le rect « scène »
                self.interactive_slider.set_scene_rect(scene_rect(self.item1))
                self.interactive_slider.setVisible(True)
                self.on_slider_ratio_update(self.interactive_slider.get_position_ratio())

                self.recalage_controls_widget.setVisible(False)

            else:                                 # ----- on DÉ-lie (recalage)
                self._slider_recalage_actif = True

                for it in (self.item1, self.item2):
                    it.set_use_mask(False)
                    it.setOpacity(0.5)
                self.interactive_slider.setVisible(False)

                self.disable_drag(self.item1)      # image 1 fixe
                self.enable_drag(self.item2)       # image 2 mobile
                self.recalage_controls_widget.setVisible(True)
                self.combo_active_image.setCurrentIndex(
                    self.combo_active_image.findData(2))

        # ------------------------------------------------------------------
        # 2) MODE A/B SWITCH
        # ------------------------------------------------------------------
        elif self.current_mode == "ab_switch":
            if checked:                           # ----- on RE-lie
                self._ab_recalage_actif = False

                c1, c2 = self.visual_center(self.item1), self.visual_center(self.item2)
                self._slider_offset_x = c2.x() - c1.x()
                self._slider_offset_y = c2.y() - c1.y()

                std = self.view_combined.get_pixmap_item()
                std.setPixmap(self.display_pixmap1)     # image 1, non transformée
                std.setScale(1.0)

                # place l’image 1 pour que son centre = c1
                std.setPos(c1 - QtCore.QPointF(
                    self.display_pixmap1.width()  / 2,
                    self.display_pixmap1.height() / 2))

                self.item1.setVisible(False)
                self.item2.setVisible(False)
                self.recalage_controls_widget.setVisible(False)

                self.ab_showing_image1 = True
                if not self.ab_timer.isActive():
                    self.ab_timer.start()

            else:                                 # ----- on DÉ-lie (recalage)
                self._ab_recalage_actif = True
                self.ab_timer.stop()

                self.view_combined.get_pixmap_item().setPixmap(QtGui.QPixmap())

                self.item1.setPixmap(self.display_pixmap1)
                self.item2.setPixmap(self.display_pixmap2)
                for it in (self.item1, self.item2):
                    it.setVisible(True)
                    it.setOpacity(0.5)

                self.disable_drag(self.item1)
                self.enable_drag(self.item2)
                self.recalage_controls_widget.setVisible(True)
                self.combo_active_image.setCurrentIndex(
                    self.combo_active_image.findData(2))

    def on_slider_ratio_update(self, ratio_scene: float):
        # 1) quitter si rien à afficher
        if (self.item1.pixmap().isNull() or self.item2.pixmap().isNull()):
            return

        scale1 = self.item1.get_scale_factor()
        scale2 = self.item2.get_scale_factor()
        w1 = self.item1.pixmap().width()
        w2 = self.item2.pixmap().width()

        # 2) quitter si l’une des largeurs (ou échelles) vaut zéro
        if scale1 == 0 or w1 == 0 or scale2 == 0 or w2 == 0:
            return

        # --- calcul inchangé ---
        cut_x = self.item1.pos().x() + ratio_scene * w1 * scale1
        local_ratio1 = (cut_x - self.item1.pos().x()) / (w1 * scale1)
        self.item1.set_slider_ratio(max(0.0, min(1.0, local_ratio1)))

        local_ratio2 = (cut_x - self.item2.pos().x()) / (w2 * scale2)
        self.item2.set_slider_ratio(max(0.0, min(1.0, local_ratio2)))

        if self.interactive_slider:
            self.interactive_slider.set_scene_rect(self.item1.sceneBoundingRect())
            self.interactive_slider.set_position_ratio(ratio_scene)


    def visual_center(self, item: QtWidgets.QGraphicsPixmapItem) -> QtCore.QPointF:
        """
        Retourne le centre de l’image telle qu’elle est peinte
        (rotation autour du centre + scale facteur).
        """
        s   = item.get_scale_factor()
        w   = item.pixmap().width()  * s
        h   = item.pixmap().height() * s
        pos = item.pos()             # coin haut-gauche dans la scène
        return QtCore.QPointF(pos.x() + w/2, pos.y() + h/2)

    def switch_ab_image(self):
        # 0. garde-fous ----------------------------------------------------
        if self.current_mode != "ab_switch":
            self.ab_timer.stop(); return
        if not (self.display_pixmap1 and self.display_pixmap2):
            self.ab_timer.stop(); return

        # 1. bascule le drapeau
        self.ab_showing_image1 = not self.ab_showing_image1

        # 2. mode recalage manuel : on laisse les deux items visibles
        if not self.link_views_enabled:
            return

        # 3. source image + transformation locale -------------------------
        src_pix = self.display_pixmap1 if self.ab_showing_image1 else self.display_pixmap2
        src_it  = self.item1           if self.ab_showing_image1 else self.item2
        if src_pix is None or src_pix.isNull():
            self.ab_timer.stop(); return

        rot   = src_it.get_rotation()
        scale = src_it.get_scale_factor()

        w, h = src_pix.width(), src_pix.height()
        tx = QtGui.QTransform()
        tx.translate(w/2, h/2)
        tx.rotate(rot)
        tx.scale(scale, scale)
        tx.translate(-w/2, -h/2)

        transformed = src_pix.transformed(tx, QtCore.Qt.SmoothTransformation)

        # --- centre du pixmap transformé (NOUVEAU) -----------------------
        center_tx = QtCore.QPointF(transformed.width()/2,
                                   transformed.height()/2)

        # --- centre visuel réel (scène) des deux images ------------------
        center1 = self.visual_center(self.item1)
        center2 = self.visual_center(self.item2)
        target_center = center1 if self.ab_showing_image1 else center2

        # --- position scène pour superposer les centres ------------------
        pos_scene = target_center - center_tx

        # 4. publication ---------------------------------------------------
        std_item = self.view_combined.get_pixmap_item()
        std_item.setPixmap(transformed)
        std_item.setPos(pos_scene)

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
                # Fallback conversion without using ImageQt
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
        if not self.pil_image1_orig or not self.pil_image2_orig:
            self.comparison_pixmap = None
            return
        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig
        if pil1 and pil2:
            try:
                im1 = pil1.convert("RGB")
                im2 = pil2.convert("RGB")
                alpha = 0.5  # Default opacity value
                result = Image.blend(im1, im2, alpha)
                # Convert result to pixmap
                self.comparison_pixmap = self.pil_to_qpixmap(result)
            except Exception as e:
                print(f"Erreur lors du blend d'images: {e}")
                self.comparison_pixmap = None

    def reset_all_views(self):
        if not self.display_pixmap1.isNull() and not self.display_pixmap2.isNull():
            self.on_slider_ratio_update(0.5)

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
        """Synchronise les vues en mode côte à côte.

        Args:
            source_view: La vue source qui a été modifiée
            force_sync: Force la synchronisation même si les vues sont déjà en cours de mise à jour
        """
        if (not force_sync and self._is_updating_views) or self.current_mode != "side_by_side":
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
                # En mode combiné, tester les deux items pour voir lequel contient la position
                item1_contains = self.item1.contains(self.item1.mapFromScene(scene_pos))
                item2_contains = self.item2.contains(self.item2.mapFromScene(scene_pos))
                if item1_contains and not item2_contains:
                    pix_item = self.item1
                elif item2_contains and not item1_contains:
                    pix_item = self.item2
            else:
                pix_item = self.view_combined.get_pixmap_item()

        coords_text = "Coords: (N/A)"
        rgb_text = "RGB: (N/A)"

        if pix_item and isinstance(pix_item, QtWidgets.QGraphicsPixmapItem):
            pm = pix_item.pixmap()
            if not pm.isNull():
                # Convertir la position de la scène en position dans l'item
                item_pos = pix_item.mapFromScene(scene_pos)
                if item_pos.x() >= 0 and item_pos.y() >= 0 and item_pos.x() < pm.width() and item_pos.y() < pm.height():
                    coords_text = f"Coords: ({int(item_pos.x())}, {int(item_pos.y())})"
                    # Récupérer la couleur du pixel
                    color = pm.toImage().pixelColor(int(item_pos.x()), int(item_pos.y()))
                    rgb_text = f"RGB: ({color.red()}, {color.green()}, {color.blue()})"

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
                    data = action.data()
                    if isinstance(data, dict) and "path" in data:
                        filepath = data["path"]
                        # Clear existing connections to avoid duplicates
                        try:
                            action.triggered.disconnect()
                        except TypeError:
                            pass  # No connections yet
                        # Connect to the appropriate method
                        action.triggered.connect(lambda _, path=filepath, is_img1=is_image1:
                                             self.load_recent_file(path, is_img1))

            # Configurer les actions pour les paires d'images
            for action in self.recent_files_menu.recent_pairs_menu.actions():
                if action.isEnabled() and action.data():
                    data = action.data()
                    if isinstance(data, dict) and "image1" in data and "image2" in data:
                        img1_path = data["image1"]
                        img2_path = data["image2"]
                        if os.path.exists(img1_path) and os.path.exists(img2_path):
                            # Clear existing connections to avoid duplicates
                            try:
                                action.triggered.disconnect()
                            except TypeError:
                                pass  # No connections yet
                            # Connect to the appropriate method
                            action.triggered.connect(lambda _, i1=img1_path, i2=img2_path:
                                                 self.load_recent_pair(i1, i2))

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

        # Mettre à jour les étiquettes d'information de rotation dans l'interface
        if hasattr(self, 'lbl_image1_rotation'):
            self.lbl_image1_rotation.setText("R: 0°")
        if hasattr(self, 'lbl_image2_rotation'):
            self.lbl_image2_rotation.setText("R: 0°")

        # Réinitialiser le slider de rotation rapide s'il existe
        if hasattr(self, 'slider_quick_rotation'):
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

    def on_scale_changed(self, item_id: int, scale: float):
        """
        Applique un facteur d'échelle à l'image spécifiée.

        Args:
            item_id: L'ID de l'item (1 ou 2)
            scale: Le facteur d'échelle (1.0 = taille originale)
        """
        if item_id == 1:
            self.item1.set_scale_factor(scale)
        else:
            self.item2.set_scale_factor(scale)

        # Mettre à jour l'affichage du facteur d'échelle dans l'interface
        if item_id == 1 and hasattr(self, 'lbl_image1_scale'):
            self.lbl_image1_scale.setText(f"S: {int(scale * 100)}%")
        elif item_id == 2 and hasattr(self, 'lbl_image2_scale'):
            self.lbl_image2_scale.setText(f"S: {int(scale * 100)}%")

        # Mettre à jour le slider si c'est l'image active et que le slider existe
        if hasattr(self, 'slider_scale') and hasattr(self, 'combo_active_image') and self.combo_active_image.currentData() == item_id:
            # Bloquer le signal temporairement pour éviter les boucles
            self.slider_scale.blockSignals(True)
            self.slider_scale.setValue(int(scale * 100))
            self.slider_scale.blockSignals(False)

        # Afficher un message dans la barre d'état
        self.statusBar.showMessage(f"Image {item_id} : échelle {int(scale * 100)}%", 2000)

    def on_quick_scale_changed(self, scale_value: int):
        """
        Gère le changement d'échelle via le slider rapide.

        Args:
            scale_value: La valeur d'échelle en pourcentage (10-500%)
        """
        # Obtenir l'ID de l'image active
        active_image_id = self.combo_active_image.currentData()

        # Convertir la valeur du slider en facteur d'échelle (pourcentage -> facteur)
        scale_factor = scale_value / 100.0

        # Mettre à jour l'étiquette affichant la valeur d'échelle si elle existe
        if hasattr(self, 'lbl_scale_value'):
            self.lbl_scale_value.setText(f"{scale_value}%")

        # Appliquer l'échelle à l'image active
        self.on_scale_changed(active_image_id, scale_factor)

    def reset_scale(self, item_id: int):
        """
        Réinitialise l'échelle de l'image spécifiée à 100%.

        Args:
            item_id: L'ID de l'item (1 ou 2)
        """
        self.on_scale_changed(item_id, 1.0)

        # Si c'est l'image active actuellement, réinitialiser aussi le slider s'il existe
        if hasattr(self, 'combo_active_image') and hasattr(self, 'slider_scale') and self.combo_active_image.currentData() == item_id:
            self.slider_scale.setValue(100)

    def copy_scale(self, source_id: int, target_id: int):
        """
        Copie le facteur d'échelle d'une image à l'autre.

        Args:
            source_id: L'ID de l'image source (1 ou 2)
            target_id: L'ID de l'image cible (1 ou 2)
        """
        # Obtenir le facteur d'échelle de la source
        scale_factor = self.item1.get_scale_factor() if source_id == 1 else self.item2.get_scale_factor()

        # Appliquer l'échelle à la cible
        self.on_scale_changed(target_id, scale_factor)

        # Afficher un message dans la barre d'état
        self.statusBar.showMessage(f"Facteur d'échelle copié de l'image {source_id} vers l'image {target_id}", 2000)

    def reset_all_transformations(self):
        """Réinitialise toutes les transformations (position, rotation, échelle) des deux images."""
        # Réinitialiser les positions
        self.item1.setPos(0, 0)
        self.item2.setPos(0, 0)
        self._offset_x = 0
        self._offset_y = 0
        self._slider_offset_x = 0.0
        self._slider_offset_y = 0.0

        # Réinitialiser les rotations
        self.reset_all_rotations()

        # Réinitialiser les échelles
        self.reset_scale(1)
        self.reset_scale(2)

        # Réinitialiser la position du slider si nécessaire
        if self.current_mode == "slider" and self.interactive_slider:
            self.interactive_slider.set_position_ratio(0.5)
            self.on_slider_ratio_update(0.5)

        # Réinitialiser la vue
        if self.current_mode == "side_by_side":
            self.view1.reset_view()
            self.view2.reset_view()
        else:
            self.view_combined.reset_view()

        # Afficher un message dans la barre d'état
        self.statusBar.showMessage("Toutes les transformations ont été réinitialisées", 2000)

    def rotate_by_angle(self, angle_increment):
        """
        Effectue une rotation de l'image active par un incrément d'angle fixe.

        Args:
            angle_increment: L'incrément d'angle en degrés (ex: 90, -90, 180)
        """
        # Obtenir l'ID de l'image active sélectionnée dans le combo box
        active_image_id = self.combo_active_image.currentData()

        # Récupérer l'angle actuel
        if active_image_id == 1:
            current_angle = self.item1.get_rotation()
        else:
            current_angle = self.item2.get_rotation()

        # Calculer le nouvel angle (arrondi pour éviter les erreurs de précision)
        new_angle = current_angle + angle_increment

        # Normaliser l'angle entre -180 and 180 degrés
        while new_angle > 180.0:
            new_angle -= 360.0
        while new_angle < -180.0:
            new_angle += 360.0

        # Appliquer la rotation
        self.on_rotation_changed(active_image_id, new_angle)

        # Mettre à jour l'affichage de l'angle de rotation dans l'interface
        if active_image_id == 1:
            self.lbl_image1_rotation.setText(f"R: {int(new_angle)}°")
        else:
            self.lbl_image2_rotation.setText(f"R: {int(new_angle)}°")

        # Afficher un message dans la barre d'état
        self.statusBar.showMessage(f"Image {active_image_id} : rotation de {int(new_angle)}°", 2000)

# -------------------------------------------------------------
# Point d'entrée
# -------------------------------------------------------------
if __name__ == "__main__":
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")                 #  <<< Ici >>>
    app.setFont(QtGui.QFont("Segoe UI", 10))
    window = ImageComparerApp()
    window.show()
    sys.exit(app.exec())

