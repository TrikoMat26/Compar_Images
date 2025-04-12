from typing import Optional, Callable, Union
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal

# -------------------------------------------------------------
# 1) DraggablePixmapItem
# -------------------------------------------------------------
class DraggablePixmapItem(QtWidgets.QGraphicsPixmapItem):
    """
    QGraphicsPixmapItem déplaçable : gère le drag (souris) et
    appelle move_pixmap_item du contrôleur.
    """
    def __init__(self, controller=None, item_id: int = 1, parent=None):
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

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._dragging = True
            self._last_mouse_pos = event.scenePos()
            event.accept()
        super().mousePressEvent(event)
        
    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
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

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
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
    def __init__(self, controller=None, item_id: int = 1, is_left: bool = True, parent=None):
        super().__init__(controller=controller, item_id=item_id, parent=parent)
        self._use_mask = False
        self._ratio = 0.5
        self._is_left = is_left
        self._lock_axis = None  # None, 'horizontal', 'vertical'

    def set_use_mask(self, use_mask: bool) -> None:
        self._use_mask = use_mask
        self.update()

    def set_slider_ratio(self, ratio: float) -> None:
        self._ratio = max(0.0, min(1.0, ratio))
        self.update()
        
    @property
    def slider_ratio(self) -> float:
        return self._ratio
        
    @slider_ratio.setter
    def slider_ratio(self, value: float) -> None:
        self.set_slider_ratio(value)
        
    def set_lock_axis(self, axis: Optional[str]) -> None:
        """Verrouille le déplacement sur un axe spécifique."""
        if axis in (None, 'horizontal', 'vertical'):
            self._lock_axis = axis
            
    @property
    def lock_axis(self) -> Optional[str]:
        return self._lock_axis
        
    @lock_axis.setter
    def lock_axis(self, value: Optional[str]) -> None:
        self.set_lock_axis(value)

    def paint(self, painter: QtGui.QPainter, option, widget=None) -> None:
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
# 3) InteractiveSliderItem (barre de séparation)
# -------------------------------------------------------------
class InteractiveSliderItem(QtWidgets.QGraphicsLineItem):
    class Signals(QtCore.QObject):
        positionChanged = Signal(float)

    def __init__(self, scene_rect: QtCore.QRectF, color: str = "red", width: int = 2, parent=None):
        super().__init__(parent)
        self.scene_rect = scene_rect
        self._position = 0.5
        self.signals = self.Signals()
        self.positionChanged = self.signals.positionChanged
        self._is_dragging = False

        # Personnalisation du style
        self.set_color(color)
        self.set_width(width)
        
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setCursor(QtCore.Qt.CursorShape.SizeHorCursor)
        self.setPos(QtCore.QPointF(0, 0))
        self.update_line_geometry()
        self.setAcceptedMouseButtons(QtCore.Qt.MouseButton.LeftButton)
        
    def set_color(self, color: str) -> None:
        """Définit la couleur de la ligne."""
        pen = QtGui.QPen(QtGui.QColor(color), self.pen().width(), QtCore.Qt.PenStyle.SolidLine)
        self.setPen(pen)
        
    def set_width(self, width: int) -> None:
        """Définit l'épaisseur de la ligne."""
        pen = self.pen()
        pen.setWidth(width)
        self.setPen(pen)

    def mousePressEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._is_dragging = True
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
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

    def mouseReleaseEvent(self, event: QtWidgets.QGraphicsSceneMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._is_dragging:
            self._is_dragging = False
            event.accept()
        super().mouseReleaseEvent(event)

    def update_line_geometry(self) -> None:
        x = self.scene_rect.left() + self._position*self.scene_rect.width()
        self.setLine(x, self.scene_rect.top(), x, self.scene_rect.bottom())

    def set_scene_rect(self, rect: QtCore.QRectF) -> None:
        self.scene_rect = rect
        self.update_line_geometry()

    def set_position_ratio(self, ratio: float) -> None:
        ratio = max(0.0, min(1.0, ratio))
        if not np.isclose(ratio, self._position):
            self._position = ratio
            self.update_line_geometry()
            
    @property
    def position_ratio(self) -> float:
        return self._position
        
    @position_ratio.setter
    def position_ratio(self, value: float) -> None:
        self.set_position_ratio(value)

    def get_position_ratio(self) -> float:
        return self._position

    def itemChange(self, change, value):
        if change == QtWidgets.QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            return QtCore.QPointF(0,0)
        return super().itemChange(change, value)
