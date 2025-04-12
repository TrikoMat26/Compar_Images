from typing import Optional, List, Tuple, Dict, Any
from PySide6 import QtCore, QtGui, QtWidgets

class AnnotationItem(QtWidgets.QGraphicsItem):
    """Classe de base pour les annotations."""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self._color = QtGui.QColor(255, 0, 0)  # Rouge par défaut
        self._line_width = 2
        
    def set_color(self, color: QtGui.QColor) -> None:
        """Définit la couleur de l'annotation."""
        self._color = color
        self.update()
        
    def set_line_width(self, width: int) -> None:
        """Définit l'épaisseur de ligne de l'annotation."""
        self._line_width = width
        self.update()
        
    def get_properties(self) -> Dict[str, Any]:
        """Retourne les propriétés de l'annotation pour la sérialisation."""
        return {
            "type": self.__class__.__name__,
            "pos_x": self.pos().x(),
            "pos_y": self.pos().y(),
            "color": self._color.name(),
            "line_width": self._line_width
        }
        
    def set_properties(self, props: Dict[str, Any]) -> None:
        """Définit les propriétés de l'annotation à partir d'un dictionnaire."""
        if "pos_x" in props and "pos_y" in props:
            self.setPos(props["pos_x"], props["pos_y"])
        if "color" in props:
            self._color = QtGui.QColor(props["color"])
        if "line_width" in props:
            self._line_width = props["line_width"]
        self.update()


class ArrowAnnotation(AnnotationItem):
    """Annotation de type flèche."""
    
    def __init__(self, start_point: QtCore.QPointF, end_point: QtCore.QPointF, parent=None):
        super().__init__(parent)
        self._start = start_point
        self._end = end_point
        self._arrow_size = 10
        
    def boundingRect(self) -> QtCore.QRectF:
        """Retourne le rectangle englobant de l'annotation."""
        # Ajouter une marge pour la pointe de flèche
        margin = self._arrow_size + self._line_width
        return QtCore.QRectF(
            min(self._start.x(), self._end.x()) - margin,
            min(self._start.y(), self._end.y()) - margin,
            abs(self._end.x() - self._start.x()) + 2 * margin,
            abs(self._end.y() - self._start.y()) + 2 * margin
        )
        
    def paint(self, painter: QtGui.QPainter, option, widget=None) -> None:
        """Dessine la flèche."""
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # Définir le style de ligne
        pen = QtGui.QPen(self._color, self._line_width)
        painter.setPen(pen)
        
        # Dessiner la ligne
        painter.drawLine(self._start, self._end)
        
        # Calculer l'angle de la flèche
        angle = QtCore.QLineF(self._end, self._start).angle()
        
        # Dessiner la pointe de flèche
        arrow_p1 = self._end + QtCore.QPointF(
            self._arrow_size * QtCore.qCos(QtCore.qDegreesToRadians(angle + 150)),
            -self._arrow_size * QtCore.qSin(QtCore.qDegreesToRadians(angle + 150))
        )
        arrow_p2 = self._end + QtCore.QPointF(
            self._arrow_size * QtCore.qCos(QtCore.qDegreesToRadians(angle + 210)),
            -self._arrow_size * QtCore.qSin(QtCore.qDegreesToRadians(angle + 210))
        )
        
        arrow_head = QtGui.QPolygonF()
        arrow_head.append(self._end)
        arrow_head.append(arrow_p1)
        arrow_head.append(arrow_p2)
        
        painter.setBrush(QtGui.QBrush(self._color))
        painter.drawPolygon(arrow_head)
        
        # Dessiner un contour si sélectionné
        if self.isSelected():
            select_pen = QtGui.QPen(QtCore.Qt.GlobalColor.blue, 1, QtCore.Qt.PenStyle.DashLine)
            painter.setPen(select_pen)
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            
    def set_end_point(self, point: QtCore.QPointF) -> None:
        """Définit le point d'arrivée de la flèche."""
        self._end = point
        self.update()
        
    def get_properties(self) -> Dict[str, Any]:
        """Retourne les propriétés spécifiques à la flèche."""
        props = super().get_properties()
        props.update({
            "start_x": self._start.x(),
            "start_y": self._start.y(),
            "end_x": self._end.x(),
            "end_y": self._end.y(),
            "arrow_size": self._arrow_size
        })
        return props
        
    def set_properties(self, props: Dict[str, Any]) -> None:
        """Définit les propriétés spécifiques à la flèche."""
        super().set_properties(props)
        if "start_x" in props and "start_y" in props:
            self._start = QtCore.QPointF(props["start_x"], props["start_y"])
        if "end_x" in props and "end_y" in props:
            self._end = QtCore.QPointF(props["end_x"], props["end_y"])
        if "arrow_size" in props:
            self._arrow_size = props["arrow_size"]
        self.update()


