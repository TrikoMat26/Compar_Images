import cv2
import numpy as np
from PIL import Image
import time
import math
from PySide6 import QtCore, QtGui

# Use SIFT if available, otherwise fallback to ORB
try:
    # Check if SIFT is available (it might be in contrib or not included)
    # A simple check is to see if cv2.SIFT exists
    if hasattr(cv2, 'SIFT_create'):
        print("Using SIFT for feature detection.")
        FEATURE_DETECTOR = 'SIFT'
    else:
         print("SIFT not available, falling back to ORB.")
         FEATURE_DETECTOR = 'ORB'
except AttributeError:
    print("SIFT not available, falling back to ORB.")
    FEATURE_DETECTOR = 'ORB'


class AlignmentProcess:
    """
    Handles automatic alignment of a sequence of overlapping images.
    Detects features, matches them between consecutive pairs, estimates
    homographies, calculates cumulative homographies, and determines
    the final canvas size and offset.
    """
    def __init__(self, progress_callback=None, log_callback=None):
        """
        Args:
            progress_callback (callable, optional): A function to call
                with progress updates (0-100). Defaults to None.
            log_callback (callable, optional): A function to call with
                log messages. Defaults to None.
        """
        self.progress_callback = progress_callback
        self.log_callback = log_callback
        self.images = [] # List of PIL Images
        self.image_paths = [] # List of image file paths
        self.homographies_relative = [] # H_i,i+1: list of homographies from img_i+1 to img_i
        self.homographies_cumulative = [] # H_0,i: list of homographies from img_i to img_0
        self.canvas_size = (0, 0) # (width, height)
        self.canvas_offset = (0.0, 0.0) # (x, y) offset for the top-left corner

        self._detector = None
        self._matcher = None

    def _log(self, message):
        """Sends a message to the log callback."""
        if self.log_callback:
            self.log_callback(message)
        else:
            print(message)

    def _update_progress(self, value):
        """Sends a progress update (0-100) to the progress callback."""
        if self.progress_callback:
            self.progress_callback(value)

    def load_images(self, image_paths):
        """
        Loads images from the given file paths.

        Args:
            image_paths (list): List of strings, paths to image files.
        """
        self._log(f"Loading {len(image_paths)} images...")
        self.images = []
        self.image_paths = image_paths
        for i, path in enumerate(image_paths):
            try:
                img = Image.open(path).convert("RGB") # Ensure RGB format
                self.images.append(img)
                self._update_progress(int((i + 1) / len(image_paths) * 10)) # 0-10% for loading
            except Exception as e:
                self._log(f"Error loading {path}: {e}")
                # Decide how to handle error: skip, raise, etc. For now, skip.
                continue
        self._log(f"Loaded {len(self.images)} images successfully.")
        self._update_progress(10)

    def _initialize_detector_and_matcher(self):
        """Initializes the feature detector and matcher based on FEATURE_DETECTOR."""
        if FEATURE_DETECTOR == 'SIFT':
            self._detector = cv2.SIFT_create()
            # FLANN is generally faster for SIFT/SURF
            FLANN_INDEX_KDTREE = 1
            index_params = dict(algorithm=FLANN_INDEX_KDTREE, trees=5)
            search_params = dict(checks=50)
            self._matcher = cv2.FlannBasedMatcher(index_params, search_params)
        elif FEATURE_DETECTOR == 'ORB':
            self._detector = cv2.ORB_create(nfeatures=2000) # Increased features
            # Use BFMatcher with Hamming distance for ORB
            self._matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False) # Use crossCheck=False for ratio test

    def _detect_and_match(self, img1_pil, img2_pil):
        """
        Detects features and matches them between two PIL images.

        Args:
            img1_pil (PIL.Image): First image.
            img2_pil (PIL.Image): Second image.

        Returns:
            tuple: (kp1, kp2, good_matches) or (None, None, None) if matching fails.
        """
        img1_cv = cv2.cvtColor(np.array(img1_pil), cv2.COLOR_RGB2GRAY)
        img2_cv = cv2.cvtColor(np.array(img2_pil), cv2.COLOR_RGB2GRAY)

        if self._detector is None or self._matcher is None:
             self._initialize_detector_and_matcher()

        # Find the keypoints and descriptors with the detector
        kp1, des1 = self._detector.detectAndCompute(img1_cv, None)
        kp2, des2 = self._detector.detectAndCompute(img2_cv, None)

        if des1 is None or des2 is None:
             self._log("Warning: Could not detect descriptors in one or both images.")
             return None, None, None
        if len(kp1) < 10 or len(kp2) < 10: # Need a minimum number of keypoints
             self._log(f"Warning: Not enough keypoints detected ({len(kp1)} in img1, {len(kp2)} in img2).")
             return None, None, None


        # Match descriptors
        # Use knnMatch for ratio test
        matches = self._matcher.knnMatch(des1, des2, k=2)

        # Apply ratio test
        good_matches = []
        try:
            for m, n in matches:
                if m.distance < 0.75 * n.distance: # Lowe's ratio test
                    good_matches.append(m)
        except ValueError:
             # Happens if k=2 matches are not found for some descriptors
             self._log("Warning: Not enough matches for ratio test.")
             return None, None, None


        self._log(f"Found {len(good_matches)} good matches.")

        if len(good_matches) < 4: # Need at least 4 points to find a homography
            self._log("Error: Not enough good matches to estimate homography.")
            return None, None, None

        return kp1, kp2, good_matches

    def _estimate_homography(self, kp1, kp2, matches):
        """
        Estimates the homography matrix from matched keypoints.

        Args:
            kp1 (list): Keypoints from the first image.
            kp2 (list): Keypoints from the second image.
            matches (list): List of good matches.

        Returns:
            tuple: (homography_matrix, mask) or (None, None) if estimation fails.
        """
        if len(matches) < 4:
            return None, None

        # Get the coordinates of the matched points
        src_pts = np.float32([kp1[m.queryIdx].pt for m in matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp2[m.trainIdx].pt for m in matches]).reshape(-1, 1, 2)

        # Find the homography matrix using RANSAC
        # H is the matrix that transforms points from img1 to img2
        # We need H_i+1,i which transforms points from img_i+1 to img_i
        # So, src_pts are from img_i+1 (kp2), dst_pts are from img_i (kp1)
        H_i_iplus1, mask = cv2.findHomography(dst_pts, src_pts, cv2.RANSAC, 5.0) # RANSAC threshold 5.0

        if H_i_iplus1 is None:
            self._log("Error: Could not estimate homography.")
            return None, None

        # Count inliers
        inliers = mask.ravel().sum()
        self._log(f"Homography estimated with {inliers} inliers out of {len(matches)} matches.")

        # Optional: Check homography quality (e.g., determinant, condition number)
        # For simplicity, we trust RANSAC for now.

        return H_i_iplus1, mask

    def auto_align(self):
        """
        Performs automatic alignment on the loaded images.

        Returns:
            bool: True if alignment was successful, False otherwise.
        """
        if len(self.images) < 2:
            self._log("Need at least two images for alignment.")
            self._update_progress(0)
            return False

        self._log("Starting automatic alignment...")
        self.homographies_relative = [] # H_i,i+1 (from i+1 to i)
        self.homographies_cumulative = [] # H_0,i (from i to 0)

        num_pairs = len(self.images) - 1
        if num_pairs <= 0:
             self._log("Not enough images to form pairs.")
             self._update_progress(0)
             return False

        # 1. Estimate relative homographies (H_i,i+1) for consecutive pairs
        self._log("Estimating relative homographies...")
        for i in range(num_pairs):
            self._log(f"Aligning image {i+1} to image {i}...")
            start_time = time.time()
            kp1, kp2, matches = self._detect_and_match(self.images[i], self.images[i+1])

            if kp1 is None or kp2 is None or matches is None:
                 self._log(f"Alignment failed for pair {i}-{i+1}. Aborting alignment.")
                 self._update_progress(0)
                 return False

            # Note: _estimate_homography takes points from the *source* image (img_i+1)
            # and maps them to the *destination* image (img_i).
            # So, src_pts come from kp2 (img_i+1), dst_pts come from kp1 (img_i).
            # The returned matrix H maps points from img_i+1 to img_i. This is H_i,i+1.
            H_i_iplus1, mask = self._estimate_homography(kp1, kp2, matches)

            if H_i_iplus1 is None:
                self._log(f"Homography estimation failed for pair {i}-{i+1}. Aborting alignment.")
                self._update_progress(0)
                return False

            self.homographies_relative.append(H_i_iplus1)
            end_time = time.time()
            self._log(f"Pair {i}-{i+1} aligned in {end_time - start_time:.2f}s")
            self._update_progress(10 + int((i + 1) / num_pairs * 40)) # 10-50% for relative homographies

        self._update_progress(50)
        self._log("Relative homographies estimated.")

        # 2. Calculate cumulative homographies (H_0,i) relative to the first image (index 0)
        # H_0,0 is identity
        # H_0,1 = H_0,0 * H_0,1 = H_0,1 (but we have H_1,0) -> H_0,1 = H_1,0.I
        # H_0,2 = H_0,1 * H_1,2 = H_1,0.I * H_1,2 (but we have H_2,1) -> H_0,2 = H_1,0.I * H_2,1.I
        # H_0,i = H_0,i-1 * H_i-1,i (but we have H_i,i-1) -> H_0,i = H_0,i-1 * H_i,i-1.I
        # Let's redefine relative homographies as H_i_iplus1 (from i to i+1) for clarity in cumulative step.
        # We estimated H_iplus1_i (from i+1 to i). Let's invert them.
        self._log("Calculating cumulative homographies...")
        homographies_i_iplus1 = [np.linalg.inv(H) for H in self.homographies_relative]

        self.homographies_cumulative = [np.identity(3)] # H_0,0 is identity

        for i in range(num_pairs):
            # H_0,i+1 = H_0,i * H_i,i+1
            H_0_iplus1 = np.dot(self.homographies_cumulative[-1], homographies_i_iplus1[i])
            self.homographies_cumulative.append(H_0_iplus1)
            self._update_progress(50 + int((i + 1) / num_pairs * 20)) # 50-70% for cumulative homographies

        self._update_progress(70)
        self._log("Cumulative homographies calculated.")

        # 3. Calculate canvas size and offset
        self._log("Calculating canvas size and offset...")
        min_x, min_y, max_x, max_y = 0, 0, 0, 0

        for i, img in enumerate(self.images):
            h, w = img.height, img.width
            corners = np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]]).reshape(-1, 1, 2)

            # Project corners using the cumulative homography H_0,i
            # cv2.perspectiveTransform expects points in the source image (img_i)
            # and applies H_0,i to map them to the destination (canvas relative to img_0 origin)
            transformed_corners = cv2.perspectiveTransform(corners, self.homographies_cumulative[i])

            # Update min/max bounds
            min_x = min(min_x, transformed_corners[:, 0, 0].min())
            min_y = min(min_y, transformed_corners[:, 0, 1].min())
            max_x = max(max_x, transformed_corners[:, 0, 0].max())
            max_y = max(max_y, transformed_corners[:, 0, 1].max())

        # Calculate canvas dimensions
        canvas_width = int(max_x - min_x)
        canvas_height = int(max_y - min_y)

        # Calculate offset to shift the top-left corner to (0,0)
        offset_x = -min_x
        offset_y = -min_y

        self.canvas_size = (canvas_width, canvas_height)
        self.canvas_offset = (offset_x, offset_y)

        self._log(f"Canvas size: {canvas_width}x{canvas_height}")
        self._log(f"Canvas offset: ({offset_x:.2f}, {offset_y:.2f})")
        self._update_progress(90)

        self._log("Automatic alignment complete.")
        self._update_progress(100)
        return True

    def get_cumulative_homographies(self):
        """Returns the list of cumulative homographies (H_0,i)."""
        return self.homographies_cumulative

    def get_canvas_info(self):
        """Returns the calculated canvas size and offset."""
        return self.canvas_size, self.canvas_offset

    def get_images(self):
        """Returns the loaded PIL images."""
        return self.images

    def get_image_paths(self):
        """Returns the loaded image file paths."""
        return self.image_paths

    def update_relative_homography(self, pair_index: int, manual_transform_matrix: np.ndarray):
        """
        Updates a relative homography (H_i,i+1) based on manual adjustment
        and recalculates cumulative homographies and canvas info.

        Args:
            pair_index (int): The index of the pair being adjusted (0 for 0-1, 1 for 1-2, etc.).
            manual_transform_matrix (np.ndarray): The 3x3 matrix representing the
                manual transformation applied to image i+1 relative to image i
                in the scene view. This matrix should map points from image i+1's
                current scene position/orientation to its new scene position/orientation.
        """
        if pair_index < 0 or pair_index >= len(self.homographies_relative):
            self._log(f"Error: Invalid pair index {pair_index}")
            return

        self._log(f"Updating homography for pair {pair_index}-{pair_index+1} manually...")

        # The manual_transform_matrix is a transformation in the scene coordinate system.
        # It maps points from the *current* scene position of img_{i+1} to its *new* scene position.
        # Let H_0,i be the cumulative homography for img_i, and H_0,i+1 be for img_i+1.
        # H_0,i+1 = H_0,i * H_i,i+1
        # The item transforms T_i and T_{i+1} in the scene correspond to H_0,i and H_0,i+1
        # (with scaling/translation for the scene view).
        # The manual transform M_manual applied to item_{i+1} means the new item transform is T'_{i+1} = M_manual * T_{i+1}.
        # We want the new cumulative homography H'_{0,i+1} to correspond to T'_{i+1}.
        # H'_{0,i+1} = H_0,i * H'_{i,i+1}
        # This implies the transformation from img_{i+1} original coords to img_i original coords (H'_{i,i+1})
        # should be updated based on M_manual.
        # The relationship between item transforms and homographies is complex due to scene scaling/offset.
        # A simpler approach: M_manual is the transformation from img_{i+1} *relative to img_i* in the scene.
        # This corresponds to updating the relative homography H_{i,i+1}.
        # New H_{i,i+1} = M_manual * Old H_{i,i+1} (assuming M_manual is relative transform from i+1 to i)
        # However, the manual transform is applied to the *item*, which is already transformed by H_0,i+1.
        # Let's assume the manual_transform_matrix represents the transformation from img_{i+1} original space
        # to img_i original space directly, based on the user's manipulation in the scene.
        # This means the user's manipulation of item_{i+1} relative to item_i *visually*
        # is interpreted as a direct update to the homography H_{i,i+1}.

        # Let's assume manual_transform_matrix is the *new* H_{i+1, i} matrix derived from the item positions/transforms.
        # The user manipulates item_{i+1} relative to item_i.
        # Let T_i be the scene transform of item_i (corresponding to H_0,i)
        # Let T'_{i+1} be the new scene transform of item_{i+1} after manual adjustment.
        # We want H'_{0,i+1} to correspond to T'_{i+1}.
        # H'_{0,i+1} = H_0,i * H'_{i,i+1}
        # The transformation from img_{i+1} original coords to img_i original coords is H'_{i,i+1}.
        # This transformation, when applied after H_0,i, should result in H'_{0,i+1}.
        # The item transforms T_i and T'_{i+1} map from image local coords to scene coords.
        # T_i corresponds to H_0,i (scaled and offset for the scene).
        # T'_{i+1} corresponds to H'_{0,i+1} (scaled and offset for the scene).
        # The transformation from img_{i+1} local coords to img_i local coords *in the scene view*
        # is T_i.inverted() * T'_{i+1}.
        # This scene-level relative transform should correspond to the homography H'_{i,i+1}.
        # So, H'_{i,i+1} = T_i.inverted() * T'_{i+1} (after converting QTransform to np.ndarray and handling scale/offset).
        # This is still complex.

        # Let's simplify the manual update logic for now:
        # Assume the manual_transform_matrix passed in is the *new* desired H_{i+1, i} matrix.
        # This matrix should be calculated in the GUI based on the relative position/rotation/scale
        # of item_{i+1} compared to item_i in the refinement view.
        # The GUI needs to calculate this matrix from the QGraphicsItem transforms.

        # Update the relative homography H_{i+1, i}
        # We store H_i,i+1 (from i+1 to i), so update that directly.
        self.homographies_relative[pair_index] = manual_transform_matrix

        # Recalculate cumulative homographies from the updated relative ones
        self._log("Recalculating cumulative homographies after manual adjustment...")
        homographies_i_iplus1 = [np.linalg.inv(H) for H in self.homographies_relative]
        self.homographies_cumulative = [np.identity(3)] # H_0,0 is identity
        for i in range(len(homographies_i_iplus1)):
             H_0_iplus1 = np.dot(self.homographies_cumulative[-1], homographies_i_iplus1[i])
             self.homographies_cumulative.append(H_0_iplus1)
        self._log("Cumulative homographies recalculated.")

        # Recalculate canvas size and offset
        self._log("Recalculating canvas size and offset after manual adjustment...")
        min_x, min_y, max_x, max_y = 0, 0, 0, 0

        for i, img in enumerate(self.images):
            h, w = img.height, img.width
            corners = np.float32([[0, 0], [w-1, 0], [w-1, h-1], [0, h-1]]).reshape(-1, 1, 2)
            transformed_corners = cv2.perspectiveTransform(corners, self.homographies_cumulative[i])
            min_x = min(min_x, transformed_corners[:, 0, 0].min())
            min_y = min(min_y, transformed_corners[:, 0, 1].min())
            max_x = max(max_x, transformed_corners[:, 0, 0].max())
            max_y = max(max_y, transformed_corners[:, 0, 1].max())

        self.canvas_size = (int(max_x - min_x), int(max_y - min_y))
        self.canvas_offset = (-min_x, -min_y)

        self._log(f"New canvas size: {self.canvas_size[0]}x{self.canvas_size[1]}")
        self._log(f"New canvas offset: ({self.canvas_offset[0]:.2f}, {self.canvas_offset[1]:.2f})")
        self._log("Canvas info recalculated.")

    def get_relative_homography(self, pair_index: int):
        """Returns the relative homography H_i+1,i for a given pair index."""
        if pair_index < 0 or pair_index >= len(self.homographies_relative):
            return None
        return self.homographies_relative[pair_index]


