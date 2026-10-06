import sys
import os

# Add parent directory to path so we can import from the main app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app
from models import db, Product
from routes.product_routes import PRODUCT_DATA_MAP

app = create_app()

def migrate():
    with app.app_context():
        products = Product.query.all()
        updated_count = 0
        
        for p in products:
            p_type = p.product_type
            name_lower = p.name.lower()
            new_cat = p.category # Keep existing if no change found
            
            if p_type in PRODUCT_DATA_MAP:
                valid_cats = PRODUCT_DATA_MAP[p_type]["categories"]
                
                # Try to map based on product_type and name keywords
                if p_type == "Server":
                    if "rack" in name_lower or "dl" in name_lower or "r750" in name_lower:
                        new_cat = "Rack Server"
                    elif "tower" in name_lower or "ml" in name_lower or "t150" in name_lower:
                        new_cat = "Tower Server"
                    elif "blade" in name_lower:
                        new_cat = "Blade Server"
                    else:
                        new_cat = "Rack Server" # Default
                
                elif p_type == "Laptop":
                    if "rog" in name_lower or "legion" in name_lower or "predator" in name_lower or "alienware" in name_lower or "gaming" in name_lower or "omen" in name_lower:
                        new_cat = "Gaming Laptop"
                    elif "thinkpad" in name_lower or "latitude" in name_lower or "probook" in name_lower or "elitebook" in name_lower:
                        new_cat = "Business Laptop"
                    elif "macbook air" in name_lower or "xps" in name_lower or "zenbook" in name_lower or "swift" in name_lower or "spectre" in name_lower:
                        new_cat = "Ultrabook"
                    elif "macbook pro" in name_lower or "precision" in name_lower or "zbook" in name_lower:
                        new_cat = "Workstation Laptop"
                    else:
                        new_cat = "Business Laptop" # Default
                        
                elif p_type == "Desktop":
                    if "rog" in name_lower or "legion" in name_lower or "predator" in name_lower or "gaming" in name_lower:
                        new_cat = "Gaming Desktop"
                    elif "mini" in name_lower or "nuc" in name_lower:
                        new_cat = "Mini PC"
                    elif "mac studio" in name_lower or "workstation" in name_lower or "precision" in name_lower:
                        new_cat = "Workstation Desktop"
                    elif "optiplex" in name_lower or "thinkcentre" in name_lower or "inspiron desktop" in name_lower or "pavilion desktop" in name_lower or "envy desktop" in name_lower or "mag" in name_lower:
                        new_cat = "Workstation Desktop" # fallback
                    else:
                        new_cat = valid_cats[0]
                        
                elif p_type == "Printer":
                    if "laser" in name_lower or "laserjet" in name_lower:
                        new_cat = "Laser Printer"
                    elif "ink tank" in name_lower or "megatank" in name_lower or "ecotank" in name_lower:
                        new_cat = "Ink Tank"
                    elif "pixma" in name_lower or "deskjet" in name_lower or "envy" in name_lower or "inkjet" in name_lower:
                        new_cat = "Inkjet Printer"
                    elif "thermal" in name_lower:
                        new_cat = "Thermal Printer"
                    elif "dot matrix" in name_lower:
                        new_cat = "Dot Matrix Printer"
                    elif "3d" in name_lower or "creality" in name_lower or "bambu" in name_lower or "anycubic" in name_lower or "flashforge" in name_lower or "elegoo" in name_lower or "phrozen" in name_lower:
                        new_cat = "3D Printer"
                    else:
                        new_cat = "Laser Printer"
                        
                elif p_type == "Scanner":
                    if "flatbed" in name_lower:
                        new_cat = "Flatbed Scanner"
                    elif "sheet" in name_lower or "scansnap" in name_lower:
                        new_cat = "Sheet-fed Scanner"
                    elif "portable" in name_lower:
                        new_cat = "Portable Scanner"
                    else:
                        new_cat = "Flatbed Scanner"
                        
                elif p_type == "Mouse":
                    if "gaming" in name_lower or "g pro" in name_lower or "rog" in name_lower or "deathadder" in name_lower or "basilisk" in name_lower or "g502" in name_lower:
                        new_cat = "Gaming Mouse"
                    elif "wireless" in name_lower or "mx master" in name_lower or "pebble" in name_lower or "anywhere" in name_lower or "bluetooth" in name_lower:
                        new_cat = "Wireless Mouse"
                    else:
                        new_cat = "Wired Mouse"
                        
                elif p_type == "Tablet":
                    if "ipad" in name_lower:
                        new_cat = "iPad"
                    elif "surface" in name_lower or "windows" in name_lower:
                        new_cat = "Windows Tablet"
                    else:
                        new_cat = "Android Tablet"
                        
                elif p_type == "Keyboard":
                    if "gaming" in name_lower or "mechanical" in name_lower or "rog" in name_lower:
                        new_cat = "Mechanical Keyboard"
                    elif "wireless" in name_lower or "mx keys" in name_lower:
                        new_cat = "Wireless Keyboard"
                    else:
                        new_cat = "Wired Keyboard"
                        
                elif p_type == "Monitor":
                    if "gaming" in name_lower or "odyssey" in name_lower or "rog" in name_lower or "ultragear" in name_lower:
                        new_cat = "Gaming Monitor"
                    elif "curved" in name_lower:
                        new_cat = "Curved Monitor"
                    elif "proart" in name_lower or "ultrasharp" in name_lower or "professional" in name_lower:
                        new_cat = "Professional Monitor"
                    else:
                        new_cat = "Standard Monitor"
                        
                elif p_type == "All-in-One (AIO)":
                    new_cat = "Consumer" # Default based on PRODUCT_DATA_MAP
                
                else:
                    new_cat = valid_cats[0] if len(valid_cats) > 0 else new_cat
            
            if p.category != new_cat:
                print(f"Updating {p.product_id_str} ({p.name}): {p.category} -> {new_cat}")
                p.category = new_cat
                updated_count += 1
                
        db.session.commit()
        print(f"Successfully migrated {updated_count} products.")

if __name__ == '__main__':
    migrate()
