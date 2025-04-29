"""
Shared pixmap item classes for PCB Mosaic and Image Comparer.
This module contains classes that are used by both the main application
and the PCB Mosaic feature, breaking the circular dependency.
"""

from PySide6 import QtCore, QtGui, QtWidgets
import math
import numpy as np

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