class TextAnnotation(AnnotationItem):
    """Annotation de type texte."""
    
    def __init__(self, position: QtCore.QPointF, text: str = "", parent=None):
        super().__init__(parent)
        self._text = text
        self._font = QtGui.QFont("Arial", 12)
        self._background_color = QtGui.QColor(255, 255, 255, 180)  # Blanc semi-transparent
        self._text_color = QtGui.QColor(0, 0, 0)  # Noir
        self._padding = 5
        self.setPos(position)
        
    def boundingRect(self) -> QtCore.QRectF:
        """Retourne le rectangle englobant du texte."""
        font_metrics = QtGui.QFontMetrics(self._font)
        text_rect = font_metrics.boundingRect(QtCore.QRect(0, 0, 1000, 1000), 
                                             QtCore.Qt.TextFlag.TextWordWrap, 
                                             self._text)
        return QtCore.QRectF(0, 0, 
                            text_rect.width() + 2 * self._padding, 
                            text_rect.height() + 2 * self._padding)
        
    def paint(self, painter: QtGui.QPainter, option, widget=None) -> None:
        """Dessine le texte avec son fond."""
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # Dessiner le fond
        painter.setPen(QtCore.Qt.PenStyle.NoPen)
        painter.setBrush(QtGui.QBrush(self._background_color))
        painter.drawRoundedRect(self.boundingRect(), 5, 5)
        
        # Dessiner le texte
        painter.setFont(self._font)
        painter.setPen(self._text_color)
        painter.drawText(self.boundingRect().adjusted(self._padding, self._padding, -self._padding, -self._padding),
                        QtCore.Qt.TextFlag.TextWordWrap,
                        self._text)
        
        # Dessiner un contour si sélectionné
        if self.isSelected():
            painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.blue, 1, QtCore.Qt.PenStyle.DashLine))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            
    def set_text(self, text: str) -> None:
        """Définit le texte de l'annotation."""
        self._text = text
        self.update()
        
    def set_font(self, font: QtGui.QFont) -> None:
        """Définit la police du texte."""
        self._font = font
        self.update()
        
    def set_text_color(self, color: QtGui.QColor) -> None:
        """Définit la couleur du texte."""
        self._text_color = color
        self.update()
        
    def set_background_color(self, color: QtGui.QColor) -> None:
        """Définit la couleur de fond du texte."""
        self._background_color = color
        self.update()
        
    def get_properties(self) -> Dict[str, Any]:
        """Retourne les propriétés spécifiques au texte."""
        props = super().get_properties()
        props.update({
            "text": self._text,
            "font_family": self._font.family(),
            "font_size": self._font.pointSize(),
            "text_color": self._text_color.name(),
            "background_color": self._background_color.name(),
            "background_alpha": self._background_color.alpha(),
            "padding": self._padding
        })
        return props
        
    def set_properties(self, props: Dict[str, Any]) -> None:
        """Définit les propriétés spécifiques au texte."""
        super().set_properties(props)
        if "text" in props:
            self._text = props["text"]
        if "font_family" in props and "font_size" in props:
            self._font = QtGui.QFont(props["font_family"], props["font_size"])
        if "text_color" in props:
            self._text_color = QtGui.QColor(props["text_color"])
        if "background_color" in props:
            self._background_color = QtGui.QColor(props["background_color"])
            if "background_alpha" in props:
                self._background_color.setAlpha(props["background_alpha"])
        if "padding" in props:
            self._padding = props["padding"]
        self.update()


class RectangleAnnotation(AnnotationItem):
    """Annotation de type rectangle."""
    
    def __init__(self, rect: QtCore.QRectF, parent=None):
        super().__init__(parent)
        self._rect = rect
        self._fill_color = QtGui.QColor(255, 255, 0, 50)  # Jaune semi-transparent
        
    def boundingRect(self) -> QtCore.QRectF:
        """Retourne le rectangle englobant."""
        return self._rect.adjusted(-self._line_width/2, -self._line_width/2, 
                                  self._line_width/2, self._line_width/2)
        
    def paint(self, painter: QtGui.QPainter, option, widget=None) -> None:
        """Dessine le rectangle."""
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        
        # Dessiner le rectangle rempli
        painter.setPen(QtGui.QPen(self._color, self._line_width))
        painter.setBrush(QtGui.QBrush(self._fill_color))
        painter.drawRect(self._rect)
        
        # Dessiner un contour si sélectionné
        if self.isSelected():
            painter.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.blue, 1, QtCore.Qt.PenStyle.DashLine))
            painter.setBrush(QtCore.Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())
            
    def set_rect(self, rect: QtCore.QRectF) -> None:
        """Définit le rectangle."""
        self._rect = rect
        self.update()
        
    def set_fill_color(self, color: QtGui.QColor) -> None:
        """Définit la couleur de remplissage."""
        self._fill_color = color
        self.update()
        
    def get_properties(self) -> Dict[str, Any]:
        """Retourne les propriétés spécifiques au rectangle."""
        props = super().get_properties()
        props.update({
            "rect_x": self._rect.x(),
            "rect_y": self._rect.y(),
            "rect_width": self._rect.width(),
            "rect_height": self._rect.height(),
            "fill_color": self._fill_color.name(),
            "fill_alpha": self._fill_color.alpha()
        })
        return props
        
    def set_properties(self, props: Dict[str, Any]) -> None:
        """Définit les propriétés spécifiques au rectangle."""
        super().set_properties(props)
        if all(k in props for k in ["rect_x", "rect_y", "rect_width", "rect_height"]):
            self._rect = QtCore.QRectF(
                props["rect_x"], props["rect_y"],
                props["rect_width"], props["rect_height"]
            )
        if "fill_color" in props:
            self._fill_color = QtGui.QColor(props["fill_color"])
            if "fill_alpha" in props:
                self._fill_color.setAlpha(props["fill_alpha"])
        self.update()