# Helper function to convert QTransform to numpy 3x3 matrix
def qtransform_to_numpy(qtransform: QtGui.QTransform) -> np.ndarray:
    """Converts a QTransform to a 3x3 numpy array."""
    matrix = np.identity(3, dtype=np.float64)
    matrix[0, 0] = qtransform.m11()
    matrix[0, 1] = qtransform.m12()
    matrix[0, 2] = qtransform.m13()
    matrix[1, 0] = qtransform.m21()
    matrix[1, 1] = qtransform.m22()
    matrix[1, 2] = qtransform.m23()
    matrix[2, 0] = qtransform.m31()
    matrix[2, 1] = qtransform.m32()
    matrix[2, 2] = qtransform.m33() # Should be 1.0 for affine transforms
    return matrix

# Helper function to convert numpy 3x3 matrix to QTransform
def numpy_to_qtransform(matrix: np.ndarray) -> QtGui.QTransform:
    """Converts a 3x3 numpy array to a QTransform."""
    if matrix.shape != (3, 3):
        raise ValueError("Matrix must be 3x3")
    return QtGui.QTransform(
        matrix[0, 0], matrix[0, 1], matrix[0, 2],
        matrix[1, 0], matrix[1, 1], matrix[1, 2],
        matrix[2, 0], matrix[2, 1], matrix[2, 2]
    )

