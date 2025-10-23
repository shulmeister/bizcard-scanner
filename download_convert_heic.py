#!/usr/bin/env python3
import os
import io
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from dotenv import load_dotenv

load_dotenv()

def download_and_convert_heic():
    # Connect to Drive
    creds = Credentials.from_authorized_user_file("token.json")
    service = build("drive", "v3", credentials=creds)
    
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    
    # Find all HEIC files
    q = f"'{folder_id}' in parents and mimeType = 'image/heif' and trashed = false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    heic_files = results.get('files', [])
    
    print(f"Found {len(heic_files)} HEIC files to convert")
    
    # Create a local directory for converted files
    output_dir = "converted_jpegs"
    os.makedirs(output_dir, exist_ok=True)
    
    for file in heic_files:
        print(f"Downloading and converting {file['name']}...")
        
        # Download HEIC file
        req = service.files().get_media(fileId=file['id'])
        heic_data = io.BytesIO()
        downloader = MediaIoBaseDownload(heic_data, req)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        # Save HEIC temporarily
        heic_filename = f"/tmp/{file['name']}"
        jpeg_filename = f"{output_dir}/{file['name'].replace('.HEIC', '.jpg')}"
        
        with open(heic_filename, 'wb') as f:
            f.write(heic_data.getvalue())
        
        # Convert using ImageMagick (use magick instead of convert)
        try:
            subprocess.run(['magick', heic_filename, jpeg_filename], check=True)
            print(f"✅ Converted {file['name']} to {jpeg_filename}")
                
        except subprocess.CalledProcessError:
            print(f"❌ Failed to convert {file['name']}")
        
        # Clean up temp HEIC file
        if os.path.exists(heic_filename):
            os.remove(heic_filename)
    
    print(f"\nConversion complete! All JPEG files are in the '{output_dir}' folder.")
    print("Now manually upload these JPEG files to your Google Drive Business Cards folder.")

if __name__ == "__main__":
    download_and_convert_heic()
