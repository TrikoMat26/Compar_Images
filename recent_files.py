from typing import List, Optional
import os
import json

class RecentFiles:
    """Gère la liste des fichiers récemment ouverts."""
    
    def __init__(self, max_files: int = 10, config_file: str = "recent_files.json"):
        self.max_files = max_files
        self.config_file = config_file
        self.recent_files = []
        self.load()
        
    def add(self, filepath: str) -> None:
        """Ajoute un fichier à la liste des fichiers récents."""
        if not filepath or not os.path.exists(filepath):
            return
            
        # Normaliser le chemin
        filepath = os.path.abspath(filepath)
        
        # Supprimer si déjà présent (pour le déplacer en tête de liste)
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
            
        # Ajouter en tête de liste
        self.recent_files.insert(0, filepath)
        
        # Limiter la taille de la liste
        if len(self.recent_files) > self.max_files:
            self.recent_files = self.recent_files[:self.max_files]
            
        # Sauvegarder les changements
        self.save()
        
    def remove(self, filepath: str) -> None:
        """Supprime un fichier de la liste des fichiers récents."""
        filepath = os.path.abspath(filepath)
        if filepath in self.recent_files:
            self.recent_files.remove(filepath)
            self.save()
            
    def clear(self) -> None:
        """Efface la liste des fichiers récents."""
        self.recent_files = []
        self.save()
        
    def get_list(self) -> List[str]:
        """Retourne la liste des fichiers récents."""
        # Filtrer les fichiers qui n'existent plus
        valid_files = [f for f in self.recent_files if os.path.exists(f)]
        
        # Mettre à jour la liste si des fichiers ont été supprimés
        if len(valid_files) != len(self.recent_files):
            self.recent_files = valid_files
            self.save()
            
        return self.recent_files
        
    def load(self) -> None:
        """Charge la liste des fichiers récents depuis le fichier de configuration."""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        self.recent_files = data
                    else:
                        self.recent_files = []
        except Exception as e:
            print(f"Error loading recent files: {e}")
            self.recent_files = []
            
    def save(self) -> None:
        """Sauvegarde la liste des fichiers récents dans le fichier de configuration."""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.recent_files, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Error saving recent files: {e}")
            
    def get_basename_list(self) -> List[str]:
        """Retourne la liste des noms de fichiers (sans le chemin)."""
        return [os.path.basename(f) for f in self.get_list()]
