import sys
print("Python path:")
for path in sys.path:
    print(f"  {path}")

print("\nTrying to import pcb_mosaic...")
try:
    import pcb_mosaic
    print(f"Success! pcb_mosaic version: {pcb_mosaic.__version__}")
    
    from pcb_mosaic.gui import PCBMosaicDock
    print("Successfully imported PCBMosaicDock from pcb_mosaic.gui")
except ImportError as e:
    print(f"Import failed: {e}")