# Helper function to create a translation matrix
def create_translation_matrix(tx, ty):
    """Creates a 3x3 translation matrix."""
    matrix = np.identity(3, dtype=np.float64)
    matrix[0, 2] = tx
    matrix[1, 2] = ty
    return matrix

# Helper function to create a scale matrix
def create_scale_matrix(sx, sy):
    """Creates a 3x3 scale matrix."""
    matrix = np.identity(3, dtype=np.float64)
    matrix[0, 0] = sx
    matrix[1, 1] = sy
    return matrix

# Helper function to create a rotation matrix (in degrees)
def create_rotation_matrix(angle_degrees):
    """Creates a 3x3 rotation matrix (around origin, degrees)."""
    angle_rad = math.radians(angle_degrees)
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    matrix = np.identity(3, dtype=np.float64)
    matrix[0, 0] = c
    matrix[0, 1] = -s
    matrix[1, 0] = s
    matrix[1, 1] = c
    return matrix

# Helper function to create a transformation matrix from pos, rotation, scale
# This is for converting QGraphicsItem properties to a matrix
def create_item_transform_matrix(pos: QtCore.QPointF, rotation_degrees: float, scale: float, item_center: QtCore.QPointF) -> np.ndarray:
    """
    Creates a 3x3 transformation matrix representing an item's transform
    (translation, rotation around center, scale from center).

    Args:
        pos (QtCore.QPointF): The item's top-left position in the scene.
        rotation_degrees (float): Rotation angle in degrees.
        scale (float): Scale factor.
        item_center (QtCore.QPointF): The center of the item's *untransformed*
                                      bounding rectangle (local coordinates).

    Returns:
        np.ndarray: The 3x3 transformation matrix.
    """
    # Sequence of transformations:
    # 1. Translate origin to item center: T(-cx, -cy)
    # 2. Apply rotation: R(angle)
    # 3. Apply scale: S(scale, scale)
    # 4. Translate back from item center, plus item's scene position: T(cx + pos.x(), cy + pos.y())

    cx, cy = item_center.x(), item_center.y()
    px, py = pos.x(), pos.y()

    # Note: OpenCV matrices are typically point * column vector, so transformations are applied right-to-left.
    # T_final = T(px+cx, py+cy) * S(s,s) * R(angle) * T(-cx, -cy)
    # Or, if applying to points (x,y,1) as row vector: (x,y,1) * M
    # M = T(-cx, -cy).T * R(angle).T * S(s,s).T * T(px+cx, py+cy).T
    # Let's stick to the standard OpenCV/NumPy matrix multiplication order (matrix * column vector)
    # M = T(px, py) * T(cx, cy) * S(s,s) * R(angle) * T(-cx, -cy) * T(-cx, -cy) # This is wrong

    # Correct sequence for matrix * column vector:
    # M = T(px, py) * T(cx, cy) * S(s,s) * R(angle) * T(-cx, -cy)
    # M = [1 0 px] [1 0 cx] [s 0 0] [cos -sin 0] [1 0 -cx]
    #     [0 1 py] [0 1 cy] [0 s 0] [sin cos  0] [0 1 -cy]
    #     [0 0 1 ] [0 0 1 ] [0 0 1] [0   0    1] [0 0 1  ]

    # Let's build it step by step:
    # 1. Translate origin to item center: T_to_center = create_translation_matrix(-cx, -cy)
    # 2. Apply rotation: R = create_rotation_matrix(rotation_degrees)
    # 3. Apply scale: S = create_scale_matrix(scale, scale)
    # 4. Translate back from item center, plus item's scene position: T_to_pos = create_translation_matrix(px + cx, py + cy)

    # M = T_to_pos @ S @ R @ T_to_center # This is the order for applying to points (x,y,1) as column vector
    # M = T(px, py) @ T(cx, cy) @ S @ R @ T(-cx, -cy) # Still confused about center translation

    # Let's use the QTransform approach and convert it
    q_transform = QtGui.QTransform()
    # Apply transformations in the order QGraphicsItem does: scale, then rotate, then translate
    # Rotation and scale are applied around the item's local origin (0,0) by default.
    # To rotate/scale around the center, we need to translate to center, rotate/scale, translate back.
    # QGraphicsItem applies transform *before* position.
    # So, the item's final transform T_final = T(pos) * T_transform
    # Where T_transform = T(cx, cy) * S(s,s) * R(angle) * T(-cx, -cy)

    q_transform.translate(item_center.x(), item_center.y())
    q_transform.rotate(rotation_degrees)
    q_transform.scale(scale, scale)
    q_transform.translate(-item_center.x(), -item_center.y())

    # Now add the item's position
    q_transform.translate(pos.x(), pos.y())

    return qtransform_to_numpy(q_transform)

