#!/bin/bash
set -e

# CrÃ©er les rÃ©pertoires nÃ©cessaires avec les bonnes permissions
# Ce script s'exÃ©cute en tant que root avant de passer Ã  appuser
mkdir -p /app/logs /app/recordings /app/reports /app/temp /app/models/piper

# S'assurer que les rÃ©pertoires appartiennent Ã  appuser
chown -R appuser:appuser /app/logs /app/recordings /app/reports /app/temp /app/models/piper

# Donner les permissions d'Ã©criture
chmod -R 755 /app/logs /app/recordings /app/reports /app/temp /app/models/piper

# ExÃ©cuter la commande passÃ©e en argument en tant qu'appuser
exec gosu appuser "$@"
