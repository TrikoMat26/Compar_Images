from typing import Optional, Tuple, Union, Dict, Any
import os
import numpy as np
from PySide6 import QtCore, QtGui

try:
    from PIL import Image, ImageQt, ImageEnhance, ImageFilter
    # Vérifier si Image.Resampling est disponible (Pillow >= 9.0.0)
    try:
        LANCZOS = Image.Resampling.LANCZOS
    except AttributeError:
        # Fallback pour les versions plus anciennes de Pillow
        LANCZOS = Image.LANCZOS
except ImportError:
    print("Warning: Pillow not found. Please install it if needed.")
    Image = ImageQt = ImageEnhance = ImageFilter = None
    LANCZOS = None

class ImageProcessor:
    """Classe utilitaire pour le traitement d'images."""

    @staticmethod
    def pil_to_qpixmap(pil_image: Optional['Image.Image']) -> QtGui.QPixmap:
        """Convertit une image PIL en QPixmap."""
        if pil_image is None:
            return QtGui.QPixmap()
        try:
            if pil_image.mode not in ["RGB", "RGBA"]:
                pil_image = pil_image.convert("RGB")
            if ImageQt:
                qimage = ImageQt.ImageQt(pil_image)
                if isinstance(qimage, QtGui.QImage):
                    return QtGui.QPixmap.fromImage(qimage)
                else:
                    return QtGui.QPixmap(qimage)
            else:
                print("Warning: ImageQt not available, using fallback conversion.")
                if pil_image.mode == "RGB":
                    data = pil_image.tobytes("raw", "RGB")
                    qimg = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGB888)
                elif pil_image.mode == "RGBA":
                    data = pil_image.tobytes("raw", "RGBA")
                    qimg = QtGui.QImage(data, pil_image.width, pil_image.height, QtGui.QImage.Format.Format_RGBA8888)
                else:
                    return QtGui.QPixmap()
                return QtGui.QPixmap.fromImage(qimg)
        except Exception as e:
            print(f"Error converting PIL to QPixmap: {e}")
            return QtGui.QPixmap()

    @staticmethod
    def qpixmap_to_pil(pixmap: QtGui.QPixmap) -> Optional['Image.Image']:
        """Convertit un QPixmap en image PIL."""
        if pixmap.isNull():
            return None
        try:
            qimage = pixmap.toImage()
            if qimage.format() in (QtGui.QImage.Format.Format_RGB32, QtGui.QImage.Format.Format_ARGB32):
                qimage = qimage.convertToFormat(QtGui.QImage.Format.Format_RGBA8888)

            if ImageQt:
                return ImageQt.fromqimage(qimage)
            else:
                # Fallback si ImageQt n'est pas disponible
                size = qimage.size()
                buffer = qimage.bits().asstring(qimage.byteCount())
                if qimage.format() == QtGui.QImage.Format.Format_RGBA8888:
                    return Image.frombuffer("RGBA", (size.width(), size.height()), buffer, "raw", "RGBA", 0, 1)
                elif qimage.format() == QtGui.QImage.Format.Format_RGB888:
                    return Image.frombuffer("RGB", (size.width(), size.height()), buffer, "raw", "RGB", 0, 1)
                else:
                    return None
        except Exception as e:
            print(f"Error converting QPixmap to PIL: {e}")
            return None

    @staticmethod
    def create_difference_image(img1: 'Image.Image', img2: 'Image.Image',
                               amplify: float = 2.0) -> Optional['Image.Image']:
        """Crée une image montrant les différences entre deux images."""
        if img1 is None or img2 is None:
            return None

        try:
            # S'assurer que les images ont la même taille
            if img1.size != img2.size:
                img2 = img2.resize(img1.size, LANCZOS)

            # Convertir en arrays numpy pour le calcul de différence
            arr1 = np.array(img1.convert("RGB"))
            arr2 = np.array(img2.convert("RGB"))

            # Calculer la différence absolue
            diff = np.abs(arr1.astype(np.int16) - arr2.astype(np.int16))

            # Amplifier les différences pour les rendre plus visibles
            diff = np.clip(diff * amplify, 0, 255).astype(np.uint8)

            # Convertir en image PIL
            return Image.fromarray(diff)
        except Exception as e:
            print(f"Error creating difference image: {e}")
            return None

    @staticmethod
    def create_blend_image(img1: 'Image.Image', img2: 'Image.Image',
                          alpha: float = 0.5) -> Optional['Image.Image']:
        """Crée une image combinée avec un niveau de transparence donné."""
        if img1 is None or img2 is None:
            return None

        try:
            # S'assurer que les images ont la même taille
            if img1.size != img2.size:
                img2 = img2.resize(img1.size, Image.Resampling.LANCZOS)

            # Convertir en mode RGB pour le mélange
            im1 = img1.convert("RGB")
            im2 = img2.convert("RGB")

            # Mélanger les images
            return Image.blend(im1, im2, alpha)
        except Exception as e:
            print(f"Error creating blend image: {e}")
            return None

    @staticmethod
    def resize_image(img: 'Image.Image', width: int, height: int,
                    resample: int = LANCZOS) -> 'Image.Image':
        """Redimensionne une image à une taille spécifique."""
        if img is None:
            return None
        return img.resize((width, height), resample)

    @staticmethod
    def resize_to_fit(img: 'Image.Image', max_width: int, max_height: int,
                     preserve_aspect: bool = True) -> 'Image.Image':
        """Redimensionne une image pour qu'elle tienne dans les dimensions maximales."""
        if img is None:
            return None

        width, height = img.size

        if width <= max_width and height <= max_height:
            return img  # Pas besoin de redimensionner

        if preserve_aspect:
            # Calculer le ratio pour préserver les proportions
            ratio = min(max_width / width, max_height / height)
            new_width = int(width * ratio)
            new_height = int(height * ratio)
        else:
            new_width = max_width
            new_height = max_height

        return img.resize((new_width, new_height), LANCZOS)

    @staticmethod
    def adjust_images_for_comparison(img1: 'Image.Image', img2: 'Image.Image',
                                    mode: str = "resize2to1") -> Tuple['Image.Image', 'Image.Image']:
        """Ajuste deux images pour la comparaison selon le mode spécifié."""
        if img1 is None or img2 is None:
            return img1, img2

        # Si les images ont déjà la même taille, pas besoin d'ajuster
        if img1.size == img2.size:
            return img1, img2

        img1_copy = img1.copy()
        img2_copy = img2.copy()

        if mode == "resize2to1":
            # Redimensionner l'image 2 à la taille de l'image 1
            img2_copy = img2_copy.resize(img1_copy.size, LANCZOS)
        elif mode == "resize1to2":
            # Redimensionner l'image 1 à la taille de l'image 2
            img1_copy = img1_copy.resize(img2_copy.size, LANCZOS)
        elif mode == "resizeboth":
            # Redimensionner les deux images à la taille maximale
            max_width = max(img1_copy.width, img2_copy.width)
            max_height = max(img1_copy.height, img2_copy.height)
            new_size = (max_width, max_height)

            if img1_copy.size != new_size:
                img1_copy = img1_copy.resize(new_size, LANCZOS)

            if img2_copy.size != new_size:
                img2_copy = img2_copy.resize(new_size, LANCZOS)
        elif mode == "proportional":
            # Adapter proportionnellement (préserver le ratio)
            w1, h1 = img1_copy.size
            w2, h2 = img2_copy.size

            # Trouver le ratio commun en conservant l'aspect ratio des deux images
            ratio1 = w1 / h1
            ratio2 = w2 / h2

            if ratio1 > ratio2:  # Image 1 plus large proportionnellement
                new_h2 = h2
                new_w2 = int(h2 * ratio1)
                new_h1 = h1
                new_w1 = w1
            else:  # Image 2 plus large proportionnellement
                new_h1 = h1
                new_w1 = int(h1 * ratio2)
                new_h2 = h2
                new_w2 = w2

            if (w1, h1) != (new_w1, new_h1):
                img1_copy = img1_copy.resize((new_w1, new_h1), LANCZOS)

            if (w2, h2) != (new_w2, new_h2):
                img2_copy = img2_copy.resize((new_w2, new_h2), LANCZOS)

        # Pour le mode "original", on ne fait rien car on veut garder les tailles originales

        return img1_copy, img2_copy

    @staticmethod
    def load_image(filepath: str, max_dim: int = 0) -> Optional['Image.Image']:
        """Charge une image à partir d'un fichier avec redimensionnement optionnel."""
        try:
            img = Image.open(filepath)
            img.load()  # Charger l'image complètement

            if max_dim > 0 and max(img.width, img.height) > max_dim:
                # Redimensionner l'image si elle dépasse la dimension maximale
                img.thumbnail((max_dim, max_dim), LANCZOS)

            # Convertir en RGBA si l'image a un canal alpha, sinon en RGB
            return img.convert("RGBA") if 'A' in img.getbands() else img.convert("RGB")
        except Exception as e:
            print(f"Error loading image {filepath}: {e}")
            return None

    @staticmethod
    def get_image_info(img: 'Image.Image') -> Dict[str, Any]:
        """Retourne des informations sur l'image."""
        if img is None:
            return {"valid": False}

        return {
            "valid": True,
            "width": img.width,
            "height": img.height,
            "mode": img.mode,
            "format": img.format,
            "size_bytes": img.width * img.height * len(img.getbands())
        }
