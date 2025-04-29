import cv2
import numpy as np
from PIL import Image
from skimage.exposure import match_histograms # Optional: for color correction
import time
import math

# Try to import pyramid_blend, but don't fail if it's not available
try:
    from skimage.transform import pyramid_blend # For multi-band blending
    PYRAMID_BLEND_AVAILABLE = True
except ImportError:
    print("Warning: pyramid_blend not available in skimage.transform. Multi-band blending will be disabled.")
    PYRAMID_BLEND_AVAILABLE = False

class StitchingProcess:
    """
    Handles warping images using homographies and blending them
    into a single mosaic image.
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

    def _pil_to_cv2(self, pil_image: Image.Image) -> np.ndarray:
        """Converts a PIL Image to a CV2 image (BGR format)."""
        # Ensure RGB or RGBA
        if pil_image.mode not in ['RGB', 'RGBA']:
             pil_image = pil_image.convert('RGB')

        cv2_image = np.array(pil_image)

        # Convert RGB to BGR for OpenCV
        if pil_image.mode == 'RGB':
            cv2_image = cv2.cvtColor(cv2_image, cv2.COLOR_RGB2BGR)
        elif pil_image.mode == 'RGBA':
             # OpenCV uses BGRA
             cv2_image = cv2.cvtColor(cv2_image, cv2.COLOR_RGBA2BGRA)

        return cv2_image

    def _cv2_to_pil(self, cv2_image: np.ndarray) -> Image.Image:
        """Converts a CV2 image (BGR or BGRA) to a PIL Image (RGB or RGBA)."""
        if cv2_image.ndim == 3:
            if cv2_image.shape[2] == 3: # BGR
                pil_image = Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGR2RGB))
            elif cv2_image.shape[2] == 4: # BGRA
                pil_image = Image.fromarray(cv2.cvtColor(cv2_image, cv2.COLOR_BGRA2RGBA))
            else:
                 raise ValueError("Unsupported CV2 image format")
        elif cv2_image.ndim == 2: # Grayscale
             pil_image = Image.fromarray(cv2_image, mode='L')
        else:
             raise ValueError("Unsupported CV2 image format")

        return pil_image

    def _warp_image(self, image_pil: Image.Image, H_cumulative: np.ndarray, canvas_size: tuple, canvas_offset: tuple) -> np.ndarray:
        """
        Warps a single PIL image onto a canvas using its cumulative homography.

        Args:
            image_pil (PIL.Image): The original image.
            H_cumulative (np.ndarray): The 3x3 cumulative homography matrix (from image to origin of img_0).
            canvas_size (tuple): The size of the destination canvas (width, height).
            canvas_offset (tuple): The (x, y) offset to shift the canvas origin.

        Returns:
            np.ndarray: The warped image as a CV2 array (BGRA), or None if warping fails.
        """
        if image_pil is None or H_cumulative is None or canvas_size[0] <= 0 or canvas_size[1] <= 0:
            return None

        # Convert PIL image to CV2 (ensure alpha channel for transparency)
        image_cv = self._pil_to_cv2(image_pil.convert("RGBA")) # Convert to RGBA for alpha

        # Create the transformation matrix including the canvas offset
        # The cumulative homography H_cumulative maps points from the image's original
        # coordinate system to the coordinate system where img_0's top-left is (0,0).
        # The canvas has its top-left at (0,0), but this corresponds to the
        # projected point (-canvas_offset_x, -canvas_offset_y) in the img_0 origin system.
        # So, we need to translate the result of H_cumulative by (canvas_offset_x, canvas_offset_y).
        # The final transformation matrix M = T(offset_x, offset_y) * H_cumulative
        offset_matrix = create_translation_matrix(canvas_offset[0], canvas_offset[1])
        M_warp = np.dot(offset_matrix, H_cumulative)

        # Perform the perspective warp
        try:
            warped_image = cv2.warpPerspective(
                image_cv,
                M_warp,
                canvas_size,
                flags=cv2.INTER_LINEAR, # Use linear interpolation
                borderMode=cv2.BORDER_TRANSPARENT # Make areas outside the warped image transparent
            )
            return warped_image
        except Exception as e:
            self._log(f"Error during warping: {e}")
            return None


    def _blend_images(self, warped_images_cv: list) -> np.ndarray:
        """
        Blends multiple warped images using a simple alpha-based average.
        Assumes warped_images_cv are BGRA and have the same dimensions.

        Args:
            warped_images_cv (list): List of warped CV2 images (BGRA).

        Returns:
            np.ndarray: The blended mosaic image as a CV2 array (BGR).
        """
        if not warped_images_cv:
            return None

        # Ensure all images have the same size and format (BGRA)
        height, width, channels = warped_images_cv[0].shape
        if channels != 4:
             self._log("Error: Warped images must have 4 channels (BGRA) for blending.")
             return None

        # Initialize the final mosaic canvas (BGR)
        mosaic_bgr = np.zeros((height, width, 3), dtype=np.float32)
        # Initialize a weight map (sum of alpha channels)
        alpha_sum = np.zeros((height, width, 1), dtype=np.float32)

        # Accumulate color and alpha
        for img_cv in warped_images_cv:
            if img_cv.shape[:2] != (height, width) or img_cv.shape[2] != 4:
                 self._log("Warning: Mismatch in warped image dimensions or channels during blending.")
                 continue

            # Split BGRA channels
            bgr = img_cv[:, :, :3].astype(np.float32)
            alpha = img_cv[:, :, 3].astype(np.float32) / 255.0 # Normalize alpha to 0-1

            # Expand alpha to 3 channels for element-wise multiplication
            alpha_3_channels = cv2.merge([alpha, alpha, alpha])

            # Accumulate weighted color
            mosaic_bgr += bgr * alpha_3_channels

            # Accumulate alpha sum
            alpha_sum += alpha[:, :, np.newaxis] # Add new axis to make it (H, W, 1)

        # Avoid division by zero
        alpha_sum[alpha_sum == 0] = 1e-6

        # Normalize the accumulated color by the sum of alpha values
        blended_mosaic = (mosaic_bgr / alpha_sum).astype(np.uint8)

        return blended_mosaic

    def _blend_images_pyramid(self, warped_images_cv: list, masks_cv: list) -> np.ndarray:
        """
        Blends multiple warped images using multi-band blending (pyramid blending).
        Requires scikit-image with pyramid_blend available.

        Args:
            warped_images_cv (list): List of warped CV2 images (BGR).
            masks_cv (list): List of corresponding binary masks (CV2, 0 or 255).

        Returns:
            np.ndarray: The blended mosaic image as a CV2 array (BGR).
        """
        if not PYRAMID_BLEND_AVAILABLE:
            self._log("Pyramid blending not available. Falling back to alpha blending.")
            return self._blend_images(warped_images_cv)

        if not warped_images_cv or not masks_cv or len(warped_images_cv) != len(masks_cv):
            self._log("Error: Invalid input for pyramid blending.")
            return None

        self._log("Performing pyramid blending...")

        # Convert CV2 BGR images and masks to scikit-image format (float, 0-1)
        # scikit-image expects RGB float images
        images_sk = [cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float64) / 255.0 for img in warped_images_cv]
        masks_sk = [mask.astype(np.float64) / 255.0 for mask in masks_cv] # Masks should be float 0-1

        # Ensure all images/masks have the same size
        height, width = images_sk[0].shape[:2]
        if not all(img.shape[:2] == (height, width) for img in images_sk + masks_sk):
             self._log("Error: Mismatch in warped image/mask dimensions for pyramid blending.")
             return None

        # Use the first image as the base for blending
        # This simple approach might not be optimal for complex overlaps
        # A more advanced approach would build a graph and blend based on seams
        # For consecutive images, blending img_i+1 onto the current mosaic is simpler.
        # Let's adapt the process: blend images sequentially onto a growing mosaic.

        if len(images_sk) == 1:
             # If only one image, just return it
             result_image = images_sk[0]
             # Convert back to BGR for OpenCV
             return (cv2.cvtColor((result_image * 255).astype(np.uint8), cv2.COLOR_RGB2BGR))
        else:
             # Blend the first two images
             try:
                 # Need to define the seam or use masks to guide blending
                 # skimage.transform.pyramid_blend works best with two images and a mask defining the seam
                 # For multiple images, we need a different strategy or blend pairs iteratively.
                 # Let's use a simple iterative blend for now. Blend img_i+1 onto the mosaic of 0..i
                 # This requires re-warping the current mosaic, which is inefficient.

                 # Alternative: Create a single large canvas and blend all warped images onto it.
                 # The `pyramid_blend` function in scikit-image is designed for blending *two* images
                 # along a seam defined by a mask. It's not directly for blending N images on a canvas.

                 # Let's revert to a simpler weighted average or feathering if pyramid_blend is too complex here.
                 # A simple feathering: create a distance transform mask for each image, normalize weights.
                 # Or, just use the alpha blending from the previous method, which is simpler and often sufficient.

                 # Let's stick to the simple alpha blend for the first version, as pyramid blending
                 # for multiple images on a canvas is significantly more complex (seam finding, etc.).
                 # The `_blend_images` method already handles alpha from the RGBA warp.

                 self._log("Pyramid blending is complex for multiple images on a canvas. Using alpha blending.")
                 return self._blend_images(warped_images_cv) # Fallback to simple alpha blend

             except Exception as e:
                 self._log(f"Error during pyramid blending: {e}. Falling back to alpha blending.")
                 return self._blend_images(warped_images_cv)


    def create_mosaic(self, images_pil: list, cumulative_homographies: list, canvas_size: tuple, canvas_offset: tuple, resolution_factor: float = 1.0) -> Image.Image:
        """
        Creates the final mosaic image by warping and blending.

        Args:
            images_pil (list): List of original PIL images.
            cumulative_homographies (list): List of cumulative homography matrices (H_0,i).
            canvas_size (tuple): The size of the canvas (width, height) at original resolution.
            canvas_offset (tuple): The (x, y) offset for the canvas origin at original resolution.
            resolution_factor (float): Factor to scale the final mosaic resolution (e.g., 1.0, 2.0).

        Returns:
            PIL.Image: The final mosaic image, or None if stitching fails.
        """
        if not images_pil or not cumulative_homographies or len(images_pil) != len(cumulative_homographies):
            self._log("Error: Invalid input for creating mosaic.")
            self._update_progress(0)
            return None

        self._log("Starting mosaic creation...")

        # Calculate target canvas size based on resolution factor
        target_width = int(canvas_size[0] * resolution_factor)
        target_height = int(canvas_size[1] * resolution_factor)
        target_canvas_size = (target_width, target_height)

        # Calculate target canvas offset based on resolution factor
        target_offset = (canvas_offset[0] * resolution_factor, canvas_offset[1] * resolution_factor)

        if target_width <= 0 or target_height <= 0:
             self._log("Error: Target canvas size is zero or negative.")
             self._update_progress(0)
             return None

        self._log(f"Target mosaic size: {target_width}x{target_height}")

        warped_images_cv = []
        # warped_masks_cv = [] # Needed for pyramid blending if implemented

        # 1. Warp each image onto the target canvas
        self._log("Warping images...")
        num_images = len(images_pil)
        for i, img_pil in enumerate(images_pil):
            self._log(f"Warping image {i}...")
            start_time = time.time()

            # Scale the cumulative homography for the target resolution
            # H_target = T(target_offset) * S(res_factor, res_factor) * H_cumulative
            # No, the scaling should be applied to the homography itself before warping.
            # If H maps from source to original canvas, H_scaled maps from source to scaled canvas.
            # H_scaled = T(target_offset) * S(res_factor, res_factor) * T(-canvas_offset) * H_cumulative
            # Let's simplify: warp directly to the target size using a scaled homography.
            # The homography H_0,i maps points from img_i to the img_0 origin system.
            # We need a matrix M that maps points from img_i to the *final canvas* system.
            # M = T(target_offset) * S(res_factor, res_factor) * H_cumulative
            # This seems correct.

            scale_matrix = create_scale_matrix(resolution_factor, resolution_factor)
            offset_matrix = create_translation_matrix(target_offset[0], target_offset[1])
            M_warp = np.dot(offset_matrix, np.dot(scale_matrix, cumulative_homographies[i]))


            warped_img_cv = cv2.warpPerspective(
                self._pil_to_cv2(img_pil.convert("RGBA")), # Ensure RGBA for alpha
                M_warp,
                target_canvas_size,
                flags=cv2.INTER_LINEAR, # Use linear interpolation
                borderMode=cv2.BORDER_TRANSPARENT # Make areas outside the warped image transparent
            )

            if warped_img_cv is not None:
                warped_images_cv.append(warped_img_cv)
                # If using pyramid blending, generate masks here:
                # mask = np.full((img_pil.height, img_pil.width), 255, dtype=np.uint8)
                # warped_mask_cv = cv2.warpPerspective(mask, M_warp, target_canvas_size, flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
                # warped_masks_cv.append(warped_mask_cv)

            end_time = time.time()
            self._log(f"Image {i} warped in {end_time - start_time:.2f}s")
            self._update_progress(90 + int((i + 1) / num_images * 5)) # 90-95% for warping

        if not warped_images_cv:
            self._log("Error: No images were successfully warped.")
            self._update_progress(0)
            return None

        # 2. Blend warped images
        self._log("Blending warped images...")
        start_time = time.time()

        # Use the simple alpha blending method
        blended_mosaic_cv = self._blend_images(warped_images_cv)

        # If pyramid blending was implemented:
        # blended_mosaic_cv = self._blend_images_pyramid(warped_images_cv, warped_masks_cv)


        end_time = time.time()
        self._log(f"Blending complete in {end_time - start_time:.2f}s")
        self._update_progress(98)

        if blended_mosaic_cv is None:
            self._log("Error: Blending failed.")
            self._update_progress(0)
            return None

        # 3. Convert back to PIL Image
        final_mosaic_pil = self._cv2_to_pil(blended_mosaic_cv)

        self._log("Mosaic creation complete.")
        self._update_progress(100)

        return final_mosaic_pil

# Re-include helper functions from alignment.py for clarity or import them
# from .alignment import create_translation_matrix, create_scale_matrix, create_rotation_matrix

# Assuming helper functions are imported or defined here:
def create_translation_matrix(tx, ty):
    matrix = np.identity(3, dtype=np.float64)
    matrix[0, 2] = tx
    matrix[1, 2] = ty
    return matrix

def create_scale_matrix(sx, sy):
    matrix = np.identity(3, dtype=np.float64)
    matrix[0, 0] = sx
    matrix[1, 1] = sy
    return matrix

def create_rotation_matrix(angle_degrees):
    angle_rad = math.radians(angle_degrees)
    c = math.cos(angle_rad)
    s = math.sin(angle_rad)
    matrix = np.identity(3, dtype=np.float64)
    matrix[0, 0] = c
    matrix[0, 1] = -s
    matrix[1, 0] = s
    matrix[1, 1] = c
    return matrix
