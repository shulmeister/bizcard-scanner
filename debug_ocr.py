#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from PIL import Image
import pytesseract
import io
import re

load_dotenv()

def test_ocr():
    # Connect to Drive
    creds = Credentials.from_authorized_user_file("token.json")
    service = build("drive", "v3", credentials=creds)
    
    # Get just JPG files (skip HEIC for now)
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    q = f"'{folder_id}' in parents and mimeType = 'image/jpeg' and trashed = false"
    
    results = service.files().list(q=q, fields="files(id, name)", pageSize=3).execute()
    files = results.get('files', [])
    
    EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
    
    for file in files:
        print(f"\n{'='*50}")
        print(f"Processing: {file['name']}")
        print('='*50)
        
        # Download
        req = service.files().get_media(fileId=file['id'])
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        
        # OCR with different settings
        data = buf.getvalue()
        image = Image.open(io.BytesIO(data))
        
        # Try different OCR configs
        configs = [
            "--psm 6",  # Single uniform block
            "--psm 4",  # Single column text
            "--psm 3",  # Default
            "--psm 8",  # Single word
        ]
        
        for i, config in enumerate(configs):
            try:
                text = pytesseract.image_to_string(image, config=config)
                emails = EMAIL_RE.findall(text)
                
                print(f"\nConfig {i+1} ({config}):")
                print("Raw OCR text:")
                print("-" * 30)
                print(repr(text[:200]))  # Show first 200 chars with escape characters
                print("-" * 30)
                
                if emails:
                    print(f"📧 Found emails: {emails}")
                else:
                    print("❌ No emails found")
                    
            except Exception as e:
                print(f"Error with config {config}: {e}")

if __name__ == "__main__":
    test_ocr()