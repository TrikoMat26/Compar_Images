from typing import Optional, Tuple, Union
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal

# -------------------------------------------------------------
# ImageViewer
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
        
        # Cache pour les transformations
        self._transform_cache = {}

    def set_pixmap(self, pixmap: QtGui.QPixmap) -> None:
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
                
    @property
    def pixmap(self) -> QtGui.QPixmap:
        """Retourne le pixmap actuel."""
        return self._pixmap_item.pixmap() if self._pixmap_item else QtGui.QPixmap()

    def get_pixmap_item(self) -> QtWidgets.QGraphicsPixmapItem:
        return self._pixmap_item

    def wheelEvent(self, event: QtGui.QWheelEvent) -> None:
        zoom_factor = 1.15
        if event.angleDelta().y() > 0:
            self.scale(zoom_factor, zoom_factor)
            self._zoom *= zoom_factor
        else:
            self.scale(1/zoom_factor, 1/zoom_factor)
            self._zoom /= zoom_factor
        self.viewChanged.emit()

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            item = self.itemAt(event.position().toPoint())
            if item == self._pixmap_item or item is None:
                self._panning = True
                self._last_pan_point = event.position().toPoint()
                self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            else:
                self._panning = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent) -> None:
        scene_pos = self.mapToScene(event.position().toPoint())
        self.mouseMoved.emit(scene_pos)
        if self._panning:
            delta = event.position().toPoint() - self._last_pan_point
            self._last_pan_point = event.position().toPoint()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            self.viewChanged.emit()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent) -> None:
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            if self._panning:
                self._panning = False
                self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
        super().mouseReleaseEvent(event)

    def reset_view(self) -> None:
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

    def get_transform(self) -> QtGui.QTransform:
        return self.transform()

    def set_transform(self, transform: QtGui.QTransform) -> None:
        super().setTransform(transform)
        self._zoom = self.transform().m11()
        
    def cache_transform(self, key: str) -> None:
        """Cache la transformation actuelle."""
        self._transform_cache[key] = self.transform()
        
    def restore_transform(self, key: str) -> bool:
        """Restaure une transformation mise en cache."""
        if key in self._transform_cache:
            self.set_transform(self._transform_cache[key])
            return True
        return False
        
    def set_background_color(self, color: Union[str, QtGui.QColor]) -> None:
        """Définit la couleur d'arrière-plan."""
        if isinstance(color, str):
            color = QtGui.QColor(color)
        self.setBackgroundBrush(QtGui.QBrush(color))
