import sys
import os
import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Signal, QObject, QThread
from PIL import Image

from .alignment import (
    AlignmentProcess,
    qtransform_to_numpy,
    numpy_to_qtransform,
    create_item_transform_matrix)
from .stitcher import StitchingProcess
#---------------------------------------------------------------------------
# 1)  On ré-utilise le composant **complet** déjà codé dans image_compare.py
# ---------------------------------------------------------------------------
from image_compare import MaskedOrFullPixmapItem   # version “full” avec rotation + scale



class WorkerSignals(QObject):
    """Defines the signals available from a running worker thread."""
    finished = Signal()
    error = Signal(str)
    progress = Signal(int)
    log = Signal(str)
    auto_align_complete = Signal(list, tuple, tuple, object) # cumulative_homographies, canvas_size, canvas_offset
    stitch_complete = Signal(Image.Image) # final PIL image

class AutoAlignWorker(QThread):
    """Worker thread for running the automatic alignment process."""
    def __init__(self, image_paths):
        super().__init__()
        self.image_paths = image_paths
        self.signals = WorkerSignals()
        self._is_canceled = False

    def run(self):
        try:
            alignment_process = AlignmentProcess(
                progress_callback=self.signals.progress.emit,
                log_callback=self.signals.log.emit
            )
            alignment_process.load_images(self.image_paths)
            if self._is_canceled: return

            success = alignment_process.auto_align()
            if self._is_canceled: return

            if success:
                cumulative_homographies = alignment_process.get_cumulative_homographies()
                canvas_size, canvas_offset = alignment_process.get_canvas_info()
                self.alignment_process = alignment_process
                self.signals.auto_align_complete.emit(cumulative_homographies, canvas_size, canvas_offset, alignment_process)
            else:
                self.signals.error.emit("Automatic alignment failed.")

        except Exception as e:
            self.signals.error.emit(f"An error occurred during alignment: {e}")
        finally:
            self.signals.finished.emit()

    def cancel(self):
        self._is_canceled = True
        self.wait() # Wait for the thread to finish

class StitchingWorker(QThread):
    """Worker thread for running the stitching process."""
    def __init__(self, images_pil, cumulative_homographies, canvas_size, canvas_offset, resolution_factor):
        super().__init__()
        self.images_pil = images_pil
        self.cumulative_homographies = cumulative_homographies
        self.canvas_size = canvas_size
        self.canvas_offset = canvas_offset
        self.resolution_factor = resolution_factor
        self.signals = WorkerSignals()
        self._is_canceled = False

    def run(self):
        try:
            stitching_process = StitchingProcess(
                progress_callback=self.signals.progress.emit,
                log_callback=self.signals.log.emit
            )
            final_mosaic_pil = stitching_process.create_mosaic(
                self.images_pil,
                self.cumulative_homographies,
                self.canvas_size,
                self.canvas_offset,
                self.resolution_factor
            )
            if self._is_canceled: return

            if final_mosaic_pil:
                self.signals.stitch_complete.emit(final_mosaic_pil)
            else:
                self.signals.error.emit("Mosaic stitching failed.")

        except Exception as e:
            self.signals.error.emit(f"An error occurred during stitching: {e}")
        finally:
            self.signals.finished.emit()

    def cancel(self):
        self._is_canceled = True
        self.wait() # Wait for the thread to finish


