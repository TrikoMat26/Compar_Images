import sys
import os
import time
from PIL import Image
import numpy as np

# Add the parent directory to the Python path to find the pcb_mosaic package
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from pcb_mosaic.alignment import AlignmentProcess
from pcb_mosaic.stitcher import StitchingProcess

def run_backend_mosaic(image_folder, output_path, resolution_factor=1.0, jpeg_quality=90):
    """
    Runs the backend mosaic stitching process from a folder of images.

    Args:
        image_folder (str): Path to the folder containing input images.
        output_path (str): Path to save the final mosaic image.
        resolution_factor (float): Factor to scale the final mosaic resolution.
        jpeg_quality (int): JPEG quality (1-100) if saving as JPEG.
    """
    print(f"--- Starting PCB Mosaic Backend Process ---")
    print(f"Input folder: {image_folder}")
    print(f"Output path: {output_path}")
    print(f"Resolution factor: {resolution_factor}")

    # Find image files in the folder
    image_files = sorted([os.path.join(image_folder, f) for f in os.listdir(image_folder)
                          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff'))])

    if len(image_files) < 2:
        print("Error: Need at least 2 images in the folder.")
        return

    print(f"Found {len(image_files)} images.")

    # --- Step 1: Auto Align ---
    print("\n--- Running Auto Alignment ---")
    align_process = AlignmentProcess(log_callback=print) # Use print for logging

    start_time = time.time()
    align_process.load_images(image_files)
    if not align_process.auto_align():
        print("Auto alignment failed. Aborting.")
        return
    end_time = time.time()
    print(f"Auto alignment completed in {end_time - start_time:.2f} seconds.")

    cumulative_homographies = align_process.get_cumulative_homographies()
    canvas_size, canvas_offset = align_process.get_canvas_info()
    images_pil = align_process.get_images() # Get loaded PIL images

    print(f"Calculated canvas size: {canvas_size}")
    print(f"Calculated canvas offset: {canvas_offset}")
    print(f"Number of cumulative homographies: {len(cumulative_homographies)}")

    # --- Step 2: Stitching ---
    print("\n--- Running Stitching Process ---")
    stitch_process = StitchingProcess(log_callback=print) # Use print for logging

    start_time = time.time()
    final_mosaic_pil = stitch_process.create_mosaic(
        images_pil,
        cumulative_homographies,
        canvas_size,
        canvas_offset,
        resolution_factor
    )
    end_time = time.time()
    print(f"Stitching completed in {end_time - start_time:.2f} seconds.")

    if final_mosaic_pil is None:
        print("Mosaic creation failed. Aborting.")
        return

    print(f"Final mosaic size: {final_mosaic_pil.width}x{final_mosaic_pil.height}")

    # --- Step 3: Save Mosaic ---
    print("\n--- Saving Mosaic ---")
    try:
        if output_path.lower().endswith(('.jpg', '.jpeg')):
            final_mosaic_pil.save(output_path, quality=jpeg_quality)
            print(f"Mosaic saved successfully to {output_path} with quality {jpeg_quality}.")
        else:
            final_mosaic_pil.save(output_path)
            print(f"Mosaic saved successfully to {output_path}.")

    except Exception as e:
        print(f"Error saving mosaic: {e}")

    print("\n--- PCB Mosaic Backend Process Finished ---")


if __name__ == "__main__":
    # Example usage:
    # Create a folder named 'test_images' and put your overlapping PCB photos inside.
    # Make sure the script can find the 'pcb_mosaic' package.
    # You might need to adjust the sys.path.insert line depending on your project structure.

    # Example: Assuming 'test_images' folder is in the same directory as run_mosaic.py
    test_image_folder = os.path.join(os.path.dirname(__file__), 'test_images')
    output_file = os.path.join(os.path.dirname(__file__), 'output_mosaic.jpg')

    # Create a dummy test_images folder and some placeholder files if it doesn't exist
    if not os.path.exists(test_image_folder):
        os.makedirs(test_image_folder)
        print(f"Created dummy folder: {test_image_folder}")
        # Create dummy files (replace with actual images for testing)
        try:
            dummy_img = Image.new('RGB', (100, 100), color = 'red')
            dummy_img.save(os.path.join(test_image_folder, 'dummy_img_01.png'))
            dummy_img = Image.new('RGB', (100, 100), color = 'green')
            dummy_img.save(os.path.join(test_image_folder, 'dummy_img_02.png'))
            print("Created dummy image files. Replace them with your actual PCB photos.")
        except Exception as e:
            print(f"Could not create dummy images: {e}")


    # Check if the test_images folder contains actual images (more than just dummies)
    actual_image_files = [f for f in os.listdir(test_image_folder)
                          if f.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif', '.tif', '.tiff'))]

    if len(actual_image_files) < 2:
         print(f"Please place at least 2 overlapping PCB images in the '{test_image_folder}' folder.")
    else:
        # Run the process
        run_backend_mosaic(test_image_folder, output_file, resolution_factor=1.0, jpeg_quality=95)