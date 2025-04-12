import sys
import os
from PySide6 import QtCore, QtGui, QtWidgets

# Modules personnalisés
from config import AppConfig
from graphics_items import MaskedOrFullPixmapItem, InteractiveSliderItem
from image_viewer import ImageViewer
from image_processing import ImageProcessor
from recent_files import RecentFiles
from i18n import translator

# Configuration globale
config = AppConfig()

# Classes déplacées dans des modules séparés


# -------------------------------------------------------------
# 5) Classe Principale (Application)
# -------------------------------------------------------------
class ImageComparerApp(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(self.tr("Image Comparer - Comparaison d'images"))
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
        self.size_adjust_options = config.size_adjust_options

        # Gestionnaire de fichiers récents
        self.recent_files = RecentFiles(max_files=10, config_file="recent_files.json")
        # Initialiser le menu des fichiers récents (sera rempli plus tard)
        self.recent_menu = None

        # Gestionnaire d'annotations
        self.annotation_mode = None  # None, 'arrow', 'text', 'rectangle'
        self.annotation_managers = {}
        self.current_annotation = None
        self.is_creating_annotation = False

        # Timer A/B
        self.ab_timer = QtCore.QTimer(self)
        self.ab_timer.timeout.connect(self.switch_ab_image)
        self.ab_switch_interval = config.default_ab_switch_interval
        self.ab_showing_image1 = True

        # Offsets side_by_side
        self._offset_x = 0
        self._offset_y = 0

        # Offsets slider
        self._slider_offset_x = 0.0
        self._slider_offset_y = 0.0

        self.setup_ui()
        self.update_display()

    def create_menus(self):
        """Crée la barre de menu principale."""
        # Créer la barre de menu
        self.menubar = QtWidgets.QMenuBar()
        self.setMenuBar(self.menubar)

        # Menu Fichier
        self.file_menu = self.menubar.addMenu(self.tr("&Fichier"))

        # Actions pour charger les images
        load_img1_action = QtGui.QAction(self.tr("Charger l'image &1..."), self)
        load_img1_action.setShortcut("Ctrl+1")
        load_img1_action.triggered.connect(lambda: self.load_image(1))
        self.file_menu.addAction(load_img1_action)

        load_img2_action = QtGui.QAction(self.tr("Charger l'image &2..."), self)
        load_img2_action.setShortcut("Ctrl+2")
        load_img2_action.triggered.connect(lambda: self.load_image(2))
        self.file_menu.addAction(load_img2_action)

        self.file_menu.addSeparator()

        # Sous-menu des fichiers récents
        self.recent_menu = self.file_menu.addMenu(self.tr("Fichiers récents"))
        self.update_recent_files_menu()

        self.file_menu.addSeparator()

        # Action pour quitter
        exit_action = QtGui.QAction(self.tr("&Quitter"), self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.file_menu.addAction(exit_action)

        # Menu Affichage
        view_menu = self.menubar.addMenu(self.tr("&Affichage"))

        # Actions pour les modes de comparaison
        side_by_side_action = QtGui.QAction(self.tr("Côte à côte"), self)
        side_by_side_action.setShortcut("1")
        side_by_side_action.triggered.connect(lambda: self.set_mode("side_by_side"))
        view_menu.addAction(side_by_side_action)

        slider_action = QtGui.QAction(self.tr("Curseur"), self)
        slider_action.setShortcut("2")
        slider_action.triggered.connect(lambda: self.set_mode("slider"))
        view_menu.addAction(slider_action)

        ab_switch_action = QtGui.QAction(self.tr("Bascule A/B"), self)
        ab_switch_action.setShortcut("3")
        ab_switch_action.triggered.connect(lambda: self.set_mode("ab_switch"))
        view_menu.addAction(ab_switch_action)

        # Ajouter le mode de différence
        diff_action = QtGui.QAction(self.tr("Différence"), self)
        diff_action.setShortcut("4")
        diff_action.triggered.connect(lambda: self.set_mode("difference"))
        view_menu.addAction(diff_action)

        view_menu.addSeparator()

        # Action pour réinitialiser la vue
        reset_view_action = QtGui.QAction(self.tr("Réinitialiser la vue"), self)
        reset_view_action.setShortcut("Ctrl+R")
        reset_view_action.triggered.connect(self.reset_all_views)
        view_menu.addAction(reset_view_action)

        # Menu Annotations
        annotations_menu = self.menubar.addMenu(self.tr("&Annotations"))

        # Actions pour les types d'annotations
        arrow_action = QtGui.QAction(self.tr("Flèche"), self)
        arrow_action.setShortcut("A")
        arrow_action.setCheckable(True)
        arrow_action.triggered.connect(lambda checked: self.set_annotation_mode("arrow" if checked else None))
        annotations_menu.addAction(arrow_action)

        text_action = QtGui.QAction(self.tr("Texte"), self)
        text_action.setShortcut("T")
        text_action.setCheckable(True)
        text_action.triggered.connect(lambda checked: self.set_annotation_mode("text" if checked else None))
        annotations_menu.addAction(text_action)

        rect_action = QtGui.QAction(self.tr("Rectangle"), self)
        rect_action.setShortcut("R")
        rect_action.setCheckable(True)
        rect_action.triggered.connect(lambda checked: self.set_annotation_mode("rectangle" if checked else None))
        annotations_menu.addAction(rect_action)

        annotations_menu.addSeparator()

        # Action pour effacer toutes les annotations
        clear_annotations_action = QtGui.QAction(self.tr("Effacer toutes les annotations"), self)
        clear_annotations_action.triggered.connect(self.clear_annotations)
        annotations_menu.addAction(clear_annotations_action)

        # Menu Outils
        tools_menu = self.menubar.addMenu(self.tr("&Outils"))

        # Action pour exporter l'image courante
        export_action = QtGui.QAction(self.tr("&Exporter l'image..."), self)
        export_action.setShortcut("Ctrl+E")
        export_action.triggered.connect(self.export_current_view)
        tools_menu.addAction(export_action)

    def update_recent_files_menu(self):
        """Met à jour le menu des fichiers récents."""
        # Vérifier si le menu des fichiers récents est initialisé
        if self.recent_menu is None:
            return

        # Effacer le menu existant
        self.recent_menu.clear()

        # Récupérer la liste des fichiers récents
        recent_files = self.recent_files.get_list()

        if not recent_files:
            # Ajouter une action désactivée si aucun fichier récent
            no_recent_action = QtGui.QAction(self.tr("Aucun fichier récent"), self)
            no_recent_action.setEnabled(False)
            self.recent_menu.addAction(no_recent_action)
            return

        # Ajouter une action pour chaque fichier récent
        for i, filepath in enumerate(recent_files):
            # Limiter la longueur du chemin pour l'affichage
            display_path = os.path.basename(filepath)
            if i < 9:  # Ajouter un raccourci pour les 9 premiers fichiers
                action_text = f"&{i+1}. {display_path}"
                shortcut = f"Alt+{i+1}"
            else:
                action_text = f"{i+1}. {display_path}"
                shortcut = ""

            action = QtGui.QAction(action_text, self)
            if shortcut:
                action.setShortcut(shortcut)

            # Utiliser une fonction lambda avec une valeur par défaut pour éviter les problèmes de portée
            action.triggered.connect(lambda checked=False, path=filepath: self.load_recent_file(path))
            self.recent_menu.addAction(action)

        self.recent_menu.addSeparator()

        # Action pour effacer la liste des fichiers récents
        clear_action = QtGui.QAction(self.tr("Effacer la liste"), self)
        clear_action.triggered.connect(self.clear_recent_files)
        self.recent_menu.addAction(clear_action)

    def load_recent_file(self, filepath):
        """Charge un fichier récent."""
        if not os.path.exists(filepath):
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Fichier introuvable"),
                self.tr(f"Le fichier {filepath} n'existe plus.")
            )
            # Supprimer le fichier de la liste des fichiers récents
            self.recent_files.remove(filepath)
            self.update_recent_files_menu()
            return

        # Déterminer s'il faut charger dans l'image 1 ou 2
        # Par défaut, charger dans l'image 1 si elle est vide, sinon dans l'image 2
        if self.image_path1 is None:
            self.load_image(1, filepath)
        else:
            self.load_image(2, filepath)

    def clear_recent_files(self):
        """Efface la liste des fichiers récents."""
        self.recent_files.clear()
        self.update_recent_files_menu()

    def setup_ui(self):
        # Créer les menus
        self.create_menus()

        # Widget principal
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
        self.slider_ab_speed.setRange(config.min_ab_switch_interval, config.max_ab_switch_interval)
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
    def load_image(self, image_num, filepath=None):
        # Si aucun chemin n'est fourni, ouvrir une boîte de dialogue pour sélectionner un fichier
        if filepath is None:
            filepath, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, self.tr(f"Sélectionner l'image {image_num}"), "",
                self.tr("Fichiers image (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;Tous les fichiers (*)")
            )
            if not filepath:
                return
        try:
            # Utiliser le module ImageProcessor pour charger l'image
            pil_img_conv = ImageProcessor.load_image(filepath, max_dim=config.max_image_dim_load)
            if pil_img_conv is None:
                raise ValueError(self.tr("Impossible de charger l'image"))

            # Convertir en QPixmap
            qt_pixmap = ImageProcessor.pil_to_qpixmap(pil_img_conv)

            # Ajouter aux fichiers récents
            self.recent_files.add(filepath)
            # Mettre à jour le menu des fichiers récents
            self.update_recent_files_menu()

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
            QtWidgets.QMessageBox.critical(self, self.tr("Erreur de chargement"), f"{self.tr('Impossible de charger l\'image')}:\n{e}")
            if image_num == 1:
                self.image_path1 = None
                self.pil_image1_orig = None
                self.qt_pixmap1_orig = None
                self.lbl_img1.setText(self.tr("Pas d'image 1"))
            else:
                self.image_path2 = None
                self.pil_image2_orig = None
                self.qt_pixmap2_orig = None
                self.lbl_img2.setText(self.tr("Pas d'image 2"))
            self.update_display()

    def pil_to_qpixmap(self, pil_image):
        """Méthode de compatibilité - utilise ImageProcessor.pil_to_qpixmap"""
        return ImageProcessor.pil_to_qpixmap(pil_image)

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
                self.sync_views(self.view1)

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
            elif self.current_mode == "difference":
                # Mode Différence - créer et afficher l'image de différence
                standard_pixmap_item = self.view_combined.get_pixmap_item()
                self.item1.setVisible(False)
                self.item2.setVisible(False)

                if self.pil_image1_orig and self.pil_image2_orig:
                    # Créer l'image de différence
                    diff_pixmap = self.create_difference_image()
                    if diff_pixmap and not diff_pixmap.isNull():
                        standard_pixmap_item.setPixmap(diff_pixmap)
                        print("Mode différence: Image de différence créée.")
                    else:
                        standard_pixmap_item.setPixmap(QtGui.QPixmap())
                        print("Mode différence: Impossible de créer l'image de différence.")
                else:
                    standard_pixmap_item.setPixmap(QtGui.QPixmap())
                    print("Mode différence: Deux images sont nécessaires.")

            self.view_combined.reset_view()

    def prepare_display_images(self):
        """Prépare les images pour l'affichage en fonction du mode d'ajustement sélectionné."""
        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig
        self.display_pixmap1 = self.qt_pixmap1_orig if self.qt_pixmap1_orig else QtGui.QPixmap()
        self.display_pixmap2 = self.qt_pixmap2_orig if self.qt_pixmap2_orig else QtGui.QPixmap()

        # Si l'une des images est manquante ou si elles ont la même taille, pas besoin d'ajuster
        if not pil1 or not pil2 or pil1.size == pil2.size:
            return

        adjust_mode = self.size_adjust_mode
        print(f"Ajustement de taille: {adjust_mode}")

        # Utiliser le module ImageProcessor pour ajuster les images
        pil1_adjusted, pil2_adjusted = ImageProcessor.adjust_images_for_comparison(
            pil1, pil2, mode=adjust_mode
        )

        # Mettre à jour les pixmaps si les images ont été modifiées
        if pil1_adjusted is not pil1:
            self.display_pixmap1 = ImageProcessor.pil_to_qpixmap(pil1_adjusted)
            print(f"Image 1 ajustée: {pil1_adjusted.width}x{pil1_adjusted.height}")

        if pil2_adjusted is not pil2:
            self.display_pixmap2 = ImageProcessor.pil_to_qpixmap(pil2_adjusted)
            print(f"Image 2 ajustée: {pil2_adjusted.width}x{pil2_adjusted.height}")

    def update_comparison_image(self):
        """Met à jour l'image de comparaison pour le mode opacité."""
        if self.current_mode != "opacity":
            self.comparison_pixmap = None
            return
        if not self.pil_image1_orig and not self.pil_image2_orig:
            self.comparison_pixmap = None
            return

        pil1 = self.pil_image1_orig
        pil2 = self.pil_image2_orig

        if pil1 and pil2:
            try:
                # Utiliser le module ImageProcessor pour créer l'image fusionnée
                alpha = getattr(self, 'opacity_value', 0.5)  # Valeur par défaut si non définie
                result = ImageProcessor.create_blend_image(pil1, pil2, alpha)
                self.comparison_pixmap = ImageProcessor.pil_to_qpixmap(result)
            except Exception as e:
                print(f"Erreur lors de la fusion des images: {e}")
                self.comparison_pixmap = None
        elif pil1:
            self.comparison_pixmap = ImageProcessor.pil_to_qpixmap(pil1)
        elif pil2:
            self.comparison_pixmap = ImageProcessor.pil_to_qpixmap(pil2)

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

    def sync_views(self, source_view):
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

        try:
            # Utiliser le module ImageProcessor pour créer l'image fusionnée
            # Convertir d'abord les QPixmap en images PIL
            pil1 = ImageProcessor.qpixmap_to_pil(self.display_pixmap1)
            pil2 = ImageProcessor.qpixmap_to_pil(self.display_pixmap2)

            if pil1 is None or pil2 is None:
                return None

            # Créer l'image fusionnée avec un alpha de 0.5 (50%)
            result = ImageProcessor.create_blend_image(pil1, pil2, alpha=0.5)

            # Convertir le résultat en QPixmap
            return ImageProcessor.pil_to_qpixmap(result)
        except Exception as e:
            print(f"Erreur lors de la création de l'image combinée: {e}")
            return None

    def pil_to_qimage(self, pixmap):
        """Convertit un QPixmap en QImage."""
        if pixmap.isNull():
            return QtGui.QImage()
        return pixmap.toImage()

    def create_difference_image(self):
        """Crée une image montrant les différences entre les deux images."""
        if not self.pil_image1_orig or not self.pil_image2_orig:
            return None

        try:
            # Utiliser le module ImageProcessor pour créer l'image de différence
            # Convertir d'abord les QPixmap en images PIL si nécessaire
            pil1 = self.pil_image1_orig
            pil2 = self.pil_image2_orig

            # Créer l'image de différence avec une amplification de 2.0
            result = ImageProcessor.create_difference_image(pil1, pil2, amplify=2.0)

            # Convertir le résultat en QPixmap
            return ImageProcessor.pil_to_qpixmap(result)
        except Exception as e:
            print(f"Erreur lors de la création de l'image de différence: {e}")
            return None

    def set_annotation_mode(self, mode):
        """Définit le mode d'annotation actuel."""
        # Désactiver le mode précédent
        if self.annotation_mode == mode:
            # Si on clique sur le même mode, le désactiver
            self.annotation_mode = None
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            print(f"Mode annotation désactivé")
        else:
            # Activer le nouveau mode
            self.annotation_mode = mode
            if mode == "arrow":
                self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
                print(f"Mode annotation: Flèche")
            elif mode == "text":
                self.setCursor(QtCore.Qt.CursorShape.IBeamCursor)
                print(f"Mode annotation: Texte")
            elif mode == "rectangle":
                self.setCursor(QtCore.Qt.CursorShape.CrossCursor)
                print(f"Mode annotation: Rectangle")
            else:
                self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
                print(f"Mode annotation désactivé")

    def clear_annotations(self):
        """Efface toutes les annotations."""
        for manager in self.annotation_managers.values():
            manager.clear_annotations()
        print("Toutes les annotations ont été effacées")

    def initialize_annotation_manager(self, scene):
        """Initialise un gestionnaire d'annotations pour une scène."""
        from annotations import AnnotationManager
        if scene not in self.annotation_managers:
            self.annotation_managers[scene] = AnnotationManager(scene)
        return self.annotation_managers[scene]

    def export_current_view(self):
        """Exporte la vue actuelle vers un fichier image."""
        # Déterminer quelle vue exporter
        if self.current_mode == "side_by_side":
            # Demander à l'utilisateur quelle vue exporter
            options = [self.tr("Image 1"), self.tr("Image 2")]
            choice, ok = QtWidgets.QInputDialog.getItem(
                self,
                self.tr("Exporter la vue"),
                self.tr("Choisissez la vue à exporter:"),
                options,
                0,
                False
            )
            if not ok:
                return

            if choice == options[0]:  # Image 1
                pixmap = self.view1.get_pixmap_item().pixmap()
            else:  # Image 2
                pixmap = self.view2.get_pixmap_item().pixmap()
        else:
            # Pour les autres modes, exporter la vue combinée
            pixmap = self.view_combined.get_pixmap_item().pixmap()

        if pixmap.isNull():
            QtWidgets.QMessageBox.warning(
                self,
                self.tr("Erreur d'exportation"),
                self.tr("Aucune image à exporter.")
            )
            return

        # Demander le chemin de sauvegarde
        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self,
            self.tr("Exporter l'image"),
            "",
            self.tr("Images (*.png *.jpg *.jpeg *.bmp);;Tous les fichiers (*)")
        )

        if not filepath:
            return

        # Ajouter l'extension .png si aucune extension n'est spécifiée
        if not os.path.splitext(filepath)[1]:
            filepath += ".png"

        # Sauvegarder l'image
        try:
            pixmap.save(filepath)
            print(f"Image exportée vers {filepath}")
            QtWidgets.QMessageBox.information(
                self,
                self.tr("Exportation réussie"),
                self.tr(f"L'image a été exportée vers {filepath}")
            )
        except Exception as e:
            QtWidgets.QMessageBox.critical(
                self,
                self.tr("Erreur d'exportation"),
                self.tr(f"Impossible d'exporter l'image: {e}")
            )