class PCBMosaicDock(QtWidgets.QDockWidget):
    """
    Dock widget for the PCB Mosaic feature.
    Guides the user through loading, aligning, refining, and stitching images.
    """
    # Signal to request switching the main view mode
    request_view_mode_change = Signal(str) # "side_by_side", "slider", "ab_switch", "mosaic_refine"
    # Signal to request updating items in the main combined view
    request_combined_view_update = Signal(list) # List of (item_id, pixmap, pos, rotation, scale)

    def __init__(self, main_window):
        """
        Args:
            main_window (ImageComparerApp): Reference to the main application window.
        """
        super().__init__("PCB Mosaic", main_window)
        self.main_window = main_window # Store reference to main window

        self.setAllowedAreas(QtCore.Qt.LeftDockWidgetArea | QtCore.Qt.RightDockWidgetArea)
        self.setFeatures(QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetMovable | QtWidgets.QDockWidget.DockWidgetFeature.DockWidgetClosable)

        # State variables
        self.image_paths = []
        self.images_pil = [] # Original PIL images loaded
        self.alignment_process = None
        self.stitching_process = None
        self.cumulative_homographies = [] # H_0,i matrices
        self.canvas_size = (0, 0)
        self.canvas_offset = (0.0, 0.0)
        self.final_mosaic_pil = None

        # Manual refinement state
        self._refine_pair_index = -1 # Index of the pair currently being refined (0 for 0-1, 1 for 1-2, etc.)
        self._refine_item1 = None # MaskedOrFullPixmapItem for the first image in the pair
        self._refine_item2 = None # MaskedOrFullPixmapItem for the second image in the pair
        self._initial_refine_item2_transform = None # Store initial transform of item2 for calculating relative change

        # Workers
        self._align_worker = None
        self._stitch_worker = None

        self.setup_ui()
        self.update_ui_state("initial") # Set initial UI state

    def setup_ui(self):
        """Sets up the user interface for the dock widget."""
        container = QtWidgets.QWidget()
        self.setWidget(container)
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(5)

        # --- Step 1: Load Images ---
        load_group = QtWidgets.QGroupBox("1. Charger les images")
        load_layout = QtWidgets.QVBoxLayout(load_group)

        self.list_images = QtWidgets.QListWidget()
        self.list_images.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.ExtendedSelection)
        load_layout.addWidget(self.list_images)

        btn_select_images = QtWidgets.QPushButton("Sélectionner des images...")
        btn_select_images.clicked.connect(self.select_images)
        load_layout.addWidget(btn_select_images)

        layout.addWidget(load_group)

        # --- Step 2: Auto Align ---
        align_group = QtWidgets.QGroupBox("2. Recalage automatique")
        align_layout = QtWidgets.QVBoxLayout(align_group)

        self.btn_auto_align = QtWidgets.QPushButton("Lancer le recalage automatique")
        self.btn_auto_align.clicked.connect(self.start_auto_align)
        align_layout.addWidget(self.btn_auto_align)

        layout.addWidget(align_group)

        # --- Step 3: Manual Refinement (Optional) ---
        refine_group = QtWidgets.QGroupBox("3. Affinage manuel (Optionnel)")
        refine_layout = QtWidgets.QVBoxLayout(refine_group)

        refine_pair_layout = QtWidgets.QHBoxLayout()
        refine_pair_layout.addWidget(QtWidgets.QLabel("Affiner la paire:"))
        self.combo_refine_pair = QtWidgets.QComboBox()
        self.combo_refine_pair.currentIndexChanged.connect(self.on_refine_pair_selected)
        refine_pair_layout.addWidget(self.combo_refine_pair)
        refine_layout.addLayout(refine_pair_layout)

        # Info label for manual controls
        shortcuts_info = QtWidgets.QLabel(
            "Utilisez la vue principale pour affiner:\n"
            "• Clic+Drag : Translation\n"
            "• Ctrl+Clic+Drag : Rotation\n"
            "• Alt+Clic+Drag : Échelle"
        )
        shortcuts_info.setStyleSheet("margin-left: 5px; font-size: 9pt;")
        refine_layout.addWidget(shortcuts_info)

        # Display current manual transformation values (Optional but helpful)
        values_layout = QtWidgets.QGridLayout()
        values_layout.addWidget(QtWidgets.QLabel("Image 1 (Fixe):"), 0, 0)
        values_layout.addWidget(QtWidgets.QLabel("Image 2 (Mobile):"), 1, 0)
        self.lbl_refine_img1_info = QtWidgets.QLabel("Pos: (0,0), R: 0°, S: 100%")
        self.lbl_refine_img2_info = QtWidgets.QLabel("Pos: (0,0), R: 0°, S: 100%")
        values_layout.addWidget(self.lbl_refine_img1_info, 0, 1)
        values_layout.addWidget(self.lbl_refine_img2_info, 1, 1)
        refine_layout.addLayout(values_layout)

        self.btn_reset_refinement = QtWidgets.QPushButton("Réinitialiser affinage paire")
        self.btn_reset_refinement.clicked.connect(self.reset_manual_refinement)
        refine_layout.addWidget(self.btn_reset_refinement)

        layout.addWidget(refine_group)

        # --- Step 4: Generate and Export Mosaic ---
        export_group = QtWidgets.QGroupBox("4. Générer et Exporter")
        export_layout = QtWidgets.QVBoxLayout(export_group)

        self.btn_generate_mosaic = QtWidgets.QPushButton("Générer la mosaïque")
        self.btn_generate_mosaic.clicked.connect(self.start_stitching)
        export_layout.addWidget(self.btn_generate_mosaic)

        resolution_layout = QtWidgets.QHBoxLayout()
        resolution_layout.addWidget(QtWidgets.QLabel("Résolution:"))
        self.combo_resolution = QtWidgets.QComboBox()
        self.combo_resolution.addItem("Originale (1x)", 1.0)
        self.combo_resolution.addItem("Moitié (0.5x)", 0.5)
        self.combo_resolution.addItem("Double (2x)", 2.0)
        # Add custom resolution option later if needed
        resolution_layout.addWidget(self.combo_resolution)
        export_layout.addLayout(resolution_layout)

        quality_layout = QtWidgets.QHBoxLayout()
        quality_layout.addWidget(QtWidgets.QLabel("Qualité JPEG:"))
        self.slider_quality = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
        self.slider_quality.setRange(1, 100)
        self.slider_quality.setValue(90)
        self.lbl_quality_value = QtWidgets.QLabel("90")
        self.slider_quality.valueChanged.connect(lambda v: self.lbl_quality_value.setText(str(v)))
        quality_layout.addWidget(self.slider_quality)
        quality_layout.addWidget(self.lbl_quality_value)
        export_layout.addLayout(quality_layout)


        self.btn_save_mosaic = QtWidgets.QPushButton("Enregistrer la mosaïque...")
        self.btn_save_mosaic.clicked.connect(self.save_mosaic)
        export_layout.addWidget(self.btn_save_mosaic)

        layout.addWidget(export_group)

        # --- Progress and Log ---
        self.progress_bar = QtWidgets.QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        layout.addWidget(self.progress_bar)

        self.log_output = QtWidgets.QTextEdit()
        self.log_output.setReadOnly(True)
        self.log_output.setFixedHeight(100) # Limit height
        layout.addWidget(self.log_output)

        layout.addStretch(1) # Push everything to the top

    def update_ui_state(self, state):
        """Manages enabling/disabling UI elements based on the current state."""
        # States: "initial", "images_loaded", "aligned", "refining", "mosaic_generated"
        self.btn_auto_align.setEnabled(state == "images_loaded")
        self.combo_refine_pair.setEnabled(state in ["aligned", "refining"])
        self.btn_reset_refinement.setEnabled(state in ["aligned", "refining"])
        self.btn_generate_mosaic.setEnabled(state in ["aligned", "refining"])
        self.combo_resolution.setEnabled(state == "mosaic_generated")
        self.slider_quality.setEnabled(state == "mosaic_generated")
        self.btn_save_mosaic.setEnabled(state == "mosaic_generated")

        # Hide/show refinement info based on state
        self.lbl_refine_img1_info.setVisible(state in ["aligned", "refining"])
        self.lbl_refine_img2_info.setVisible(state in ["aligned", "refining"])

        # Update group box titles/appearance (optional)
        # self.load_group.setTitle("1. Charger les images" + (" ✓" if state != "initial" else ""))
        # etc.

    def log_message(self, message):
        """Appends a message to the log output."""
        self.log_output.append(message)
        # Auto-scroll to the bottom
        self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

    def update_progress(self, value):
        """Updates the progress bar."""
        self.progress_bar.setValue(value)

    def select_images(self):
        """Opens a file dialog to select images."""
        filepaths, _ = QtWidgets.QFileDialog.getOpenFileNames(
            self, "Sélectionner les images pour la mosaïque", "",
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.tif *.tiff);;Tous les fichiers (*)"
        )
        if filepaths:
            if 2 <= len(filepaths) <= 10:
                self.image_paths = filepaths
                self.list_images.clear()
                for path in filepaths:
                    self.list_images.addItem(os.path.basename(path))
                self.log_message(f"Selected {len(filepaths)} images.")
                self.update_ui_state("images_loaded")
                self.images_pil = [] # Clear previous PIL images
                self.cumulative_homographies = []
                self.canvas_size = (0, 0)
                self.canvas_offset = (0.0, 0.0)
                self.final_mosaic_pil = None
                self.combo_refine_pair.clear() # Clear refinement pairs
            else:
                QtWidgets.QMessageBox.warning(self, "Sélection invalide", "Veuillez sélectionner entre 2 et 10 images.")
                self.update_ui_state("initial")

    def start_auto_align(self):
        """Starts the automatic alignment process in a worker thread."""
        if not self.image_paths:
            self.log_message("No images selected for alignment.")
            return

        self.log_message("Starting auto alignment worker...")
        self.update_ui_state("aligning") # Indicate busy state
        self.progress_bar.setValue(0)
        self.log_output.clear() # Clear log for new process

        # Load PIL images in the main thread before starting the worker
        # Or load them inside the worker if they are large and blocking
        # Let's load in the worker to keep the UI responsive during loading
        self.images_pil = [] # Will be populated by the worker

        self._align_worker = AutoAlignWorker(self.image_paths)
        self._align_worker.signals.progress.connect(self.update_progress)
        self._align_worker.signals.log.connect(self.log_message)
        self._align_worker.signals.error.connect(self.on_auto_align_error)
        self._align_worker.signals.auto_align_complete.connect(self.on_auto_align_complete)
        self._align_worker.signals.finished.connect(self.on_auto_align_finished)
        self._align_worker.start()

    def on_auto_align_error(self, message):
        """Handles errors from the auto alignment worker."""
        self.log_message(f"ERROR: {message}")
        QtWidgets.QMessageBox.critical(self, "Erreur de recalage", message)
        self.update_ui_state("images_loaded") # Allow retrying alignment

    def on_auto_align_complete(self, cumulative_homographies, canvas_size, canvas_offset, alignment_process):
        """Handles successful completion of auto alignment."""
        self.log_message("Auto alignment successful.")
        self.cumulative_homographies = cumulative_homographies
        self.canvas_size = canvas_size
        self.canvas_offset = canvas_offset
        # mémoriser l'instance pour la suite (affinage, export)
        self.alignment_process = alignment_process

        # Store loaded PIL images from the worker
        # Need to modify worker to return images or load them here
        # Let's load them here for simplicity, assuming they fit in memory
        self.images_pil = [Image.open(p).convert("RGB") for p in self.image_paths]

        # Populate refinement pair combo box
        self.combo_refine_pair.clear()
        for i in range(len(self.images_pil) - 1):
            self.combo_refine_pair.addItem(f"Paire {i+1}-{i+2}", i) # Store pair index as data

        self.update_ui_state("aligned")
        self.log_message("Ready for manual refinement or mosaic generation.")

        # Automatically select the first pair to display the aligned images
        if self.combo_refine_pair.count() > 0:
            self.log_message("Displaying first image pair...")
            # This will trigger on_refine_pair_selected which will display the images
            self.combo_refine_pair.setCurrentIndex(0)

    def on_auto_align_finished(self):
        """Cleans up after the auto alignment worker finishes."""
        self._align_worker = None
        self.progress_bar.setValue(0) # Reset progress bar

    def on_refine_pair_selected(self, index):
        """Handles selection of a pair for manual refinement."""
        if index < 0:
            self._refine_pair_index = -1
            self.request_view_mode_change.emit("side_by_side") # Go back to side-by-side or default
            self.lbl_refine_img1_info.setText("Pos: (0,0), R: 0°, S: 100%")
            self.lbl_refine_img2_info.setText("Pos: (0,0), R: 0°, S: 100%")
            return

        self._refine_pair_index = self.combo_refine_pair.itemData(index)
        self.log_message(f"Selected pair {self._refine_pair_index+1}-{self._refine_pair_index+2} for refinement.")

        # Switch main view to "mosaic_refine" mode
        self.request_view_mode_change.emit("mosaic_refine")

        # Use a timer with a longer delay to ensure the mode change is fully processed
        self.log_message("Scheduling refinement view setup with delay...")
        QtCore.QTimer.singleShot(500, lambda: self._complete_refine_pair_setup(self._refine_pair_index))

    def _complete_refine_pair_setup(self, pair_index):
        """Completes the setup after the mode change has been processed."""
        # Prepare items in the combined view
        try:
            self.setup_refinement_view(pair_index)
            self.update_ui_state("refining")
            self.log_message("Refinement view setup complete.")
        except Exception as e:
            self.log_message(f"Error in refinement view setup: {e}")
            self.log_message("Attempting fallback display method...")
            self._fallback_display_images(pair_index)

    def _fallback_display_images(self, pair_index):
        """Fallback method to display images side by side if the normal setup fails."""
        if pair_index < 0 or pair_index >= len(self.images_pil) - 1:
            self.log_message("Error: Invalid pair index for fallback display.")
            return

        img1_index = pair_index
        img2_index = pair_index + 1

        try:
            # Get the images
            img1_pil = self.images_pil[img1_index]
            img2_pil = self.images_pil[img2_index]

            # Convert to QPixmaps
            img1_pixmap = self.main_window.pil_to_qpixmap(img1_pil)
            img2_pixmap = self.main_window.pil_to_qpixmap(img2_pil)

            # Get the scene
            combined_view = self.main_window.view_combined
            scene = combined_view.scene()

            # Clear any existing items
            scene.clear()

            # Create new items
            self._refine_item1 = MaskedOrFullPixmapItem(controller=self, item_id=1)
            self._refine_item2 = MaskedOrFullPixmapItem(controller=self, item_id=2)

            # Set pixmaps
            self._refine_item1.setPixmap(img1_pixmap)
            self._refine_item2.setPixmap(img2_pixmap)

            # Position side by side
            self._refine_item1.setPos(0, 0)
            self._refine_item2.setPos(img1_pixmap.width() + 20, 0)  # 20 pixels gap

            # Add to scene
            scene.addItem(self._refine_item1)
            scene.addItem(self._refine_item2)

            # Set scene rect
            scene_rect = self._refine_item1.sceneBoundingRect().united(self._refine_item2.sceneBoundingRect())
            scene.setSceneRect(scene_rect)

            # Fit view
            combined_view.fitInView(scene_rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)

            # Force update
            combined_view.viewport().update()

            # Set UI state
            self.update_ui_state("refining")
            self.log_message("Fallback display method successful.")
        except Exception as e:
            self.log_message(f"Error in fallback display method: {e}")

    def setup_refinement_view(self, pair_index: int):
        """
        Sets up the main combined view to show the selected pair for refinement.
        Uses MaskedOrFullPixmapItems.
        """
        self.log_message(f"Setting up refinement view for pair index {pair_index}...")

        if pair_index < 0 or pair_index >= len(self.images_pil) - 1:
            self.log_message("Error setting up refinement view: Invalid pair index.")
            return

        img1_index = pair_index
        img2_index = pair_index + 1

        self.log_message(f"Using images {img1_index+1} and {img2_index+1}")

        # Vérifier que les images sont bien chargées
        if not self.images_pil or len(self.images_pil) <= img2_index:
            self.log_message(f"Error: Images not loaded or index out of range. Images loaded: {len(self.images_pil)}")
            return

        img1_pil = self.images_pil[img1_index]
        img2_pil = self.images_pil[img2_index]

        self.log_message(f"Image 1 size: {img1_pil.width}x{img1_pil.height}, Image 2 size: {img2_pil.width}x{img2_pil.height}")

        # Convert PIL images to QPixmaps
        img1_pixmap = self.main_window.pil_to_qpixmap(img1_pil)
        img2_pixmap = self.main_window.pil_to_qpixmap(img2_pil)

        if img1_pixmap.isNull() or img2_pixmap.isNull():
            self.log_message("Error: Failed to convert PIL images to QPixmaps")
            return

        self.log_message(f"QPixmap 1 size: {img1_pixmap.width()}x{img1_pixmap.height()}, QPixmap 2 size: {img2_pixmap.width()}x{img2_pixmap.height()}")

        # Get the combined view and its scene
        combined_view = self.main_window.view_combined
        if not combined_view:
            self.log_message("Error: Combined view not available")
            return

        scene = combined_view.scene()
        if not scene:
            self.log_message("Error: Scene not available")
            return

        self.log_message(f"Scene rect: {scene.sceneRect().x()},{scene.sceneRect().y()} {scene.sceneRect().width()}x{scene.sceneRect().height()}")

        # Clear previous refinement items if they exist
        if self._refine_item1:
            scene.removeItem(self._refine_item1)
            self._refine_item1 = None
        if self._refine_item2:
            scene.removeItem(self._refine_item2)
            self._refine_item2 = None

        self.log_message("Previous refinement items cleared")

        # Create new items for refinement
        # Pass self as controller so items call back to this dock
        self._refine_item1 = MaskedOrFullPixmapItem(controller=self, item_id=1)
        self._refine_item2 = MaskedOrFullPixmapItem(controller=self, item_id=2)

        self.log_message("New refinement items created")

        self._refine_item1.setPixmap(img1_pixmap)
        self._refine_item2.setPixmap(img2_pixmap)

        self.log_message("Pixmaps set on refinement items")

        # Add items to the scene
        scene.addItem(self._refine_item1)
        scene.addItem(self._refine_item2)

        self.log_message("Items added to scene")

        # Calculate initial positions/transforms based on cumulative homographies
        self.log_message("Calculating transforms based on homographies...")

        # Vérifier que les homographies sont disponibles
        if not self.cumulative_homographies or len(self.cumulative_homographies) <= img2_index:
            self.log_message(f"Error: Homographies not available or index out of range. Homographies: {len(self.cumulative_homographies)}")
            return

        # H_0,i maps from img_i original coords to img_0 origin canvas coords.
        # We need to map from img_i original coords to the *scene* coords.
        # The scene origin (0,0) corresponds to the canvas origin (canvas_offset_x, canvas_offset_y)
        # in the img_0 origin system.
        # So, the transformation from img_i original coords to scene coords is:
        # M_scene_i = T(canvas_offset_x, canvas_offset_y) * H_0,i
        # The QGraphicsItem transform maps from item local (0,0) to scene.
        # If the item pixmap is the original image, the item transform *is* M_scene_i.

        H_0_i = self.cumulative_homographies[img1_index]
        H_0_iplus1 = self.cumulative_homographies[img2_index]

        self.log_message(f"Canvas offset: {self.canvas_offset}")

        offset_matrix = np.array([[1, 0, self.canvas_offset[0]],
                                  [0, 1, self.canvas_offset[1]],
                                  [0, 0, 1]], dtype=np.float64)

        M_scene_i = np.dot(offset_matrix, H_0_i)
        M_scene_iplus1 = np.dot(offset_matrix, H_0_iplus1)

        self.log_message(f"M_scene_i shape: {M_scene_i.shape}")
        self.log_message(f"M_scene_iplus1 shape: {M_scene_iplus1.shape}")

        # Convert these matrices to QTransforms and apply to items
        try:
            transform1 = numpy_to_qtransform(M_scene_i)
            transform2 = numpy_to_qtransform(M_scene_iplus1)
            self.log_message("Matrices converted to QTransforms")
        except Exception as e:
            self.log_message(f"Error converting matrices to QTransforms: {e}")
            return

        # QGraphicsItem applies transform *after* position.
        # So, set position to (0,0) and apply the full transform using setTransform.
        # However, our custom items handle position, rotation, scale separately.
        # Let's calculate the position, rotation, and scale from the matrix.
        # This is non-trivial for a full homography.
        # Let's simplify: For manual refinement, we only allow affine transformations (translation, rotation, scale).
        # The initial display should reflect the *full* homography, but manual edits are affine.
        # A better approach: Display the images warped by their cumulative homographies onto a temporary canvas,
        # then display *that* temporary canvas in the QGraphicsView. But this loses the item interaction.

        # Let's try setting the item's transform directly using setTransform, and see if drag/rotate/scale still works.
        # The custom items override mouse events and call controller methods.
        # We need to modify the custom items to work with setTransform, or calculate pos/rot/scale from the matrix.
        # Calculating pos/rot/scale from a general affine matrix is possible but complex.
        # Let's assume for manual refinement, we only care about relative affine adjustments.
        # Display img_i at origin (or centered), and img_i+1 relative to it using H_i,i+1.
        # H_i,i+1 = H_0,i.I * H_0,i+1

        # We don't actually need H_i_iplus1 for display, so let's skip this calculation
        # It was just for documentation purposes
        self.log_message("Using M_scene_i and M_scene_iplus1 for display")

        # Display img_i at (0,0) in the scene with identity transform (or scaled to fit view)
        # Display img_i+1 at (0,0) with transform corresponding to H_i,i+1
        # This doesn't use the canvas offset correctly for display.

        # Let's use the calculated scene transforms M_scene_i and M_scene_iplus1.
        # Set item positions to (0,0) and apply transforms directly.
        self.log_message("Setting item positions and transforms...")
        self._refine_item1.setPos(0, 0)
        self._refine_item2.setPos(0, 0)

        try:
            self._refine_item1.setTransform(transform1)
            self._refine_item2.setTransform(transform2)
            self.log_message("Transforms applied to items")
        except Exception as e:
            self.log_message(f"Error applying transforms to items: {e}")
            return

        # Disable drag/transform on item1, enable on item2
        self._refine_item1.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self._refine_item1.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self._refine_item1.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, False)

        self._refine_item2.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsMovable, True)
        self._refine_item2.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, True)
        self._refine_item2.setFlag(QtWidgets.QGraphicsItem.GraphicsItemFlag.ItemIsFocusable, True)

        # Store the initial transform of item2 for calculating relative changes
        self._initial_refine_item2_transform = self._refine_item2.transform()

        # Set opacity for blending view
        self._refine_item1.setOpacity(0.5)
        self._refine_item2.setOpacity(0.5)

        # Ensure items are visible
        self._refine_item1.setVisible(True)
        self._refine_item2.setVisible(True)

        # Adjust scene rect to encompass both items
        try:
            # Check if the transforms resulted in reasonable coordinates
            rect1 = self._refine_item1.sceneBoundingRect()
            rect2 = self._refine_item2.sceneBoundingRect()

            self.log_message(f"Item1 rect: {rect1.x()},{rect1.y()} {rect1.width()}x{rect1.height()}")
            self.log_message(f"Item2 rect: {rect2.x()},{rect2.y()} {rect2.width()}x{rect2.height()}")

            # Check if the coordinates are extremely large
            max_coord = 1000000  # 1 million pixels is already very large
            if (abs(rect1.x()) > max_coord or abs(rect1.y()) > max_coord or
                abs(rect2.x()) > max_coord or abs(rect2.y()) > max_coord or
                rect1.width() > max_coord or rect1.height() > max_coord or
                rect2.width() > max_coord or rect2.height() > max_coord):

                self.log_message("WARNING: Extremely large coordinates detected. Resetting transforms.")

                # Reset transforms to identity and position items manually
                self._refine_item1.setTransform(QtGui.QTransform())
                self._refine_item2.setTransform(QtGui.QTransform())

                # Position items side by side
                img1_width = self._refine_item1.pixmap().width()
                self._refine_item1.setPos(0, 0)
                self._refine_item2.setPos(img1_width + 20, 0)  # 20 pixels gap

                # Recalculate scene rect
                rect1 = self._refine_item1.sceneBoundingRect()
                rect2 = self._refine_item2.sceneBoundingRect()

                self.log_message(f"Reset Item1 rect: {rect1.x()},{rect1.y()} {rect1.width()}x{rect1.height()}")
                self.log_message(f"Reset Item2 rect: {rect2.x()},{rect2.y()} {rect2.width()}x{rect2.height()}")

            scene_rect = rect1.united(rect2)
            scene.setSceneRect(scene_rect)
            self.log_message(f"Scene rect adjusted: {scene_rect.x()},{scene_rect.y()} {scene_rect.width()}x{scene_rect.height()}")

            # Fit view to the scene rect
            combined_view.fitInView(scene_rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
            self.log_message("View fitted to scene rect")

            # Force update
            combined_view.viewport().update()
            self.log_message("Viewport updated")
        except Exception as e:
            self.log_message(f"Error adjusting scene rect: {e}")

        # Update info labels
        try:
            self.update_refinement_info_labels()
            self.log_message("Info labels updated")
        except Exception as e:
            self.log_message(f"Error updating info labels: {e}")

    def update_refinement_info_labels(self):
        """Updates the labels showing current transformation info for refinement items."""
        if self._refine_item1 and self._refine_item2:
            # Getting rotation/scale from a general QTransform is not straightforward.
            # Let's just show position for now, or calculate approximate affine components.
            # For simplicity, let's assume the user only applies translation, rotation, scale
            # via the mouse controls, and we track those specific changes.
            # The MaskedOrFullPixmapItem already stores _rotation_angle and _scale_factor.
            # It doesn't store _position directly if setTransform is used.
            # We need to modify MaskedOrFullPixmapItem to work with setTransform and still track these.

            # Let's assume the custom items' mouse events *modify* their internal pos, rotation, scale
            # and then call setTransform based on those. This is how the original code works.
            # So, we need to set the *initial* pos, rotation, scale based on the homography.
            # This is the hard part: decomposing a homography (or even affine matrix) into pos, rot, scale.

            # Let's simplify: When in refinement mode, the items *only* use pos, rotation, scale,
            # and we calculate the corresponding affine matrix from these properties.
            # The initial state needs to be set by calculating the best affine approximation
            # of the cumulative homography.

            # For now, let's just show the item's scene position and its internal rotation/scale properties
            # (which are only updated by mouse events in the current item implementation).
            # This means the initial display won't reflect the full homography's rotation/scale, only translation.
            # This is a limitation of reusing the current item structure directly with homographies.

            # Alternative: Modify MaskedOrFullPixmapItem to accept and apply a full QTransform,
            # but still allow mouse events to *add* affine transformations on top,
            # and report the *total* transform or the *relative* affine transform applied by the user.

            # Let's assume the simplest interpretation for now: the custom items' mouse events
            # modify their internal _rotation_angle, _scale_factor, and _pos (via move_pixmap_item).
            # We need to initialize these properties based on the homography.
            # Calculating initial pos/rot/scale from M_scene is complex.
            # Let's just set initial pos to (0,0) and rot/scale to default (0, 1.0) for now,
            # and the user refines from there. This is not ideal as it loses the auto-alignment result visually.

            # Let's try to extract approximate affine components for initial display:
            # Extract translation: tx = M[0,2], ty = M[1,2]
            # Extract scale and rotation: Use SVD or polar decomposition on the 2x2 part M[0:2, 0:2]
            # For simplicity, let's just use the translation part for position, and assume rotation/scale are 0/1 initially.
            # This is a known simplification/limitation.

            # Let's use the item's actual scene position and its internal rotation/scale properties
            # (which are updated by mouse events).
            pos1 = self._refine_item1.pos()
            rot1 = self._refine_item1.get_rotation()
            scale1 = self._refine_item1.get_scale_factor()

            pos2 = self._refine_item2.pos()
            rot2 = self._refine_item2.get_rotation()
            scale2 = self._refine_item2.get_scale_factor()

            self.lbl_refine_img1_info.setText(f"Pos: ({pos1.x():.0f},{pos1.y():.0f}), R: {rot1:.0f}°, S: {scale1*100:.0f}%")
            self.lbl_refine_img2_info.setText(f"Pos: ({pos2.x():.0f},{pos2.y():.0f}), R: {rot2:.0f}°, S: {scale2*100:.0f}%")

    # Implement controller methods expected by MaskedOrFullPixmapItem
    def move_pixmap_item(self, item_id: int, dx: float, dy: float):
        """Called by DraggablePixmapItem/MaskedOrFullPixmapItem when dragged."""
        if self._refine_pair_index == -1 or self._refine_item1 is None or self._refine_item2 is None:
            return # Not in refinement mode

        # Only item2 is movable
        if item_id == 2:
            current_pos = self._refine_item2.pos()
            new_pos = QtCore.QPointF(current_pos.x() + dx, current_pos.y() + dy)
            self._refine_item2.setPos(new_pos)
            self.update_homography_from_item_transform()
            self.update_refinement_info_labels()

    def on_rotation_changed(self, item_id: int, angle: float):
        """Called by MaskedOrFullPixmapItem when rotation changes (via Ctrl+Drag)."""
        if self._refine_pair_index == -1 or self._refine_item1 is None or self._refine_item2 is None:
            return # Not in refinement mode

        # Only item2 is rotatable via mouse
        if item_id == 2:
            self._refine_item2.set_rotation(angle) # Update item's internal state and trigger repaint
            self.update_homography_from_item_transform()
            self.update_refinement_info_labels()

    def on_scale_changed(self, item_id: int, scale: float):
        """Called by MaskedOrFullPixmapItem when scale changes (via Alt+Drag)."""
        if self._refine_pair_index == -1 or self._refine_item1 is None or self._refine_item2 is None:
            return # Not in refinement mode

        # Only item2 is scalable via mouse
        if item_id == 2:
            self._refine_item2.set_scale_factor(scale) # Update item's internal state and trigger repaint
            self.update_homography_from_item_transform()
            self.update_refinement_info_labels()

    def reset_manual_refinement(self):
        """Resets the manual refinement for the current pair to the auto-aligned state."""
        if self._refine_pair_index == -1 or self._refine_item1 is None or self._refine_item2 is None:
            return # Not in refinement mode

        self.log_message(f"Resetting refinement for pair {self._refine_pair_index+1}-{self._refine_pair_index+2}")

        # Re-setup the refinement view with the original auto-aligned transforms
        self.setup_refinement_view(self._refine_pair_index)

    def start_stitching(self):
        """Starts the stitching process in a worker thread."""
        if not self.images_pil or not self.cumulative_homographies or self.canvas_size[0] <= 0:
            self.log_message("Alignment not complete or no images loaded.")
            return

        self.log_message("Starting stitching worker...")
        self.update_ui_state("stitching") # Indicate busy state
        self.progress_bar.setValue(0)
        # Keep previous log messages

        resolution_factor = self.combo_resolution.currentData()

        self._stitch_worker = StitchingWorker(
            self.images_pil,
            self.cumulative_homographies,
            self.canvas_size,
            self.canvas_offset,
            resolution_factor
        )
        self._stitch_worker.signals.progress.connect(self.update_progress)
        self._stitch_worker.signals.log.connect(self.log_message)
        self._stitch_worker.signals.error.connect(self.on_stitch_error)
        self._stitch_worker.signals.stitch_complete.connect(self.on_stitch_complete)
        self._stitch_worker.signals.finished.connect(self.on_stitch_finished)
        self._stitch_worker.start()

    def on_stitch_error(self, message):
        """Handles errors from the stitching worker."""
        self.log_message(f"ERROR: {message}")
        QtWidgets.QMessageBox.critical(self, "Erreur de mosaïque", message)
        self.update_ui_state("aligned") # Allow retrying stitching

    def on_stitch_complete(self, mosaic_pil):
        """Handles successful completion of stitching."""
        self.log_message("Stitching successful.")
        self.final_mosaic_pil = mosaic_pil
        self.update_ui_state("mosaic_generated")

    def on_stitch_finished(self):
        """Cleans up after the stitching worker finishes."""
        self._stitch_worker = None

    def save_mosaic(self):
        """Saves the final mosaic image to a file."""
        if self.final_mosaic_pil is None:
            self.log_message("No mosaic to save.")
            return

        file_path, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Enregistrer la mosaïque", "",
            "Images (*.png *.jpg *.jpeg *.tif *.tiff);;Tous les fichiers (*)"
        )

        if file_path:
            try:
                # Determine quality for JPEG
                quality = self.slider_quality.value()

                # Determine file format based on extension
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ['.jpg', '.jpeg']:
                    self.final_mosaic_pil.save(file_path, quality=quality)
                    self.log_message(f"Mosaic saved as JPEG with quality {quality} to {file_path}")
                else:
                    self.final_mosaic_pil.save(file_path)
                    self.log_message(f"Mosaic saved to {file_path}")

                # Show success message
                QtWidgets.QMessageBox.information(
                    self, "Mosaïque enregistrée",
                    f"La mosaïque a été enregistrée avec succès dans :\n{file_path}"
                )
            except Exception as e:
                self.log_message(f"Error saving mosaic: {e}")
                QtWidgets.QMessageBox.critical(
                    self, "Erreur d'enregistrement",
                    f"Erreur lors de l'enregistrement de la mosaïque :\n{str(e)}"
                )

    def update_homography_from_item_transform(self):
        """
        Calculates the new relative homography H_i+1,i based on the current
        transforms of _refine_item1 and _refine_item2 in the scene,
        and updates the AlignmentProcess.
        """
        if self._refine_pair_index == -1 or self._refine_item1 is None or self._refine_item2 is None or self.alignment_process is None:
            return

        # Get the current scene transforms of the two items
        T1_scene = self._refine_item1.transform()
        T2_scene = self._refine_item2.transform()

        # Convert QTransforms to numpy matrices
        M1_scene = qtransform_to_numpy(T1_scene)
        M2_scene = qtransform_to_numpy(T2_scene)

        # The transformation from item2's local coordinates to item1's local coordinates
        # in the scene is M1_scene.I * M2_scene.
        # This matrix should represent the new relative homography H'_{i+1, i}.
        # We need to be careful about the coordinate systems.
        # The item transform maps from item local (0,0 at top-left, size=pixmap size) to scene.
        # The homography maps from original image (0,0 at top-left, size=original size) to canvas.
        # If the item pixmap *is* the original image, then item local == original image coords.
        # If the scene origin == canvas origin, then scene coords == canvas coords.
        # In setup_refinement_view, we set item pos to (0,0) and applied the full M_scene matrix.
        # So, T1_scene corresponds to M_scene_i, and T2_scene corresponds to M_scene_iplus1.
        # M_scene_i = T(offset) * H_0,i
        # M_scene_iplus1 = T(offset) * H_0,iplus1 = T(offset) * H_0,i * H_i,iplus1

        # After manual adjustment, item2 has transform T'2_scene.
        # We want the new H'_{i,i+1} such that T'2_scene corresponds to T(offset) * H_0,i * H'_{i,i+1}.
        # T'2_scene = T(offset) * H_0,i * H'_{i,i+1}
        # T(offset).I * T'2_scene = H_0,i * H'_{i,i+1}
        # H_0,i.I * T(offset).I * T'2_scene = H'_{i,i+1}

        # This is getting complicated. Let's rethink the manual refinement representation.
        # The user is applying an *affine* transformation (translation, rotation, scale) to image i+1 *relative* to image i.
        # Let the initial relative homography be H_{i+1, i}_auto.
        # The user applies a manual affine transform M_manual_affine (represented by a 3x3 matrix).
        # The new relative homography should be H'_{i+1, i} = M_manual_affine * H_{i+1, i}_auto.
        # The challenge is deriving M_manual_affine from the QGraphicsItem's mouse events.
        # The item's mouse events update its internal pos, rotation, scale.
        # We need to convert these pos, rot, scale values into an affine matrix M_manual_affine.
        # This matrix should represent the transformation from img_{i+1}'s original position/orientation
        # *relative to img_i* to its new position/orientation *relative to img_i*.

        # Let's use the item's current pos, rotation, and scale properties (updated by mouse events)
        # to construct an affine matrix representing the transformation of item2 relative to item1.
        # This assumes item1 is fixed at its initial position/orientation.
        # The transformation from item1's local space to item2's local space in the scene is:
        # T1_scene.I * T2_scene.
        # This matrix should be the new H'_{i+1, i}.

        # Let's calculate the new relative homography H'_{i+1, i} directly from the item transforms.
        # H'_{i+1, i} = M1_scene.I * M2_scene
        try:
            M1_scene_inv = np.linalg.inv(M1_scene)
            H_iplus1_i_new = np.dot(M1_scene_inv, M2_scene)

            # Update the relative homography in the alignment process
            self.alignment_process.update_relative_homography(self._refine_pair_index, H_iplus1_i_new)
            # 2) récupérer les nouvelles informations
            self.cumulative_homographies = self.alignment_process.get_cumulative_homographies()
            self.canvas_size, self.canvas_offset = self.alignment_process.get_canvas_info()

            # After updating the relative homography and recalculating cumulative homographies/canvas,
            # the item positions/transforms in the scene view should ideally be updated to reflect
            # the *new* cumulative homographies. This prevents drift.
            # Recalculate M_scene_i and M_scene_iplus1 based on the *new* cumulative homographies
            # and the current canvas offset.
            new_cumulative_homographies = self.alignment_process.get_cumulative_homographies()
            H_0_i_new = new_cumulative_homographies[self._refine_pair_index]
            H_0_iplus1_new = new_cumulative_homographies[self._refine_pair_index + 1]
            offset_matrix = np.array([[1, 0, self.canvas_offset[0]],
                                      [0, 1, self.canvas_offset[1]],
                                      [0, 0, 1]], dtype=np.float64)

            M_scene_i_new = np.dot(offset_matrix, H_0_i_new)
            M_scene_iplus1_new = np.dot(offset_matrix, H_0_iplus1_new)

            # Apply the new transforms to the items
            # Temporarily disconnect signals to avoid infinite loops
            self._refine_item1.blockSignals(True)
            self._refine_item2.blockSignals(True)

            self._refine_item1.setTransform(numpy_to_qtransform(M_scene_i_new))
            self._refine_item2.setTransform(numpy_to_qtransform(M_scene_iplus1_new))

            # Reconnect signals
            self._refine_item1.blockSignals(False)
            self._refine_item2.blockSignals(False)

            # Update scene rect and fit view
            scene_rect = self._refine_item1.sceneBoundingRect().united(self._refine_item2.sceneBoundingRect())
            self.main_window.view_combined.scene().setSceneRect(scene_rect)
            # self.main_window.view_combined.fitInView(scene_rect, QtCore.Qt.AspectRatioMode.KeepAspectRatio) # Maybe don't refit automatically

            self.log_message(f"Homography for pair {self._refine_pair_index+1}-{self._refine_pair_index+2} updated.")

        except np.linalg.LinAlgError:
            self.log_message("Warning: Could not invert matrix to update homography.")
        except Exception as e:
            self.log_message(f"Error updating homography from item transform: {e}")


    def reset_manual_refinement(self):
        """Resets the manual refinement for the current pair to the auto-aligned state."""
        if self._refine_pair_index == -1 or self.alignment_process is None:
            return

        self.log_message(f"Resetting manual refinement for pair {self._refine_pair_index+1}-{self._refine_pair_index+2}.")

        # Re-run auto-alignment for this specific pair? No, that's not how it works.
        # We need to revert the relative homography for this pair back to the value
        # calculated by the initial auto-alignment.
        # This requires storing the original relative homographies.
        # Let's modify AlignmentProcess to store original relative homographies.
        # For now, as a simplification, let's just re-run the *cumulative* calculation
        # from the original relative homographies (assuming they weren't overwritten).
        # A proper solution needs AlignmentProcess to store both original and current relative H.

        # Assuming AlignmentProcess stores original relative homographies:
        # self.alignment_process.reset_relative_homography(self._refine_pair_index)
        # self.alignment_process.recalculate_cumulative_and_canvas()

        # Since AlignmentProcess currently overwrites, we'd need to re-run the whole auto-align
        # or store a copy. Let's add a method to AlignmentProcess to reset a specific relative H.
        # (Need to add this to alignment.py)
        # For now, let's just reload the images and re-run auto-align (inefficient but works).
        # Or, if we stored the original relative homographies...

        # Let's assume AlignmentProcess has a method `reset_pair_to_auto(pair_index)`
        # self.alignment_process.reset_pair_to_auto(self._refine_pair_index)
        # self.cumulative_homographies = self.alignment_process.get_cumulative_homographies()
        # self.canvas_size, self.canvas_offset = self.alignment_process.get_canvas_info()

        # Re-setup the refinement view to reflect the reset
        # self.setup_refinement_view(self._refine_pair_index)
        # self.update_refinement_info_labels()
        # self.log_message("Manual refinement reset.")

        # --- Temporary Simplification ---
        # If we don't store original relative H, resetting is hard.
        # Let's skip the full reset for now or require re-running auto-align.
        # A better approach: when auto-align finishes, store a *copy* of the relative homographies.
        # The reset button then copies from the stored original back to the working set.
        # Let's add this state to AlignmentProcess.

        # Assuming AlignmentProcess now supports reset_pair_to_auto:
        if hasattr(self.alignment_process, 'reset_pair_to_auto'):
             self.alignment_process.reset_pair_to_auto(self._refine_pair_index)
             self.cumulative_homographies = self.alignment_process.get_cumulative_homographies()
             self.canvas_size, self.canvas_offset = self.alignment_process.get_canvas_info()
             self.setup_refinement_view(self._refine_pair_index) # Re-setup view based on reset H
             self.update_refinement_info_labels()
             self.log_message("Manual refinement reset for the current pair.")
        else:
             self.log_message("Reset function not fully implemented yet (requires AlignmentProcess update).")
             # Fallback: just reset the item positions visually, but the underlying H is not reset
             if self._refine_item1 and self._refine_item2:
                 self.setup_refinement_view(self._refine_pair_index) # Re-setup view based on current H
                 self.update_refinement_info_labels()
                 self.log_message("Refinement view reset (underlying alignment not reset).")


    def start_stitching(self):
        """Starts the stitching process in a worker thread."""
        if not self.images_pil or not self.cumulative_homographies or self.canvas_size[0] <= 0:
            self.log_message("Alignment not complete or no images loaded.")
            return

        self.log_message("Starting stitching worker...")
        self.update_ui_state("stitching") # Indicate busy state
        self.progress_bar.setValue(0)
        # Keep previous log messages

        resolution_factor = self.combo_resolution.currentData()

        self._stitch_worker = StitchingWorker(
            self.images_pil,
            self.cumulative_homographies,
            self.canvas_size,
            self.canvas_offset,
            resolution_factor
        )
        self._stitch_worker.signals.progress.connect(self.update_progress)
        self._stitch_worker.signals.log.connect(self.log_message)
        self._stitch_worker.signals.error.connect(self.on_stitching_error)
        self._stitch_worker.signals.stitch_complete.connect(self.on_stitching_complete)
        self._stitch_worker.signals.finished.connect(self.on_stitching_finished)
        self._stitch_worker.start()

    def on_stitching_error(self, message):
        """Handles errors from the stitching worker."""
        self.log_message(f"ERROR: {message}")
        QtWidgets.QMessageBox.critical(self, "Erreur de mosaïque", message)
        self.update_ui_state("aligned") # Allow retrying stitching

    def on_stitching_complete(self, final_mosaic_pil: Image.Image):
        """Handles successful completion of stitching."""
        self.log_message("Mosaic stitching successful.")
        self.final_mosaic_pil = final_mosaic_pil
        self.update_ui_state("mosaic_generated")
        self.log_message("Mosaic image generated. Ready to save.")

        # Optional: Display the final mosaic in the main view?
        # This would require adding a mode to ImageComparerApp to show a single image.
        # For now, just enable saving.

    def on_stitching_finished(self):
        """Cleans up after the stitching worker finishes."""
        self._stitch_worker = None
        self.progress_bar.setValue(0) # Reset progress bar

    def save_mosaic(self):
        """Saves the generated mosaic image to a file."""
        if self.final_mosaic_pil is None:
            self.log_message("No mosaic image generated yet.")
            return

        filepath, _ = QtWidgets.QFileDialog.getSaveFileName(
            self, "Enregistrer la mosaïque", "mosaic.jpg",
            "JPEG Image (*.jpg *.jpeg);;PNG Image (*.png);;TIFF Image (*.tif *.tiff)"
        )
        if not filepath:
            return

        try:
            quality = self.slider_quality.value()
            # PIL save options depend on format
            if filepath.lower().endswith(('.jpg', '.jpeg')):
                self.final_mosaic_pil.save(filepath, quality=quality)
            elif filepath.lower().endswith('.png'):
                 # PNG quality is compression level (0-9), not visual quality
                 # Let's just save without specific quality for PNG
                 self.final_mosaic_pil.save(filepath)
            elif filepath.lower().endswith(('.tif', '.tiff')):
                 self.final_mosaic_pil.save(filepath)
            else:
                 # Default to JPEG if extension is missing or unknown
                 filepath += ".jpg"
                 self.final_mosaic_pil.save(filepath, quality=quality)


            self.log_message(f"Mosaic saved to {filepath}")
            self.statusBar().showMessage(f"Mosaïque enregistrée : {os.path.basename(filepath)}", 3000)

        except Exception as e:
            self.log_message(f"Error saving mosaic: {e}")
            QtWidgets.QMessageBox.critical(self, "Erreur d'enregistrement", f"Impossible d'enregistrer la mosaïque :\n{e}")

    def statusBar(self):
        """Helper to access the main window's status bar."""
        return self.main_window.statusBar

    def closeEvent(self, event: QtGui.QCloseEvent):
        """Handles closing the dock widget."""
        # Cancel any running workers
        if self._align_worker and self._align_worker.isRunning():
            self._align_worker.cancel()
        if self._stitch_worker and self._stitch_worker.isRunning():
            self._stitch_worker.cancel()
        super().closeEvent(event)

    # --- Methods to be called by MaskedOrFullPixmapItem (controller interface) ---
    # These methods are already defined in ImageComparerApp, but the items
    # in the mosaic refinement view need to call the dock as their controller.
    # We need to implement the necessary parts here.

    # move_pixmap_item, on_rotation_changed, on_scale_changed are implemented above
    # to update the homography and labels.

    # The original ImageComparerApp also has:
    # - set_use_mask: Not needed for refinement items (always full)
    # - set_slider_ratio: Not needed for refinement items
    # - get_rotation, get_scale_factor: Items have these methods internally
    # - visual_center: Items have this method internally
    # - disable_drag, enable_drag: Handled in setup_refinement_view

    # Need to ensure the MaskedOrFullPixmapItem calls the correct controller instance.
    # When creating the items in setup_refinement_view, we pass `controller=self`.
