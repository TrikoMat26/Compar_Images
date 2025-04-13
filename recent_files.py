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
        # Utiliser un emplacement plus simple et plus fiable pour le fichier de configuration
        self.config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recent_files.json")
        print(f"Fichier de configuration des fichiers récents : {self.config_file}")

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

        Returns:
            bool: True si le fichier a été ajouté avec succès, False sinon
        """
        if not file_path or not os.path.exists(file_path):
            print(f"Impossible d'ajouter le fichier récent : {file_path} (n'existe pas)")
            return False

        # Normaliser le chemin
        file_path = os.path.normpath(file_path)
        print(f"Ajout du fichier récent : {file_path} (Image {1 if is_image1 else 2})")

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
        return self.save_recent_files()

    def add_recent_pair(self, image1_path, image2_path):
        """
        Ajoute une paire d'images à la liste des paires récentes.

        Args:
            image1_path (str): Chemin de l'image 1
            image2_path (str): Chemin de l'image 2

        Returns:
            bool: True si la paire a été ajoutée avec succès, False sinon
        """
        if not image1_path or not image2_path or not os.path.exists(image1_path) or not os.path.exists(image2_path):
            print(f"Impossible d'ajouter la paire récente : {image1_path} & {image2_path} (un ou plusieurs fichiers n'existent pas)")
            return False

        # Normaliser les chemins
        image1_path = os.path.normpath(image1_path)
        image2_path = os.path.normpath(image2_path)
        print(f"Ajout de la paire récente : {image1_path} & {image2_path}")

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
        return self.save_recent_files()

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

    def get_recent_pairs(self, max_count=None):
        """
        Récupère la liste des paires d'images récentes.

        Args:
            max_count (int, optional): Nombre maximum de paires à renvoyer.
                                      Si None, renvoie toutes les paires.

        Returns:
            list: Liste des paires d'images récentes
        """
        if max_count is not None and max_count > 0:
            return self.recent_pairs[:max_count]
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
                print(f"Chargement des fichiers récents depuis {self.config_file}")
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.recent_files = data.get("files", [])
                    self.recent_pairs = data.get("pairs", [])

                    # Filtrer les fichiers qui n'existent plus
                    self.recent_files = [f for f in self.recent_files if os.path.exists(f["path"])]
                    self.recent_pairs = [p for p in self.recent_pairs
                                        if os.path.exists(p["image1"]) and os.path.exists(p["image2"])]

                    print(f"Chargé {len(self.recent_files)} fichiers récents et {len(self.recent_pairs)} paires")
                    return True
            else:
                print(f"Fichier de configuration {self.config_file} introuvable, création d'un nouveau fichier")
                self.recent_files = []
                self.recent_pairs = []
                self.save_recent_files()
                return False
        except Exception as e:
            print(f"Erreur lors du chargement des fichiers récents : {e}")
            self.recent_files = []
            self.recent_pairs = []

            # Essayer de sauvegarder un fichier vide pour réinitialiser
            try:
                self.save_recent_files()
            except Exception as save_error:
                print(f"Impossible de réinitialiser le fichier de configuration : {save_error}")
            return False

    def save_recent_files(self):
        """Enregistre la liste des fichiers récents dans le fichier de configuration."""
        try:
            # Filtrer les fichiers qui n'existent plus avant de sauvegarder
            self.recent_files = [f for f in self.recent_files if os.path.exists(f["path"])]
            self.recent_pairs = [p for p in self.recent_pairs
                                if os.path.exists(p["image1"]) and os.path.exists(p["image2"])]

            # Créer un dictionnaire simple pour le JSON
            data = {
                "files": self.recent_files,
                "pairs": self.recent_pairs
            }

            # Enregistrer le fichier
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)

            print(f"Sauvegardé {len(self.recent_files)} fichiers récents et {len(self.recent_pairs)} paires dans {self.config_file}")
            return True
        except Exception as e:
            print(f"Erreur lors de l'enregistrement des fichiers récents : {e}")
            return False

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

        # Créer les menus avec des icônes
        self.recent_menu = QtWidgets.QMenu("Fichiers récents", parent)
        self.recent_menu.setIcon(QtGui.QIcon.fromTheme("document-open-recent", QtGui.QIcon.fromTheme("document-open")))

        self.recent_image1_menu = QtWidgets.QMenu("Images 1 récentes", parent)
        self.recent_image1_menu.setIcon(QtGui.QIcon.fromTheme("image-x-generic"))

        self.recent_image2_menu = QtWidgets.QMenu("Images 2 récentes", parent)
        self.recent_image2_menu.setIcon(QtGui.QIcon.fromTheme("image-x-generic"))

        self.recent_pairs_menu = QtWidgets.QMenu("Paires récentes", parent)
        self.recent_pairs_menu.setIcon(QtGui.QIcon.fromTheme("view-dual", QtGui.QIcon.fromTheme("view-list-icons")))

        # Action pour effacer l'historique
        self.clear_action = QtGui.QAction("Effacer l'historique", parent)
        self.clear_action.setIcon(QtGui.QIcon.fromTheme("edit-clear", QtGui.QIcon.fromTheme("edit-delete")))
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

        # Ajouter un titre au menu principal
        title_action = QtGui.QAction("Fichiers récents", self.parent)
        title_action.setEnabled(False)
        font = title_action.font()
        font.setBold(True)
        title_action.setFont(font)
        self.recent_menu.addAction(title_action)
        self.recent_menu.addSeparator()

        # Ajouter les sous-menus
        self.recent_menu.addMenu(self.recent_image1_menu)
        self.recent_menu.addMenu(self.recent_image2_menu)
        self.recent_menu.addSeparator()
        self.recent_menu.addMenu(self.recent_pairs_menu)
        self.recent_menu.addSeparator()
        self.recent_menu.addAction(self.clear_action)

        # Afficher un message de débogage
        print("Menu des fichiers récents mis à jour")

        # Remplir le menu des images 1
        recent_files_1 = self.manager.get_recent_files(image1_only=True)
        if recent_files_1:
            for i, file in enumerate(recent_files_1):
                # Créer une nouvelle action avec un nom explicite pour faciliter le débogage
                action_name = f"Img1_{i}_{os.path.basename(file['path'])}"
                action = self._create_file_action(action_name, file["path"], True)
                if i < 9:
                    action.setShortcut(f"Ctrl+Alt+{i+1}")
                self.recent_image1_menu.addAction(action)
        else:
            empty_action = QtGui.QAction("(Aucune image récente)", self.parent)
            empty_action.setEnabled(False)
            self.recent_image1_menu.addAction(empty_action)

        # Remplir le menu des images 2
        recent_files_2 = self.manager.get_recent_files(image1_only=False)
        if recent_files_2:
            for i, file in enumerate(recent_files_2):
                action_name = f"Img2_{i}_{os.path.basename(file['path'])}"
                action = self._create_file_action(action_name, file["path"], False)
                self.recent_image2_menu.addAction(action)
        else:
            empty_action = QtGui.QAction("(Aucune image récente)", self.parent)
            empty_action.setEnabled(False)
            self.recent_image2_menu.addAction(empty_action)

        # Remplir le menu des paires
        recent_pairs = self.manager.get_recent_pairs()
        if recent_pairs:
            for i, pair in enumerate(recent_pairs):
                name1 = os.path.basename(pair["image1"])
                name2 = os.path.basename(pair["image2"])
                action_name = f"Pair_{i}_{name1}&{name2}"
                action = self._create_pair_action(action_name, pair["image1"], pair["image2"])
                if i < 9:
                    action.setShortcut(f"Ctrl+Shift+{i+1}")
                self.recent_pairs_menu.addAction(action)
        else:
            empty_action = QtGui.QAction("(Aucune paire récente)", self.parent)
            empty_action.setEnabled(False)
            self.recent_pairs_menu.addAction(empty_action)

    def _create_file_action(self, name, filepath, is_image1):
        """Crée une action pour un fichier récent avec une connexion fonctionnelle."""
        action = QtGui.QAction(os.path.basename(filepath), self.parent)
        action.setObjectName(name)
        action.setIcon(QtGui.QIcon.fromTheme("image-x-generic"))
        action.setToolTip(filepath)
        
        # Utilisation d'une lambda avec capture directe pour éviter les problèmes de closure
        action.triggered.connect(lambda checked=False, p=filepath, i=is_image1: 
                                self._load_recent_file_direct(p, i))
        return action

    def _create_pair_action(self, name, image1_path, image2_path):
        """Crée une action pour une paire d'images récentes avec une connexion fonctionnelle."""
        name1 = os.path.basename(image1_path)
        name2 = os.path.basename(image2_path)
        action = QtGui.QAction(f"{name1} & {name2}", self.parent)
        action.setObjectName(name)
        action.setIcon(QtGui.QIcon.fromTheme("view-dual", QtGui.QIcon.fromTheme("view-list-icons")))
        action.setToolTip(f"Image 1: {image1_path}\nImage 2: {image2_path}")
        
        # Utilisation d'une lambda avec capture directe
        action.triggered.connect(lambda checked=False, p1=image1_path, p2=image2_path: 
                                self._load_recent_pair_direct(p1, p2))
        return action

    def _load_recent_file_direct(self, filepath, is_image1):
        """
        Méthode directe pour charger un fichier récent, sans utiliser sender().
        Cette approche est plus fiable car elle ne dépend pas du signal/slot standard.
        """
        print(f"Loading file directly: {filepath}, is_image1={is_image1}")
        try:
            if hasattr(self.parent, 'load_recent_file'):
                self.parent.load_recent_file(filepath, is_image1)
            else:
                print("ERROR: Parent does not have load_recent_file method!")
        except Exception as e:
            print(f"Error loading recent file directly: {e}")

    def _load_recent_pair_direct(self, image1_path, image2_path):
        """
        Méthode directe pour charger une paire d'images récentes, sans utiliser sender().
        """
        print(f"Loading pair directly: {image1_path} & {image2_path}")
        try:
            if hasattr(self.parent, 'load_recent_pair'):
                self.parent.load_recent_pair(image1_path, image2_path)
            else:
                print("ERROR: Parent does not have load_recent_pair method!")
        except Exception as e:
            print(f"Error loading recent pair directly: {e}")

    def on_recent_file_selected(self):
        """
        Méthode de compatibilité maintenue, mais qui n'est plus utilisée directement.
        Les actions sont maintenant liées à _load_recent_file_direct.
        """
        print("WARNING: on_recent_file_selected called via old path!")
        action = self.parent.sender()
        if action and action.data():
            data = action.data()
            try:
                print(f"Tentative d'appel de load_recent_file avec {data['path']} et is_image1={data['is_image1']}")
                if hasattr(self.parent, 'load_recent_file'):
                    self.parent.load_recent_file(data["path"], data["is_image1"])
                else:
                    print("Erreur: La méthode load_recent_file n'est pas disponible dans le parent.")
            except Exception as e:
                print(f"Erreur lors du chargement du fichier récent: {e}")

    def on_recent_pair_selected(self):
        """
        Méthode de compatibilité maintenue, mais qui n'est plus utilisée directement.
        Les actions sont maintenant liées à _load_recent_pair_direct.
        """
        print("WARNING: on_recent_pair_selected called via old path!")
        action = self.parent.sender()
        if action and action.data():
            data = action.data()
            try:
                print(f"Tentative d'appel de load_recent_pair avec {data['image1']} et {data['image2']}")
                if hasattr(self.parent, 'load_recent_pair'):
                    self.parent.load_recent_pair(data["image1"], data["image2"])
                else:
                    print("Erreur: La méthode load_recent_pair n'est pas disponible dans le parent.")
            except Exception as e:
                print(f"Erreur lors du chargement de la paire récente: {e}")

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
