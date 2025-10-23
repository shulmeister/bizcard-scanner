#!/usr/bin/env python3
import os
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

def test_drive_access():
    # Load existing credentials
    creds = Credentials.from_authorized_user_file("token.json")
    service = build("drive", "v3", credentials=creds)
    
    # List folders in your Drive
    print("=== Folders in your Google Drive ===")
    results = service.files().list(
        q="mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name, parents)"
    ).execute()
    
    folders = results.get('files', [])
    for folder in folders:
        print(f"Name: {folder['name']}")
        print(f"ID: {folder['id']}")
        print("---")
    
    # Test access to your specific folder
    print(f"\n=== Testing access to folder: 1m7T4QKiydcr2p55B5D0Mx0DIApK8lbak ===")
    try:
        folder_info = service.files().get(fileId="1m7T4QKiydcr2p55B5D0Mx0DIApK8lbak").execute()
        print(f"✅ Success! Folder name: {folder_info['name']}")
        
        # Try to list files in the folder
        print("\n=== Files in this folder ===")
        files = service.files().list(
            q=f"'1m7T4QKiydcr2p55B5D0Mx0DIApK8lbak' in parents and trashed=false",
            fields="files(id, name, mimeType)"
        ).execute()
        
        for file in files.get('files', []):
            print(f"  - {file['name']} ({file['mimeType']})")
            
    except Exception as e:
        print(f"❌ Error accessing folder: {e}")
        print("This folder might not be accessible with your current permissions.")

if __name__ == "__main__":
    test_drive_access()