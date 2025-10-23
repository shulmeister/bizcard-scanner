#!/usr/bin/env python3
import os
import io
import subprocess
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from dotenv import load_dotenv

load_dotenv()

def convert_heic_files():
    # Connect to Drive
    creds = Credentials.from_authorized_user_file("token.json")
    service = build("drive", "v3", credentials=creds)
    
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    
    # Find all HEIC files
    q = f"'{folder_id}' in parents and mimeType = 'image/heif' and trashed = false"
    results = service.files().list(q=q, fields="files(id, name)").execute()
    heic_files = results.get('files', [])
    
    print(f"Found {len(heic_files)} HEIC files to convert")
    
    for file in heic_files:
        print(f"Converting {file['name']}...")
        
        # Download HEIC file
        req = service.files().get_media(fileId=file['id'])
        heic_data = io.BytesIO()
        downloader = MediaIoBaseDownload(heic_data, req)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        # Save temporarily
        heic_filename = f"/tmp/{file['name']}"
        jpeg_filename = f"/tmp/{file['name'].replace('.HEIC', '.jpg')}"
        
        with open(heic_filename, 'wb') as f:
            f.write(heic_data.getvalue())
        
        # Convert using ImageMagick
        try:
            subprocess.run(['convert', heic_filename, jpeg_filename], check=True)
            print(f"✅ Converted {file['name']} to JPEG")
            
            # Upload JPEG to Google Drive
            with open(jpeg_filename, 'rb') as f:
                media = MediaIoBaseUpload(f, mimetype='image/jpeg')
                jpeg_name = file['name'].replace('.HEIC', '.jpg')
                
                new_file = service.files().create(
                    body={'name': jpeg_name, 'parents': [folder_id]},
                    media_body=media
                ).execute()
                
                print(f"✅ Uploaded {jpeg_name} to Google Drive")
                
        except subprocess.CalledProcessError:
            print(f"❌ Failed to convert {file['name']}")
        
        # Clean up temp files
        if os.path.exists(heic_filename):
            os.remove(heic_filename)
        if os.path.exists(jpeg_filename):
            os.remove(jpeg_filename)
    
    print("Conversion complete!")

if __name__ == "__main__":
    convert_heic_files()
