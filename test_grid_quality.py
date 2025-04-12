import sys
import os
from PySide6 import QtWidgets, QtGui, QtCore
from image_compare import ImageViewer, GridItem

class TestWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test Grid and Quality")
        self.setGeometry(100, 100, 800, 600)

        # Widget central
        central_widget = QtWidgets.QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QtWidgets.QVBoxLayout(central_widget)

        # Créer la vue
        self.image_viewer = ImageViewer()
        main_layout.addWidget(self.image_viewer, 1)

        # Panneau de contrôle
        control_panel = QtWidgets.QFrame()
        control_panel.setFrameShape(QtWidgets.QFrame.Shape.StyledPanel)
        control_layout = QtWidgets.QHBoxLayout(control_panel)
        main_layout.addWidget(control_panel)

        # Bouton pour charger une image
        btn_load = QtWidgets.QPushButton("Charger une image")
        btn_load.clicked.connect(self.load_image)
        control_layout.addWidget(btn_load)

        # Case à cocher pour la grille
        self.check_grid = QtWidgets.QCheckBox("Afficher la grille")
        self.check_grid.toggled.connect(self.toggle_grid)
        control_layout.addWidget(self.check_grid)

        # Slider pour la taille de la grille
        grid_size_layout = QtWidgets.QHBoxLayout()
        grid_size_layout.addWidget(QtWidgets.QLabel("Taille de la grille:"))
        self.slider_grid_size = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_grid_size.setRange(10, 200)
        self.slider_grid_size.setValue(50)
        self.slider_grid_size.valueChanged.connect(self.change_grid_size)
        grid_size_layout.addWidget(self.slider_grid_size)
        control_layout.addLayout(grid_size_layout)

        # Case à cocher pour la qualité
        self.check_quality = QtWidgets.QCheckBox("Haute qualité")
        self.check_quality.setChecked(True)
        self.check_quality.toggled.connect(self.toggle_quality)
        control_layout.addWidget(self.check_quality)

        # Bouton pour changer la couleur de la grille
        btn_color = QtWidgets.QPushButton("Couleur de la grille")
        btn_color.clicked.connect(self.change_grid_color)
        control_layout.addWidget(btn_color)

        # Initialiser la grille (désactivée par défaut)
        self.toggle_grid(False)

    def load_image(self):
        filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
            self, "Sélectionner une image", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;Tous les fichiers (*)"
        )
        if filepath:
            pixmap = QtGui.QPixmap(filepath)
            if not pixmap.isNull():
                self.image_viewer.set_pixmap(pixmap)
                self.setWindowTitle(f"Test Grid and Quality - {os.path.basename(filepath)}")

    def toggle_grid(self, checked):
        self.image_viewer.set_grid_visible(checked)
        self.slider_grid_size.setEnabled(checked)

    def change_grid_size(self, size):
        self.image_viewer.set_grid_size(size)

    def toggle_quality(self, checked):
        # Appliquer le paramètre à la vue
        self.image_viewer.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing, checked)
        self.image_viewer.setRenderHint(QtGui.QPainter.RenderHint.SmoothPixmapTransform, checked)
        self.image_viewer.setRenderHint(QtGui.QPainter.RenderHint.TextAntialiasing, checked)

        # Définir la qualité de transformation
        if checked:
            # Haute qualité - utiliser une transformation bilinéaire
            self.image_viewer._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.SmoothTransformation)
        else:
            # Qualité standard - utiliser une transformation rapide
            self.image_viewer._pixmap_item.setTransformationMode(QtCore.Qt.TransformationMode.FastTransformation)

        # Mettre à jour l'affichage
        self.image_viewer.viewport().update()

    def change_grid_color(self):
        color = QtWidgets.QColorDialog.getColor(
            QtGui.QColor(255, 0, 0, 100), self, "Sélectionner la couleur de la grille"
        )
        if color.isValid():
            self.image_viewer.set_grid_color(color)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec())