# -------------------------------------------------------------
# Point d'entrée
# -------------------------------------------------------------
if __name__ == "__main__":
    # Activer le support haute résolution
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    # Créer l'application
    app = QtWidgets.QApplication(sys.argv)

    # Configurer la traduction
    translator.set_application(app)
    translator.load_language("fr")  # Langue par défaut

    # Créer et afficher la fenêtre principale
    window = ImageComparerApp()
    window.show()

    # Ajouter des raccourcis clavier globaux
    QtGui.QShortcut(QtGui.QKeySequence("Ctrl+1"), window, lambda: window.load_image(1))
    QtGui.QShortcut(QtGui.QKeySequence("Ctrl+2"), window, lambda: window.load_image(2))
    QtGui.QShortcut(QtGui.QKeySequence("Ctrl+R"), window, window.reset_all_views)
    QtGui.QShortcut(QtGui.QKeySequence("1"), window, lambda: window.set_mode("side_by_side"))
    QtGui.QShortcut(QtGui.QKeySequence("2"), window, lambda: window.set_mode("slider"))
    QtGui.QShortcut(QtGui.QKeySequence("3"), window, lambda: window.set_mode("ab_switch"))
    QtGui.QShortcut(QtGui.QKeySequence("4"), window, lambda: window.set_mode("difference"))

    # Exécuter l'application
    sys.exit(app.exec())
