from oscal.oscal_support_class import setup_support
import os
import zipfile

SUPPORT_DB_PATH = os.path.join("..", "support", "oscal_support.db")
SUPPORT_ZIP_PATH = os.path.join("data", "oscal_support.zip")

print ("Database absolute path: " + os.path.abspath(SUPPORT_DB_PATH))
supportObj = setup_support(SUPPORT_DB_PATH)

if True: # supportObj.update("all"):
    print("Support assets updated successfully.")
    # Clear ./data/oscal_support.zip to ensure it will be regenerated with the updated support assets
    if os.path.exists(SUPPORT_ZIP_PATH):
        os.remove(SUPPORT_ZIP_PATH)
        print("Cleared existing oscal_support.zip to allow regeneration with updated assets.")

    # Zip the updated support database for distribution
    with zipfile.ZipFile(SUPPORT_ZIP_PATH, 'w', zipfile.ZIP_DEFLATED) as zipf:
        zipf.write(SUPPORT_DB_PATH, arcname=os.path.basename(SUPPORT_DB_PATH))
    print(f"Updated support database compressed and saved to {SUPPORT_ZIP_PATH}.")
    

else:    
    print("Failed to update support assets.")