class AnnotationManager:
    """Gestionnaire d'annotations pour une scène."""
    
    def __init__(self, scene: QtWidgets.QGraphicsScene):
        self.scene = scene
        self.annotations: List[AnnotationItem] = []
        self.current_annotation = None
        self.is_creating = False
        
    def add_annotation(self, annotation: AnnotationItem) -> None:
        """Ajoute une annotation à la scène."""
        self.annotations.append(annotation)
        self.scene.addItem(annotation)
        
    def remove_annotation(self, annotation: AnnotationItem) -> None:
        """Supprime une annotation de la scène."""
        if annotation in self.annotations:
            self.annotations.remove(annotation)
            self.scene.removeItem(annotation)
            
    def clear_annotations(self) -> None:
        """Supprime toutes les annotations de la scène."""
        for annotation in self.annotations[:]:  # Copie de la liste pour éviter les problèmes de modification pendant l'itération
            self.scene.removeItem(annotation)
        self.annotations.clear()
        
    def start_arrow(self, start_point: QtCore.QPointF) -> None:
        """Commence la création d'une flèche."""
        self.is_creating = True
        self.current_annotation = ArrowAnnotation(start_point, start_point)
        self.scene.addItem(self.current_annotation)
        
    def update_arrow(self, end_point: QtCore.QPointF) -> None:
        """Met à jour la flèche en cours de création."""
        if self.is_creating and isinstance(self.current_annotation, ArrowAnnotation):
            self.current_annotation.set_end_point(end_point)
            
    def finish_arrow(self) -> None:
        """Termine la création d'une flèche."""
        if self.is_creating and isinstance(self.current_annotation, ArrowAnnotation):
            self.annotations.append(self.current_annotation)
            self.is_creating = False
            self.current_annotation = None
            
    def add_text(self, position: QtCore.QPointF, text: str = "") -> TextAnnotation:
        """Ajoute une annotation de texte."""
        text_annotation = TextAnnotation(position, text)
        self.add_annotation(text_annotation)
        return text_annotation
        
    def start_rectangle(self, start_point: QtCore.QPointF) -> None:
        """Commence la création d'un rectangle."""
        self.is_creating = True
        self.current_annotation = RectangleAnnotation(QtCore.QRectF(start_point, QtCore.QSizeF(0, 0)))
        self.scene.addItem(self.current_annotation)
        
    def update_rectangle(self, current_point: QtCore.QPointF) -> None:
        """Met à jour le rectangle en cours de création."""
        if self.is_creating and isinstance(self.current_annotation, RectangleAnnotation):
            start_pos = self.current_annotation.pos()
            rect = QtCore.QRectF(0, 0, 
                               current_point.x() - start_pos.x(), 
                               current_point.y() - start_pos.y())
            self.current_annotation.set_rect(rect)
            
    def finish_rectangle(self) -> None:
        """Termine la création d'un rectangle."""
        if self.is_creating and isinstance(self.current_annotation, RectangleAnnotation):
            self.annotations.append(self.current_annotation)
            self.is_creating = False
            self.current_annotation = None
            
    def serialize_annotations(self) -> List[Dict[str, Any]]:
        """Sérialise toutes les annotations pour la sauvegarde."""
        return [annotation.get_properties() for annotation in self.annotations]
        
    def deserialize_annotations(self, data: List[Dict[str, Any]]) -> None:
        """Charge des annotations à partir de données sérialisées."""
        self.clear_annotations()
        
        for item_data in data:
            annotation_type = item_data.get("type")
            if annotation_type == "ArrowAnnotation":
                if all(k in item_data for k in ["start_x", "start_y", "end_x", "end_y"]):
                    start = QtCore.QPointF(item_data["start_x"], item_data["start_y"])
                    end = QtCore.QPointF(item_data["end_x"], item_data["end_y"])
                    annotation = ArrowAnnotation(start, end)
                    annotation.set_properties(item_data)
                    self.add_annotation(annotation)
            elif annotation_type == "TextAnnotation":
                if "text" in item_data:
                    pos = QtCore.QPointF(item_data.get("pos_x", 0), item_data.get("pos_y", 0))
                    annotation = TextAnnotation(pos, item_data["text"])
                    annotation.set_properties(item_data)
                    self.add_annotation(annotation)
            elif annotation_type == "RectangleAnnotation":
                if all(k in item_data for k in ["rect_x", "rect_y", "rect_width", "rect_height"]):
                    rect = QtCore.QRectF(
                        item_data["rect_x"], item_data["rect_y"],
                        item_data["rect_width"], item_data["rect_height"]
                    )
                    annotation = RectangleAnnotation(rect)
                    annotation.set_properties(item_data)
                    self.add_annotation(annotation)
