#!/usr/bin/env python3
import os, io, re, hashlib, logging
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv
import requests

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from PIL import Image, ImageEnhance
from pillow_heif import register_heif_opener
register_heif_opener()
import pytesseract
from pdf2image import convert_from_bytes

load_dotenv()
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL","INFO").upper()),
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("bizcard")

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID")
MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_TAG = os.getenv("MAILCHIMP_TAG","Referral Source")
GOOGLE_OAUTH_CLIENT_JSON = os.getenv("GOOGLE_OAUTH_CLIENT_JSON","client_secret.json")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:(?:\+?1[\s\-.])?)?(?:\(?\d{3}\)?|\d{3})[\s\-.]?\d{3}[\s\-.]?\d{4}")
WEB_RE = re.compile(r"\b(?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z]{2,}){1,}(/[^\s]*)?\b")

def drive_service():
    creds = None
    token_path = "token.json"
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
            except Exception:
                creds = None
        if not creds:
            flow = InstalledAppFlow.from_client_secrets_file(GOOGLE_OAUTH_CLIENT_JSON, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())
    return build("drive","v3",credentials=creds)

def list_files(svc, folder_id: str):
    q = f"'{folder_id}' in parents and (mimeType contains 'image/' or mimeType = 'application/pdf') and trashed = false"
    res = svc.files().list(q=q, fields="files(id,name,mimeType,modifiedTime)").execute()
    return res.get("files", [])

def download(svc, fid: str) -> bytes:
    req = svc.files().get_media(fileId=fid)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        status, done = downloader.next_chunk()
    return buf.getvalue()

def ocr_bytes_with_rotation(data: bytes, mime: str) -> str:
    try:
        if mime == "application/pdf":
            pages = convert_from_bytes(data, dpi=300)
            if not pages:
                return ""
            original_image = pages[0]
        else:
            original_image = Image.open(io.BytesIO(data))
        
        if original_image.mode not in ("RGB", "L"):
            original_image = original_image.convert("RGB")
        
        gray_image = original_image.convert('L')
        
        variations = [
            ("Original", gray_image),
            ("High Contrast", ImageEnhance.Contrast(gray_image).enhance(2.0)),
            ("Rotated 90°", gray_image.rotate(90, expand=True)),
            ("Rotated 180°", gray_image.rotate(180, expand=True)),
            ("Rotated 270°", gray_image.rotate(270, expand=True)),
        ]
        
        best_result = ""
        best_score = 0
        
        for name, img in variations:
            try:
                text = pytesseract.image_to_string(img, config="--psm 3")
                emails = EMAIL_RE.findall(text)
                phones = PHONE_RE.findall(text)
                score = len(emails) * 10 + len(phones) * 5 + len(text.split())
                
                if score > best_score:
                    best_score = score
                    best_result = text
                    log.info(f"New best OCR result from {name} (score: {score})")
            except Exception:
                continue
        
        return best_result
    except Exception as e:
        log.error("OCR processing failed: %s", e)
        return ""

def parse(text: str) -> Dict[str, Optional[str]]:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    block = "\n".join(lines)
    email = EMAIL_RE.search(block)
    phone = PHONE_RE.search(block)
    web = WEB_RE.search(block)

    name = company = None
    candidates = []
    for ln in lines[:6]:
        if EMAIL_RE.search(ln) or PHONE_RE.search(ln) or WEB_RE.search(ln):
            continue
        if len(ln.split()) <= 1:
            continue
        candidates.append(ln)
    if candidates:
        name = candidates[0]
        if len(candidates) > 1:
            company = candidates[1]

    return {
        "name": name,
        "company": company,
        "email": email.group(0) if email else None,
        "phone": phone.group(0) if phone else None,
        "website": web.group(0) if web else None,
        "raw_text": block
    }

def mc_upsert(email: str, merge: Dict[str,str], tags: List[str]) -> Tuple[bool, Dict]:
    if not email:
        return False, {"error":"missing email"}
    mhash = hashlib.md5(email.lower().encode()).hexdigest()
    base = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0"
    url = f"{base}/lists/{MAILCHIMP_LIST_ID}/members/{mhash}"
    auth = ("anystring", MAILCHIMP_API_KEY)
    payload = {
        "email_address": email.lower(),
        "status_if_new": "subscribed",
        "status": "subscribed",
        "merge_fields": merge
    }
    r = requests.put(url, auth=auth, json=payload, timeout=30)
    ok = r.status_code in (200,201)
    try:
        data = r.json()
    except Exception:
        data = {"status_code": r.status_code, "text": r.text}
    if ok and tags:
        try:
            requests.post(f"{base}/lists/{MAILCHIMP_LIST_ID}/members/{mhash}/tags",
                          auth=auth, json={"tags":[{"name":t,"status":"active"} for t in tags]}, timeout=20)
        except Exception:
            pass
    return ok, data

def main():
    for env in ["DRIVE_FOLDER_ID","MAILCHIMP_API_KEY","MAILCHIMP_SERVER_PREFIX","MAILCHIMP_LIST_ID"]:
        if not os.getenv(env):
            log.error("Missing %s in .env", env)
            return
    svc = drive_service()
    files = list_files(svc, DRIVE_FOLDER_ID)
    if not files:
        log.info("No files found in Drive folder.")
        return
    
    jpg_files = [f for f in files if f["mimeType"] == "image/jpeg"]
    log.info("Found %d JPG files to process", len(jpg_files))

    processed = 0
    successful_contacts = 0

    for f in jpg_files:
        fid, name, mime = f["id"], f["name"], f["mimeType"]
        log.info("Processing %s (%s)", name, mime)
        data = download(svc, fid)
        text = ocr_bytes_with_rotation(data, mime)
        if not text.strip():
            log.warning("No text extracted from %s", name)
            continue
            
        fields = parse(text)
        log.info("Parsed: name='%s', email='%s', phone='%s', company='%s'", 
                 fields.get("name"), fields.get("email"), fields.get("phone"), fields.get("company"))
        
        email = fields.get("email")
        if not email:
            log.warning("No email found for %s - skipping Mailchimp", name)
            continue
            
        fname = lname = None
        if fields.get("name"):
            parts = fields["name"].split()
            if len(parts) >= 2:
                fname, lname = parts[0], " ".join(parts[1:])
            else:
                fname = parts[0]
                
        merge = {
            "FNAME": fname or "",
            "LNAME": lname or "",
            "COMPANY": fields.get("company") or "",
            "PHONE": fields.get("phone") or "",
            "WEBSITE": fields.get("website") or "",
        }
        
        ok, resp = mc_upsert(email, merge, [MAILCHIMP_TAG] if MAILCHIMP_TAG else [])
        if not ok:
            log.error("Mailchimp upsert failed for %s: %s", email, resp)
        else:
            log.info("✅ Successfully added %s (%s) to Mailchimp", fname or "Unknown", email)
            successful_contacts += 1
        
        processed += 1
        
    log.info("Processing complete: %d files processed, %d contacts successfully added to Mailchimp", 
             processed, successful_contacts)

if __name__ == "__main__":
    main()
