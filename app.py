#!/usr/bin/env python3
"""
Simple Business Card Scanner App
Upload a business card image, extract contact info, and add to Mailchimp
"""

from flask import Flask, render_template, request, jsonify
import os
import re
import hashlib
import requests
from PIL import Image, ImageEnhance
import pytesseract
from werkzeug.utils import secure_filename
import secrets

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['ALLOWED_EXTENSIONS'] = {'jpg', 'jpeg', 'png', 'heic'}

# Create uploads directory
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Mailchimp configuration from environment variables
MAILCHIMP_API_KEY = os.getenv("MAILCHIMP_API_KEY")
MAILCHIMP_SERVER_PREFIX = os.getenv("MAILCHIMP_SERVER_PREFIX")
MAILCHIMP_LIST_ID = os.getenv("MAILCHIMP_LIST_ID")
MAILCHIMP_TAG = os.getenv("MAILCHIMP_TAG", "Referral Source")

# Regex patterns for extracting contact information
EMAIL_PATTERN = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b')
PHONE_PATTERN = re.compile(r'(?:\+?1[\s\-.])?(?:\(?\d{3}\)?[\s\-.]?)?\d{3}[\s\-.]?\d{4}')
WEBSITE_PATTERN = re.compile(r'(?:https?://)?(?:www\.)?[A-Za-z0-9\-]+(?:\.[A-Za-z]{2,}){1,}(?:/[^\s]*)?')

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

def extract_text_from_image(image_path):
    """Extract text from image using OCR with multiple attempts"""
    try:
        # Open and process image
        image = Image.open(image_path)
        
        # Convert to RGB if needed
        if image.mode not in ("RGB", "L"):
            image = image.convert("RGB")
        
        # Convert to grayscale for better OCR
        gray_image = image.convert('L')
        
        # Try different image enhancements
        variations = [
            ("Original", gray_image),
            ("High Contrast", ImageEnhance.Contrast(gray_image).enhance(2.0)),
            ("Sharpened", ImageEnhance.Sharpness(gray_image).enhance(2.0)),
            ("Brightened", ImageEnhance.Brightness(gray_image).enhance(1.2)),
        ]
        
        best_text = ""
        best_score = 0
        
        for name, processed_image in variations:
            try:
                # Extract text using Tesseract
                text = pytesseract.image_to_string(processed_image, config='--psm 3')
                
                # Score based on found contact info
                emails = EMAIL_PATTERN.findall(text)
                phones = PHONE_PATTERN.findall(text)
                score = len(emails) * 10 + len(phones) * 5 + len(text.split())
                
                if score > best_score:
                    best_score = score
                    best_text = text
                    
            except Exception as e:
                print(f"OCR failed for {name}: {e}")
                continue
        
        return best_text
        
    except Exception as e:
        print(f"Image processing failed: {e}")
        return ""

def parse_contact_info(text):
    """Parse contact information from extracted text"""
    if not text:
        return {}
    
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    # Extract email, phone, website
    email_match = EMAIL_PATTERN.search(text)
    phone_match = PHONE_PATTERN.search(text)
    website_match = WEBSITE_PATTERN.search(text)
    
    email = email_match.group(0) if email_match else None
    phone = phone_match.group(0) if phone_match else None
    website = website_match.group(0) if website_match else None
    
    # Extract name and company from lines
    name = None
    company = None
    
    # Look for name and company in first few lines
    for i, line in enumerate(lines[:5]):
        # Skip lines that contain email, phone, or website
        if EMAIL_PATTERN.search(line) or PHONE_PATTERN.search(line) or WEBSITE_PATTERN.search(line):
            continue
        
        # Skip very short lines
        if len(line.split()) < 2:
            continue
            
        if not name:
            name = line
        elif not company and len(line.split()) > 1:
            company = line
            break
    
    return {
        'name': name,
        'company': company,
        'email': email,
        'phone': phone,
        'website': website
    }

def add_to_mailchimp(email, first_name, last_name, company, phone, website):
    """Add contact to Mailchimp list"""
    if not email:
        return False, "No email address found"
    
    if not all([MAILCHIMP_API_KEY, MAILCHIMP_SERVER_PREFIX, MAILCHIMP_LIST_ID]):
        return False, "Mailchimp configuration missing"
    
    # Create subscriber hash
    subscriber_hash = hashlib.md5(email.lower().encode()).hexdigest()
    
    # Mailchimp API endpoint
    base_url = f"https://{MAILCHIMP_SERVER_PREFIX}.api.mailchimp.com/3.0"
    url = f"{base_url}/lists/{MAILCHIMP_LIST_ID}/members/{subscriber_hash}"
    
    # Prepare payload
    payload = {
        "email_address": email.lower(),
        "status_if_new": "subscribed",
        "status": "subscribed",
        "merge_fields": {
            "FNAME": first_name or "",
            "LNAME": last_name or "",
            "COMPANY": company or "",
            "PHONE": phone or "",
            "WEBSITE": website or ""
        }
    }
    
    try:
        # Add/update subscriber
        response = requests.put(
            url,
            auth=("anystring", MAILCHIMP_API_KEY),
            json=payload,
            timeout=30
        )
        
        if response.status_code in [200, 201]:
            # Add tag if specified
            if MAILCHIMP_TAG:
                try:
                    tag_url = f"{base_url}/lists/{MAILCHIMP_LIST_ID}/members/{subscriber_hash}/tags"
                    requests.post(
                        tag_url,
                        auth=("anystring", MAILCHIMP_API_KEY),
                        json={"tags": [{"name": MAILCHIMP_TAG, "status": "active"}]},
                        timeout=20
                    )
                except Exception:
                    pass  # Tag addition is optional
            
            return True, "Successfully added to Mailchimp"
        else:
            return False, f"Mailchimp API error: {response.text}"
            
    except Exception as e:
        return False, f"Error connecting to Mailchimp: {str(e)}"

@app.route('/')
def index():
    """Main page"""
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    """Handle file upload and processing"""
    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No file provided'}), 400
        
        file = request.files['file']
        
        if file.filename == '':
            return jsonify({'success': False, 'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'success': False, 'error': 'Invalid file type. Please upload JPG, PNG, or HEIC'}), 400
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        try:
            # Extract text from image
            text = extract_text_from_image(filepath)
            
            if not text.strip():
                return jsonify({
                    'success': False,
                    'error': 'Could not extract text from image. Please ensure the image is clear and well-lit.'
                }), 400
            
            # Parse contact information
            contact = parse_contact_info(text)
            
            if not contact.get('email'):
                return jsonify({
                    'success': False,
                    'error': 'No email address found on business card',
                    'contact': contact
                }), 400
            
            # Split name into first and last
            first_name = ""
            last_name = ""
            if contact.get('name'):
                name_parts = contact['name'].split()
                if len(name_parts) >= 2:
                    first_name = name_parts[0]
                    last_name = " ".join(name_parts[1:])
                else:
                    first_name = name_parts[0]
            
            # Add to Mailchimp
            success, message = add_to_mailchimp(
                contact['email'],
                first_name,
                last_name,
                contact.get('company'),
                contact.get('phone'),
                contact.get('website')
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
                    'error': f"Failed to add to Mailchimp: {message}",
                    'contact': contact
                }), 500
                
        finally:
            # Clean up uploaded file
            if os.path.exists(filepath):
                os.remove(filepath)
                
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f"Processing error: {str(e)}"
        }), 500

@app.route('/health')
def health_check():
    """Health check endpoint"""
    return jsonify({'status': 'healthy', 'message': 'Business Card Scanner is running'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
