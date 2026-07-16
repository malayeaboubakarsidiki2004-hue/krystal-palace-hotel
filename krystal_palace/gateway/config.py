"""
config.py — Configuration de la passerelle BACnet
Krystal Palace Hôtel Yaoundé — Windows (même PC)
Simulateur BACnet : YABE (Yet Another BACnet Explorer)
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Charge krystal_palace/.env (même fichier que le serveur PMS, un seul
# GATEWAY_TOKEN partagé entre les deux processus).
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

# ── Sécurité ─────────────────────────────────────────────────────────────────
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "secret-gateway-token")

# ── BACnet/IP — YABE sur Windows ─────────────────────────────────────────────
# YABE est lancé sur le même PC → on utilise 127.0.0.1
# Dans YABE : Settings → Network → IP Address = 127.0.0.1, Port = 47808
BACNET_DEVICE_IP   = os.getenv("BACNET_DEVICE_IP", "127.0.0.1")   # Même PC Windows
BACNET_DEVICE_PORT = int(os.getenv("BACNET_DEVICE_PORT", "47808"))  # Port BACnet/IP standard (UDP)
BACNET_TIMEOUT      = int(os.getenv("BACNET_TIMEOUT", "10"))        # Secondes d'attente par requête BACnet

# Device Instance du simulateur YABE
# Dans YABE : Add Device → saisir Device Instance = 1001
YABE_DEVICE_INSTANCE = int(os.getenv("YABE_DEVICE_INSTANCE", "1001"))

# ── Mapping chambres → objets BACnet (à créer dans YABE)
#   ao_setpoint : Analog Output  — consigne de température (°C)
#   bo_power    : Binary Output  — marche (True) / arrêt (False)
#   mv_mode     : Multi-State Value — 1=Auto 2=Froid 3=Chaud 4=Ventilation
CHAMBRES_BACNET = {
    "101": {"ao_setpoint": 1,  "bo_power": 1,  "mv_mode": 1},
    "102": {"ao_setpoint": 2,  "bo_power": 2,  "mv_mode": 2},
    "103": {"ao_setpoint": 3,  "bo_power": 3,  "mv_mode": 3},
    "201": {"ao_setpoint": 4,  "bo_power": 4,  "mv_mode": 4},
    "202": {"ao_setpoint": 5,  "bo_power": 5,  "mv_mode": 5},
    "203": {"ao_setpoint": 6,  "bo_power": 6,  "mv_mode": 6},
    "301": {"ao_setpoint": 7,  "bo_power": 7,  "mv_mode": 7},
    "302": {"ao_setpoint": 8,  "bo_power": 8,  "mv_mode": 8},
    "303": {"ao_setpoint": 9,  "bo_power": 9,  "mv_mode": 9},
    "401": {"ao_setpoint": 10, "bo_power": 10, "mv_mode": 10},
    "402": {"ao_setpoint": 11, "bo_power": 11, "mv_mode": 11},
}

# ── Consignes HVAC
TEMP_PRECOOLING       = 20.0   # Pré-refroidissement avant arrivée (°C)
TEMP_OCCUPIED         = 24.0   # Température chambre occupée (°C)
MODE_COOLING          = 2      # Mode BACnet : 2 = Froid

# ── Délais de temporisation
MINUTES_AVANT_ARRIVEE = 15     # Démarrer clim 30 min avant l'arrivée
MINUTES_APRES_DEPART  = 5     # Arrêter clim 10 min après le checkout
