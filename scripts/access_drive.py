name: Google Drive Access

on:
  push:
    branches: [ main ]
  workflow_dispatch:

jobs:
  access-drive:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
          
      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install google-auth google-api-python-client
          
      - name: Access Google Drive
        env:
          GOOGLE_CREDENTIALS: ${{ secrets.GOOGLE_DRIVE_CREDENTIALS }}
        run: python scripts/access_drive.py
