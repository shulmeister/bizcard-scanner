#!/usr/bin/env python3
from flask import Flask, render_template, request, jsonify
import os
import io
import re
import hashlib
from typing import Dict, Optional
from dotenv import load_dotenv
import requests
from PIL import Image, ImageEnhance
import pytesseract
from werkzeug.utils import secure_filename
import secrets

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'heic'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_TAG = os.getenv("MAILCHIMP_TAG", "Referral Source")

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:(?:\+?1[\s\-.])?)?(?:\(?\d{3}\)?|\d{3})[\s\-.]?\d{3}[\s\-.]?\d{4}")
WEB_RE = re.compile(r"\b(?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z]{2,}){1,}(/[^\s]*)?\b")

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def ocr_image_with_rotation(image_path: str) -> str:
    try:
        original_image = Image.open(image_path)
        
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
            except Exception:
                continue
        
        return best_result
    except Exception as e:
        print(f"OCR failed: {e}")
        return ""

def parse_contact_info(text: str) -> Dict[str, Optional[str]]:
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

def add_to_mailchimp(email, fname, lname, company, phone, website):
    if not email:
        return False, "No email address found"
    
    mhash = hashlib.md5(email.lower().encode()).hexdigest()
    base = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0"
    url = f"{base}/lists/{MAILCHIMP_LIST_ID}/members/{mhash}"
    auth = ("anystring", MAILCHIMP_API_KEY)
    
    payload = {
        "email_address": email.lower(),
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
    
    return ok, r.json() if ok else r.text

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file provided'}), 400
    
    file = request.files['file']
    
    if file.filename == '':
        return jsonify({'success': False, 'error': 'No file selected'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'success': False, 'error': 'Invalid file type. Please upload JPG, PNG, or HEIC'}), 400
    
    try:
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        text = ocr_image_with_rotation(filepath)
        
        if not text.strip():
            return jsonify({
                'success': False,
                'error': 'Could not extract text from image. Please ensure the image is clear and well-lit.'
            }), 400
        
        contact = parse_contact_info(text)
        
        if not contact['email']:
            return jsonify({
                'success': False,
                'error': 'No email address found on business card',
                'contact': contact
            }), 400
        
        fname = lname = ""
        if contact['name']:
            parts = contact['name'].split()
            if len(parts) >= 2:
                fname, lname = parts[0], " ".join(parts[1:])
            else:
                fname = parts[0]
        
        success, response = add_to_mailchimp(
            contact['email'],
            fname,
            lname,
            contact['company'],
            contact['phone'],
            contact['website']
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': f"Successfully added {contact['email']} to Mailchimp!",
                'contact': contact
            })
        else:
            return jsonify({
                'success': False,
                'error': f"Failed to add to Mailchimp: {response}",
                'contact': contact
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Processing error: {str(e)}"
        }), 500
    finally:
        if os.path.exists(filepath):
            os.remove(filepath)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
