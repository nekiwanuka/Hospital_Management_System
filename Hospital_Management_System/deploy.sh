#!/usr/bin/env bash
# deploy.sh — Run this on the cPanel server after pulling new code.
#
# Usage (SSH into cPanel):
#   cd ~/Hospital_Management_System/Hospital_Management_System
#   bash deploy.sh

set -euo pipefail

VENV="/home/jbeiqmqv/virtualenv/hms/Hospital_Management_System/3.13"
PYTHON="$VENV/bin/python"
PIP="$VENV/bin/pip"

echo "── Installing / upgrading dependencies ──"
$PIP install --upgrade pip
$PIP install -r requirements.txt

echo "── Running migrations ──"
$PYTHON manage.py migrate --no-input

echo "── Collecting static files ──"
$PYTHON manage.py collectstatic --no-input --clear

echo "── Restarting Passenger ──"
mkdir -p tmp
touch tmp/restart.txt

echo "✓ Deployment complete."
