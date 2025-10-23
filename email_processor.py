#!/usr/bin/env python3
"""
Email Business Card Processor
Monitors an email inbox for business card photos and processes them automatically
"""
import os
import imaplib
import email
from email.header import decode_header
import time
import re
import hashlib
from typing import Dict, Optional, List, Tuple
from dotenv import load_dotenv
import requests
from PIL import Image, ImageEnhance
import pytesseract
import io

load_dotenv()

# Email settings
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER", "imap.gmail.com")
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))

# Mailchimp settings
MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_TAG = os.getenv("MAILCHIMP_TAG", "Referral Source")

# Regex patterns
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:(?:\+?1[\s\-.])?)?(?:\(?\d{3}\)?|\d{3})[\s\-.]?\d{3}[\s\-.]?\d{4}")
WEB_RE = re.compile(r"\b(?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z]{2,}){1,}(/[^\s]*)?\b")

# Supported image formats
SUPPORTED_FORMATS = {'.jpg', '.jpeg', '.png', '.heic', '.gif', '.bmp'}

def log(message):
    """Simple logging function"""
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S')
    print(f"[{timestamp}] {message}")

def ocr_image_with_rotation(image_data: bytes) -> str:
    """Process image with multiple rotations to find best OCR result."""
    try:
        original_image = Image.open(io.BytesIO(image_data))
        
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
                    log(f"  Better OCR from {name} (score: {score})")
            except Exception:
                continue
        
        return best_result
    except Exception as e:
        log(f"  OCR failed: {e}")
        return ""

def parse_contact_info(text: str) -> Dict[str, Optional[str]]:
    """Extract contact information from OCR text."""
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
    }

def add_to_mailchimp(email_addr: str, fname: str, lname: str, company: str, phone: str, website: str) -> Tuple[bool, str]:
    """Add contact to Mailchimp list."""
    if not email_addr:
        return False, "No email address found"
    
    mhash = hashlib.md5(email_addr.lower().encode()).hexdigest()
    base = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0"
    url = f"{base}/lists/{MAILCHIMP_LIST_ID}/members/{mhash}"
    auth = ("anystring", MAILCHIMP_API_KEY)
    
    payload = {
        "email_address": email_addr.lower(),
        "status_if_new": "subscribed",
        "status": "subscribed",
        "merge_fields": {
            "FNAME": fname or "",
            "LNAME": lname or "",
            "COMPANY": company or "",
            "PHONE": phone or "",
            "WEBSITE": website or "",
        }
    }
    
    r = requests.put(url, auth=auth, json=payload, timeout=30)
    ok = r.status_code in (200, 201)
    
    if ok and MAILCHIMP_TAG:
        try:
            requests.post(
                f"{base}/lists/{MAILCHIMP_LIST_ID}/members/{mhash}/tags",
                auth=auth,
                json={"tags": [{"name": MAILCHIMP_TAG, "status": "active"}]},
                timeout=20
            )
        except Exception:
            pass
    
    message = f"Successfully added {email_addr}" if ok else f"Failed to add {email_addr}"
    return ok, message

def process_email_message(mail, email_id):
    """Process a single email message."""
    try:
        status, msg_data = mail.fetch(email_id, "(RFC822)")
        
        if status != "OK":
            return
        
        msg = email.message_from_bytes(msg_data[0][1])
        
        from_header = msg.get("From")
        sender = email.utils.parseaddr(from_header)[1]
        
        subject = msg.get("Subject")
        if subject:
            subject, encoding = decode_header(subject)[0]
            if isinstance(subject, bytes):
                subject = subject.decode(encoding or "utf-8")
        
        log(f"\n📧 Processing email from {sender}")
        log(f"  Subject: {subject}")
        
        attachments_found = 0
        contacts_added = 0
        
        for part in msg.walk():
            if part.get_content_maintype() == 'multipart':
                continue
            
            filename = part.get_filename()
            if not filename:
                continue
            
            file_ext = os.path.splitext(filename)[1].lower()
            if file_ext not in SUPPORTED_FORMATS:
                continue
            
            attachments_found += 1
            log(f"  📎 Found attachment: {filename}")
            
            image_data = part.get_payload(decode=True)
            
            log(f"  🔍 Processing OCR...")
            text = ocr_image_with_rotation(image_data)
            
            if not text.strip():
                log(f"  ❌ No text extracted from {filename}")
                continue
            
            contact = parse_contact_info(text)
            log(f"  📋 Extracted: {contact.get('name')} - {contact.get('email')}")
            
            if not contact['email']:
                log(f"  ⚠️  No email found in {filename}")
                continue
            
            fname = lname = ""
            if contact['name']:
                parts = contact['name'].split()
                if len(parts) >= 2:
                    fname, lname = parts[0], " ".join(parts[1:])
                else:
                    fname = parts[0]
            
            success, message = add_to_mailchimp(
                contact['email'],
                fname,
                lname,
                contact['company'],
                contact['phone'],
                contact['website']
            )
            
            if success:
                contacts_added += 1
                log(f"  ✅ {message}")
            else:
                log(f"  ❌ {message}")
        
        if attachments_found == 0:
            log(f"  ℹ️  No image attachments found")
        else:
            log(f"  📊 Processed {attachments_found} images, added {contacts_added} contacts")
        
    except Exception as e:
        log(f"  ❌ Error processing email: {e}")

def monitor_inbox():
    """Monitor email inbox for new messages."""
    log("🚀 Starting email business card processor...")
    log(f"📧 Monitoring: {EMAIL_ADDRESS}")
    log(f"📬 IMAP Server: {IMAP_SERVER}:{IMAP_PORT}")
    log("-" * 60)
    
    while True:
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
            mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            mail.select("INBOX")
            
            status, messages = mail.search(None, "UNSEEN")
            
            if status == "OK":
                email_ids = messages[0].split()
                
                if email_ids:
                    log(f"\n📬 Found {len(email_ids)} new email(s)")
                    
                    for email_id in email_ids:
                        process_email_message(mail, email_id)
                        mail.store(email_id, '+FLAGS', '\\Seen')
            
            mail.close()
            mail.logout()
            
            time.sleep(30)
            
        except Exception as e:
            log(f"❌ Connection error: {e}")
            log("⏳ Retrying in 60 seconds...")
            time.sleep(60)

if __name__ == "__main__":
    required_vars = [
        "EMAIL_ADDRESS", "EMAIL_PASSWORD", 
        "MAILCHIMP_API_KEY", "MAILCHIMP_SERVER_PREFIX", "MAILCHIMP_LIST_ID"
    ]
    
    missing_vars = [var for var in required_vars if not os.getenv(var)]
    
    if missing_vars:
        log(f"❌ Missing required environment variables: {', '.join(missing_vars)}")
        log("Please add them to your .env file")
        exit(1)
    
    monitor_inbox()
