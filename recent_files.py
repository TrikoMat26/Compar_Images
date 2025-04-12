import os
import json
from PySide6 import QtCore, QtWidgets, QtGui

class RecentFilesManager:
    """
    Gestionnaire de fichiers récents pour l'application de comparaison d'images.
    Permet de stocker et récupérer les chemins des images récemment ouvertes.
    """
    def __init__(self, max_files=10):
        """
        Initialise le gestionnaire de fichiers récents.

        Args:
            max_files (int): Nombre maximum de fichiers récents à conserver
        """
        self.max_files = max_files
        self.recent_files = []
        self.recent_pairs = []
        self.config_file = os.path.join(
            QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.AppDataLocation),
            "image_comparer_recent.json"
        )

        # Créer le dossier de configuration s'il n'existe pas
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

        # Charger les fichiers récents
        self.load_recent_files()

    def add_recent_file(self, file_path, is_image1=True):
        """
        Ajoute un fichier à la liste des fichiers récents.

        Args:
            file_path (str): Chemin du fichier à ajouter
            is_image1 (bool): True si c'est l'image 1, False si c'est l'image 2
        """
        if not os.path.exists(file_path):
            return

        # Normaliser le chemin
        file_path = os.path.normpath(file_path)

        # Supprimer le fichier s'il est déjà dans la liste
        self.recent_files = [f for f in self.recent_files if f["path"] != file_path]

        # Ajouter le fichier au début de la liste
        self.recent_files.insert(0, {
            "path": file_path,
            "is_image1": is_image1,
            "timestamp": QtCore.QDateTime.currentDateTime().toString(QtCore.Qt.ISODate)
        })

        # Limiter le nombre de fichiers
        self.recent_files = self.recent_files[:self.max_files]

        # Enregistrer les modifications
        self.save_recent_files()

    def add_recent_pair(self, image1_path, image2_path):
        """
        Ajoute une paire d'images à la liste des paires récentes.

        Args:
            image1_path (str): Chemin de l'image 1
            image2_path (str): Chemin de l'image 2
        """
        if not os.path.exists(image1_path) or not os.path.exists(image2_path):
            return

        # Normaliser les chemins
        image1_path = os.path.normpath(image1_path)
        image2_path = os.path.normpath(image2_path)

        # Supprimer la paire si elle est déjà dans la liste
        self.recent_pairs = [p for p in self.recent_pairs
                            if not (p["image1"] == image1_path and p["image2"] == image2_path)]

        # Ajouter la paire au début de la liste
        self.recent_pairs.insert(0, {
            "image1": image1_path,
            "image2": image2_path,
            "timestamp": QtCore.QDateTime.currentDateTime().toString(QtCore.Qt.ISODate)
        })

        # Limiter le nombre de paires
        self.recent_pairs = self.recent_pairs[:self.max_files]

        # Enregistrer les modifications
        self.save_recent_files()

    def get_recent_files(self, image1_only=None):
        """
        Récupère la liste des fichiers récents.

        Args:
            image1_only (bool, optional): Si True, ne renvoie que les images 1.
                                         Si False, ne renvoie que les images 2.
                                         Si None, renvoie toutes les images.

        Returns:
            list: Liste des chemins des fichiers récents
        """
        if image1_only is None:
            return self.recent_files
        else:
            return [f for f in self.recent_files if f["is_image1"] == image1_only]

    def get_recent_pairs(self):
        """
        Récupère la liste des paires d'images récentes.

        Returns:
            list: Liste des paires d'images récentes
        """
        return self.recent_pairs

    def clear_recent_files(self):
        """Efface la liste des fichiers récents."""
        self.recent_files = []
        self.recent_pairs = []
        self.save_recent_files()

    def load_recent_files(self):
        """Charge la liste des fichiers récents depuis le fichier de configuration."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    data = json.load(f)
                    self.recent_files = data.get("files", [])
                    self.recent_pairs = data.get("pairs", [])
        except Exception as e:
            print(f"Erreur lors du chargement des fichiers récents : {e}")
            self.recent_files = []
            self.recent_pairs = []

    def save_recent_files(self):
        """Enregistre la liste des fichiers récents dans le fichier de configuration."""
        try:
            with open(self.config_file, 'w') as f:
                json.dump({
                    "files": self.recent_files,
                    "pairs": self.recent_pairs
                }, f, indent=2)
        except Exception as e:
            print(f"Erreur lors de l'enregistrement des fichiers récents : {e}")

class RecentFilesMenu:
    """
    Menu de fichiers récents pour l'application de comparaison d'images.
    """
    def __init__(self, parent, recent_files_manager):
        """
        Initialise le menu de fichiers récents.

        Args:
            parent (QWidget): Widget parent
            recent_files_manager (RecentFilesManager): Gestionnaire de fichiers récents
        """
        self.parent = parent
        self.manager = recent_files_manager

        # Créer les menus
        self.recent_menu = QtWidgets.QMenu("Fichiers récents", parent)
        self.recent_image1_menu = QtWidgets.QMenu("Images 1 récentes", parent)
        self.recent_image2_menu = QtWidgets.QMenu("Images 2 récentes", parent)
        self.recent_pairs_menu = QtWidgets.QMenu("Paires récentes", parent)

        # Action pour effacer l'historique
        self.clear_action = QtGui.QAction("Effacer l'historique", parent)
        self.clear_action.triggered.connect(self.clear_recent_files)

        # Mettre à jour les menus
        self.update_menus()

    def update_menus(self):
        """Met à jour le contenu des menus de fichiers récents."""
        # Vider les menus
        self.recent_menu.clear()
        self.recent_image1_menu.clear()
        self.recent_image2_menu.clear()
        self.recent_pairs_menu.clear()

        # Ajouter les sous-menus
        self.recent_menu.addMenu(self.recent_image1_menu)
        self.recent_menu.addMenu(self.recent_image2_menu)
        self.recent_menu.addSeparator()
        self.recent_menu.addMenu(self.recent_pairs_menu)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction(self.clear_action)

        # Remplir le menu des images 1
        for file in self.manager.get_recent_files(image1_only=True):
            action = QtGui.QAction(os.path.basename(file["path"]), self.parent)
            action.setData({"path": file["path"], "is_image1": True})
            action.setToolTip(file["path"])
            action.triggered.connect(self.on_recent_file_selected)
            self.recent_image1_menu.addAction(action)

        # Remplir le menu des images 2
        for file in self.manager.get_recent_files(image1_only=False):
            action = QtGui.QAction(os.path.basename(file["path"]), self.parent)
            action.setData({"path": file["path"], "is_image1": False})
            action.setToolTip(file["path"])
            action.triggered.connect(self.on_recent_file_selected)
            self.recent_image2_menu.addAction(action)

        # Remplir le menu des paires
        for pair in self.manager.get_recent_pairs():
            name1 = os.path.basename(pair["image1"])
            name2 = os.path.basename(pair["image2"])
            action = QtGui.QAction(f"{name1} & {name2}", self.parent)
            action.setData(pair)
            action.setToolTip(f"Image 1: {pair['image1']}\nImage 2: {pair['image2']}")
            action.triggered.connect(self.on_recent_pair_selected)
            self.recent_pairs_menu.addAction(action)

    def on_recent_file_selected(self):
        """Gère la sélection d'un fichier récent."""
        action = self.parent.sender()
        if action and action.data():
            data = action.data()
            self.parent.load_recent_file(data["path"], data["is_image1"])

    def on_recent_pair_selected(self):
        """Gère la sélection d'une paire d'images récente."""
        action = self.parent.sender()
        if action and action.data():
            data = action.data()
            self.parent.load_recent_pair(data["image1"], data["image2"])

    def clear_recent_files(self):
        """Efface l'historique des fichiers récents."""
        reply = QtWidgets.QMessageBox.question(
            self.parent,
            "Effacer l'historique",
            "Êtes-vous sûr de vouloir effacer l'historique des fichiers récents ?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
            QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            self.manager.clear_recent_files()
            self.update_menus()
