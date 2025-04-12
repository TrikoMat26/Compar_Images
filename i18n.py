from typing import Dict, Optional
from PySide6 import QtCore

class Translator:
    """Gestionnaire de traduction pour l'application."""
    
    def __init__(self):
        self.translator = QtCore.QTranslator()
        self.app = None
        self.current_language = "fr"  # Langue par défaut
        self.available_languages = {
            "fr": "Français",
            "en": "English",
            "es": "Español",
            "de": "Deutsch"
        }
        
    def set_application(self, app) -> None:
        """Définit l'application à traduire."""
        self.app = app
        
    def load_language(self, language_code: str) -> bool:
        """Charge une langue spécifique."""
        if language_code not in self.available_languages:
            return False
            
        # Charger le fichier de traduction
        success = self.translator.load(f"translations/image_comparer_{language_code}")
        
        if success:
            # Installer le traducteur dans l'application
            if self.app:
                self.app.installTranslator(self.translator)
                self.current_language = language_code
                return True
        
        return False
        
    def get_available_languages(self) -> Dict[str, str]:
        """Retourne la liste des langues disponibles."""
        return self.available_languages
        
    def get_current_language(self) -> str:
        """Retourne le code de la langue actuelle."""
        return self.current_language
        
    def translate(self, context: str, text: str) -> str:
        """Traduit un texte dans la langue actuelle."""
        return self.translator.translate(context, text)


# Instance globale du traducteur
translator = Translator()
