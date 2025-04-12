from dataclasses import dataclass
from typing import Dict

@dataclass
class AppConfig:
    """Configuration globale de l'application."""
    max_image_dim_load: int = 3000
    default_ab_switch_interval: int = 500
    min_ab_switch_interval: int = 100
    max_ab_switch_interval: int = 2000
    
    # Couleurs par défaut
    slider_line_color: str = "red"
    background_color: str = "#464646"  # Gris foncé (70, 70, 70)
    
    # Options d'ajustement de taille
    size_adjust_options: Dict[str, str] = None
    
    def __post_init__(self):
        if self.size_adjust_options is None:
            self.size_adjust_options = {
                "resize2to1": "Redimensionner Image 2 → Image 1",
                "resize1to2": "Redimensionner Image 1 → Image 2",
                "resizeboth": "Redimensionner les deux (taille max)",
                "original": "Conserver tailles originales",
                "proportional": "Adapter proportionnellement"
            }
