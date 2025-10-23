#!/usr/bin/env python3
import os
from dotenv import load_dotenv
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import io
import re
import numpy as np

load_dotenv()

def preprocess_image(image):
    """Apply various preprocessing to improve OCR"""
    results = []
    
    # Original
    results.append(("Original", image))
    
    # Convert to grayscale
    gray = image.convert('L')
    results.append(("Grayscale", gray))
    
    # Increase contrast
    enhancer = ImageEnhance.Contrast(gray)
    high_contrast = enhancer.enhance(2.0)
    results.append(("High Contrast", high_contrast))
    
    # Sharpen
    sharpened = gray.filter(ImageFilter.SHARPEN)
    results.append(("Sharpened", sharpened))
    
    # Try different rotations
    for angle in [90, 180, 270]:
        rotated = gray.rotate(angle, expand=True)
        results.append((f"Rotated {angle}°", rotated))
    
    # Resize larger (sometimes helps with small text)
    width, height = gray.size
    enlarged = gray.resize((width * 2, height * 2), Image.Resampling.LANCZOS)
    results.append(("Enlarged 2x", enlarged))
    
    return results

def test_improved_ocr():
    # Connect to Drive
    creds = Credentials.from_authorized_user_file("token.json")
    service = build("drive", "v3", credentials=creds)
    
    # Get just 1 JPG file for testing
    folder_id = os.getenv("DRIVE_FOLDER_ID")
    q = f"'{folder_id}' in parents and mimeType = 'image/jpeg' and trashed = false"
    
    results = service.files().list(q=q, fields="files(id, name)", pageSize=1).execute()
    files = results.get('files', [])
    
    EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
    PHONE_RE = re.compile(r"(?:(?:\+?1[\s\-.])?)?(?:\(?\d{3}\)?|\d{3})[\s\-.]?\d{3}[\s\-.]?\d{4}")
    
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
        
        # Load image
        data = buf.getvalue()
        original_image = Image.open(io.BytesIO(data))
        
        # Try different preprocessing
        processed_images = preprocess_image(original_image)
        
        best_result = None
        best_score = 0
        
        for name, img in processed_images:
            try:
                # Try the best OCR config from before
                text = pytesseract.image_to_string(img, config="--psm 3")
                
                emails = EMAIL_RE.findall(text)
                phones = PHONE_RE.findall(text)
                
                # Score this result
                score = len(emails) * 10 + len(phones) * 5 + len(text.split())
                
                print(f"\n--- {name} ---")
                print(f"Score: {score}")
                if emails:
                    print(f"📧 Emails: {emails}")
                if phones:
                    print(f"📞 Phones: {phones}")
                
                # Show a cleaner version of the text
                clean_text = ' '.join(text.split())[:100]
                print(f"Text preview: {clean_text}...")
                
                if score > best_score:
                    best_score = score
                    best_result = (name, text, emails, phones)
                    
            except Exception as e:
                print(f"Error with {name}: {e}")
        
        if best_result:
            name, text, emails, phones = best_result
            print(f"\n🏆 BEST RESULT: {name}")
            print(f"📧 Best emails found: {emails}")
            print(f"📞 Best phones found: {phones}")
            print("\nFull text:")
            print("-" * 40)
            print(text)
            print("-" * 40)

if __name__ == "__main__":
    test_improved_ocr()