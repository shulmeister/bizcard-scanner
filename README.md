Simplest setup (no Google Cloud service account, no Vision API). 
This version:
- Asks you to sign in to Google once in a browser (OAuth),
- Reads images/PDFs from your Drive folder,
- Uses local Tesseract OCR (install with Homebrew),
- Upserts contacts to Mailchimp with tag "Referral Source".

Steps (macOS):
1) Install Homebrew if you don't have it: https://brew.sh
2) Install Tesseract: `brew install tesseract poppler`
3) Put your Google OAuth client secret JSON in this folder and name it `client_secret.json`.
4) In Terminal:
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   cp .env.example .env
   python3 business_card_scanner.py
   ```
5) A browser window opens. Choose the Google account that owns the Drive folder and allow "View Drive files".
6) The script finds files in the folder, OCRs, and pushes to Mailchimp. Contacts appear under your Audience with the "Referral Source" tag.

Notes:
- This build does not move files or require Vision API. It keeps things dead simple.
- For PDFs, we use `pdf2image` which needs Poppler (`brew install poppler`).
- If a card has no email on it, we skip Mailchimp (email is required). Check Terminal logs if someone is missing.
