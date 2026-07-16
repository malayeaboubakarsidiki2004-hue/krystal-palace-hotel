"""
main.py — Krystal Palace Hôtel Yaoundé v7.0
════════════════════════════════════════════════════════════════════════════════
Serveur principal FastAPI — PMS (Property Management System)
Stack : Python 3.11 · FastAPI · PostgreSQL · bacpypes3 · Orange Money USSD

Nouvelles fonctionnalités v7 :
  • Page 0 : espace client (Réserver / Annuler / Modifier)
  • Annulation avec pénalité 20%/jour après J-3 avant arrivée
  • Annulation bloquée après J+3 après arrivée (soit J-3+6 jours)
  • Modification possible uniquement avant le délai de pénalité (J-3)
  • Remboursement automatique simulé Orange Money
  • Nouvelle facture PDF après modification

Lancement PyCharm :
  → Menu Run → Run 'main' (configuration fournie dans .idea/)
  ou terminal :
  → uvicorn krystal_palace.main:app --host 127.0.0.1 --port 8000 --reload

URLs :
  Client      : http://127.0.0.1:8000
  Admin       : http://127.0.0.1:8000/admin
  API Swagger : http://127.0.0.1:8000/docs
════════════════════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import logging
import os
import secrets
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import httpx
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel

# Charge krystal_palace/.env (chemin absolu : fonctionne quel que soit le
# répertoire de travail depuis lequel uvicorn est lancé).
load_dotenv(Path(__file__).resolve().parent / ".env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("pms")

# ══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════════

app = FastAPI(
    title="Krystal Palace Hôtel Yaoundé — API PMS v7",
    description="Système de Gestion Hôtelière intégré avec BACnet/IP et Orange Money",
    version="7.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

security = HTTPBasic()

# Env vars
ADMIN_USER    = os.getenv("ADMIN_USER",    "admin")
ADMIN_PASS    = os.getenv("ADMIN_PASS",    "krystal2024")
GATEWAY_URL   = os.getenv("GATEWAY_URL",   "http://127.0.0.1:8001")
GATEWAY_TOKEN = os.getenv("GATEWAY_TOKEN", "secret-gateway-token")
DATABASE_URL  = os.getenv(
    "DATABASE_URL",
    "postgresql://krystal_user:krystal2024@localhost:5432/krystal_palace"
)
OM_NUMERO     = os.getenv("OM_NUMERO_RECEPTEUR", "+237655448731")

# Tarifs FCFA / nuit
TARIFS = {
    "Standard":       25_000,
    "Superieure":     45_000,
    "Suite Prestige": 95_000,
}

# Règles annulation
DELAI_ANNULATION_GRATUITE = 3   # jours avant arrivée → annulation 100% remboursée
PENALITE_PAR_JOUR         = 0.20  # 20% du total par jour de dépassement
LIMITE_ANNULATION_APRES_ARRIVEE = 3  # jours après arrivée → annulation bloquée

# ══════════════════════════════════════════════════════════════════════════════
# AUTHENTIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def verifier_admin(credentials: HTTPBasicCredentials = Depends(security)):
    ok = (
        secrets.compare_digest(credentials.username.encode(), ADMIN_USER.encode())
        and secrets.compare_digest(credentials.password.encode(), ADMIN_PASS.encode())
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiants incorrects",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username

# ══════════════════════════════════════════════════════════════════════════════
# BASE DE DONNÉES POSTGRESQL
# ══════════════════════════════════════════════════════════════════════════════

def get_conn():
    """Retourne une connexion PostgreSQL avec RealDictCursor."""
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    conn.autocommit = False
    return conn


def init_db():
    """Crée les tables si elles n'existent pas."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS clients (
                    id          SERIAL PRIMARY KEY,
                    nom         VARCHAR(100) NOT NULL,
                    prenom      VARCHAR(100) NOT NULL,
                    cni         VARCHAR(50)  NOT NULL UNIQUE,
                    telephone   VARCHAR(25)  NOT NULL,
                    email       VARCHAR(150),
                    nationalite VARCHAR(80),
                    cree_le     TIMESTAMP DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS reservations (
                    id              SERIAL PRIMARY KEY,
                    ref             VARCHAR(30)  NOT NULL UNIQUE,
                    client_id       INTEGER REFERENCES clients(id) ON DELETE SET NULL,
                    client_nom      VARCHAR(200) NOT NULL,
                    type_chambre    VARCHAR(50)  NOT NULL,
                    ref_chambre     VARCHAR(20)  NOT NULL DEFAULT 'A attribuer',
                    ref_climatisation VARCHAR(20),
                    arrivee         DATE         NOT NULL,
                    depart          DATE         NOT NULL,
                    nuits           INTEGER      NOT NULL,
                    total           INTEGER      NOT NULL,
                    montant_rembourse INTEGER    DEFAULT 0,
                    observations    TEXT,
                    statut          VARCHAR(30)  NOT NULL DEFAULT 'Confirmee',
                    paiement_sim    BOOLEAN      DEFAULT FALSE,
                    paiement_mode   VARCHAR(50),
                    paiement_statut VARCHAR(50)  NOT NULL DEFAULT 'En attente',
                    reference_om    VARCHAR(60),
                    facture_pdf     TEXT,
                    cree_le         TIMESTAMP    DEFAULT NOW(),
                    modifie_le      TIMESTAMP    DEFAULT NOW()
                );

                CREATE TABLE IF NOT EXISTS annulations (
                    id              SERIAL PRIMARY KEY,
                    reservation_id  INTEGER REFERENCES reservations(id) ON DELETE CASCADE,
                    ref             VARCHAR(30) NOT NULL,
                    date_annulation TIMESTAMP DEFAULT NOW(),
                    jours_penalite  INTEGER NOT NULL DEFAULT 0,
                    taux_penalite   NUMERIC(5,2) NOT NULL DEFAULT 0,
                    montant_penalite INTEGER NOT NULL DEFAULT 0,
                    montant_rembourse INTEGER NOT NULL DEFAULT 0,
                    motif           TEXT
                );

                CREATE TABLE IF NOT EXISTS modifications (
                    id              SERIAL PRIMARY KEY,
                    reservation_id  INTEGER REFERENCES reservations(id) ON DELETE CASCADE,
                    ref             VARCHAR(30) NOT NULL,
                    date_modif      TIMESTAMP DEFAULT NOW(),
                    ancien_arrivee  DATE,
                    nouvel_arrivee  DATE,
                    ancien_depart   DATE,
                    nouvel_depart   DATE,
                    ancien_total    INTEGER,
                    nouveau_total   INTEGER,
                    observations    TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_res_statut   ON reservations(statut);
                CREATE INDEX IF NOT EXISTS idx_res_arrivee  ON reservations(arrivee);
                CREATE INDEX IF NOT EXISTS idx_res_ref      ON reservations(ref);
                CREATE INDEX IF NOT EXISTS idx_cli_cni      ON clients(cni);
            """)
        conn.commit()
        logger.info("Base PostgreSQL initialisée ✓")
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur init_db : {e}")
        raise
    finally:
        conn.close()


init_db()

# ══════════════════════════════════════════════════════════════════════════════
# LOGIQUE PÉNALITÉ / ANNULATION
# ══════════════════════════════════════════════════════════════════════════════

def calculer_penalite(arrivee: date, total: int, paiement_confirme: bool) -> dict:
    """
    Calcule la pénalité d'annulation selon les règles :
      - Annulation avant J-3 (DELAI_ANNULATION_GRATUITE) : 0% pénalité → 100% remboursé
      - Annulation entre J-3 et J+3 : 20% par jour dépassé
      - Annulation après J+3 : BLOQUÉE (retourne blocked=True)
      - Si paiement non confirmé : 0 FCFA remboursé (rien à rembourser)

    Retourne :
      {
        "bloque": bool,
        "gratuit": bool,
        "jours_penalite": int,
        "taux_penalite": float,   # ex: 0.40 pour 2 jours
        "montant_penalite": int,
        "montant_rembourse": int,
        "message": str
      }
    """
    aujourd_hui = date.today()
    date_limite_gratuit  = arrivee - timedelta(days=DELAI_ANNULATION_GRATUITE)
    date_limite_annuler  = arrivee + timedelta(days=LIMITE_ANNULATION_APRES_ARRIVEE)

    # Annulation bloquée après J+3 de l'arrivée
    if aujourd_hui > date_limite_annuler:
        return {
            "bloque": True,
            "gratuit": False,
            "jours_penalite": 0,
            "taux_penalite": 0.0,
            "montant_penalite": 0,
            "montant_rembourse": 0,
            "message": (
                f"Annulation impossible : le délai de {LIMITE_ANNULATION_APRES_ARRIVEE} jours "
                f"après la date d'arrivée ({arrivee.strftime('%d/%m/%Y')}) est dépassé."
            ),
        }

    if not paiement_confirme:
        return {
            "bloque": False,
            "gratuit": True,
            "jours_penalite": 0,
            "taux_penalite": 0.0,
            "montant_penalite": 0,
            "montant_rembourse": 0,
            "message": "Réservation annulée sans pénalité (paiement non confirmé).",
        }

    # Annulation gratuite
    if aujourd_hui <= date_limite_gratuit:
        return {
            "bloque": False,
            "gratuit": True,
            "jours_penalite": 0,
            "taux_penalite": 0.0,
            "montant_penalite": 0,
            "montant_rembourse": total,
            "message": (
                f"Annulation gratuite — remboursement intégral de "
                f"{total:,} FCFA sur votre compte Orange Money."
            ),
        }

    # Annulation avec pénalité
    jours = (aujourd_hui - date_limite_gratuit).days
    taux  = min(jours * PENALITE_PAR_JOUR, 1.0)
    penalite  = int(total * taux)
    rembourse = max(total - penalite, 0)

    return {
        "bloque": False,
        "gratuit": False,
        "jours_penalite": jours,
        "taux_penalite": taux,
        "montant_penalite": penalite,
        "montant_rembourse": rembourse,
        "message": (
            f"Pénalité de {int(taux*100)}% ({jours} jour(s) de dépassement × 20%) = "
            f"{penalite:,} FCFA. "
            f"Remboursement : {rembourse:,} FCFA sur Orange Money."
        ),
    }


def peut_modifier(arrivee: date) -> bool:
    """
    La modification est autorisée uniquement avant le délai de pénalité.
    Soit : avant J-3 par rapport à la date d'arrivée.
    """
    return date.today() < arrivee - timedelta(days=DELAI_ANNULATION_GRATUITE)

# ══════════════════════════════════════════════════════════════════════════════
# WEBHOOK BACNET
# ══════════════════════════════════════════════════════════════════════════════

def envoyer_webhook(payload: dict):
    try:
        with httpx.Client(timeout=5.0) as cl:
            resp = cl.post(
                f"{GATEWAY_URL}/webhook/reservation",
                json=payload,
                headers={"X-Gateway-Token": GATEWAY_TOKEN},
            )
            resp.raise_for_status()
            logger.info(f"[WEBHOOK] ✓ {payload['evenement']} | {payload['ref']}")
    except Exception as e:
        logger.warning(f"[WEBHOOK] ✗ Gateway indisponible : {e}")

# ══════════════════════════════════════════════════════════════════════════════
# SCHÉMAS PYDANTIC
# ══════════════════════════════════════════════════════════════════════════════

class ReservationPublique(BaseModel):
    nom:          str
    prenom:       str
    cni:          str
    telephone:    str
    email:        Optional[str] = None
    nationalite:  Optional[str] = None
    type_chambre: str
    arrivee:      str
    depart:       str
    observations: Optional[str] = None


class PaiementOrangeMoney(BaseModel):
    reservation_id:   int
    mode:             str
    reference_om:     str
    numero_recepteur: str
    montant:          int


class ModificationReservation(BaseModel):
    ref:         str
    cni:         str
    nouvel_arrivee: str
    nouvel_depart:  str
    observations: Optional[str] = None


class DemandeAnnulation(BaseModel):
    ref:  str
    cni:  str
    motif: Optional[str] = None


class ClientCreate(BaseModel):
    nom:         str
    prenom:      str
    cni:         str
    telephone:   str
    email:       Optional[str] = None
    nationalite: Optional[str] = None


class ReservationUpdate(BaseModel):
    statut:           str
    ref_chambre:      Optional[str] = None
    ref_climatisation: Optional[str] = None
    reference_om:     Optional[str] = None


class EnregistrementManuel(BaseModel):
    nom:          str
    prenom:       str
    cni:          str
    telephone:    str
    email:        Optional[str] = None
    nationalite:  Optional[str] = None
    type_chambre: str
    arrivee:      str
    depart:       str
    ref_chambre:  Optional[str] = None
    ref_climatisation: Optional[str] = None
    observations: Optional[str] = None
    statut:       Optional[str] = "Confirmee"
    reference_om: Optional[str] = None

# ══════════════════════════════════════════════════════════════════════════════
# PAGES HTML
# ══════════════════════════════════════════════════════════════════════════════

TPL = Path(__file__).parent / "templates"

# En développement, on évite que le navigateur mette en cache une ancienne
# version de admin.html/client.html pendant que vous itérez dessus.
_NO_CACHE = {"Cache-Control": "no-store, no-cache, must-revalidate"}


@app.get("/", response_class=HTMLResponse, tags=["Pages"])
def page_client():
    return HTMLResponse(open(TPL / "client.html", encoding="utf-8").read(), headers=_NO_CACHE)


@app.get("/admin", response_class=HTMLResponse, tags=["Pages"])
def page_admin():
    return HTMLResponse(open(TPL / "admin.html", encoding="utf-8").read(), headers=_NO_CACHE)

# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — RÉSERVATION
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/reserver", status_code=201, tags=["Reservation"])
def reserver(data: ReservationPublique, bg: BackgroundTasks):
    """
    Étapes 1-3 du wizard client :
    Crée client + réservation, retourne ref/total/nuits.
    """
    if data.type_chambre not in TARIFS:
        raise HTTPException(400, f"Type invalide. Valeurs : {list(TARIFS.keys())}")

    try:
        arr = date.fromisoformat(data.arrivee)
        dep = date.fromisoformat(data.depart)
    except ValueError:
        raise HTTPException(400, "Format de date invalide (YYYY-MM-DD)")

    nuits = (dep - arr).days
    if nuits <= 0:
        raise HTTPException(400, "Date de départ doit être après l'arrivée")

    total       = nuits * TARIFS[data.type_chambre]
    ref         = "RES-" + datetime.now().strftime("%Y%m%d%H%M%S")
    nom_complet = f"{data.nom.upper()} {data.prenom}"

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            # UPSERT client
            cur.execute("""
                INSERT INTO clients (nom, prenom, cni, telephone, email, nationalite)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT(cni) DO UPDATE SET
                    telephone = EXCLUDED.telephone,
                    email     = COALESCE(EXCLUDED.email, clients.email)
                RETURNING id
            """, (data.nom, data.prenom, data.cni, data.telephone, data.email, data.nationalite))
            client_id = cur.fetchone()["id"]

            cur.execute("""
                INSERT INTO reservations
                    (ref, client_id, client_nom, type_chambre, arrivee, depart,
                     nuits, total, observations)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            """, (ref, client_id, nom_complet, data.type_chambre,
                  data.arrivee, data.depart, nuits, total, data.observations))
            res_id = cur.fetchone()["id"]
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"Erreur reserver : {e}")
        raise HTTPException(500, str(e))
    finally:
        conn.close()

    bg.add_task(envoyer_webhook, {
        "evenement": "RESERVATION_CONFIRMEE", "ref": ref,
        "type_chambre": data.type_chambre, "numero": "A attribuer",
        "arrivee": data.arrivee, "depart": data.depart,
    })

    return {"id": res_id, "ref": ref, "total": total, "nuits": nuits,
            "message": "Réservation confirmée"}


@app.post("/api/paiement", tags=["Paiement"])
def enregistrer_paiement(data: PaiementOrangeMoney, bg: BackgroundTasks):
    """Étape 4 — enregistre la référence Orange Money."""
    numero_n = data.numero_recepteur.replace(" ", "").replace("-", "")
    if numero_n not in ("+237655448731", "237655448731", "655448731"):
        raise HTTPException(400, "Numéro de réception invalide")
    if not data.reference_om or len(data.reference_om.strip()) < 6:
        raise HTTPException(400, "Référence OM invalide")

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, ref, statut, type_chambre, ref_chambre, total "
                "FROM reservations WHERE id = %s",
                (data.reservation_id,)
            )
            r = cur.fetchone()
            if not r:
                raise HTTPException(404, "Réservation introuvable")
            if abs(r["total"] - data.montant) > 1:
                raise HTTPException(400, f"Montant incorrect : attendu {r['total']} FCFA")

            cur.execute("""
                UPDATE reservations SET
                    paiement_statut = 'Orange Money confirme',
                    paiement_mode   = 'Orange Money USSD',
                    paiement_sim    = TRUE,
                    reference_om    = %s
                WHERE id = %s
            """, (data.reference_om.strip().upper(), data.reservation_id))
        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()

    if r["statut"] == "En cours":
        bg.add_task(envoyer_webhook, {
            "evenement": "CHECK_IN", "ref": r["ref"],
            "type_chambre": r["type_chambre"],
            "numero": r["ref_chambre"], "arrivee": "", "depart": "",
        })

    return {
        "success": True, "ref": r["ref"],
        "reference_om": data.reference_om.strip().upper(),
        "montant": r["total"], "recepteur": OM_NUMERO,
    }

# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — PAGE 0 : VÉRIFIER RÉSERVATION EXISTANTE
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/ma-reservation", tags=["Page 0"])
def ma_reservation(ref: str, cni: str):
    """
    Page 0 : vérifie qu'un client a bien une réservation payée et retourne
    ses droits (peut_annuler, peut_modifier, info pénalité).
    Appelé quand le client entre sa référence + CNI.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.*, c.nom, c.prenom, c.cni, c.telephone, c.email
                FROM reservations r
                JOIN clients c ON c.id = r.client_id
                WHERE r.ref = %s AND c.cni = %s
            """, (ref.upper(), cni.upper()))
            r = cur.fetchone()
    finally:
        conn.close()

    if not r:
        raise HTTPException(404, "Réservation introuvable — vérifiez votre référence et CNI")

    # Paiement non confirmé → pas de page 0
    if not r["paiement_sim"]:
        raise HTTPException(403, "Paiement non confirmé — accès à l'espace client indisponible")

    arrivee_d = r["arrivee"]
    if isinstance(arrivee_d, str):
        arrivee_d = date.fromisoformat(arrivee_d)

    penalite_info = calculer_penalite(arrivee_d, r["total"], r["paiement_sim"])
    modif_ok      = peut_modifier(arrivee_d) and r["statut"] not in ("Annulee", "Terminee")
    annul_ok      = not penalite_info["bloque"] and r["statut"] not in ("Annulee", "Terminee")

    return {
        "id":            r["id"],
        "ref":           r["ref"],
        "client_nom":    r["client_nom"],
        "type_chambre":  r["type_chambre"],
        "arrivee":       str(r["arrivee"]),
        "depart":        str(r["depart"]),
        "nuits":         r["nuits"],
        "total":         r["total"],
        "statut":        r["statut"],
        "reference_om":  r["reference_om"],
        "peut_annuler":  annul_ok,
        "peut_modifier": modif_ok,
        "penalite":      penalite_info,
    }

# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — SIMULER PÉNALITÉ (avant confirmation annulation)
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/simuler-annulation", tags=["Page 0"])
def simuler_annulation(ref: str, cni: str):
    """
    Retourne les détails de pénalité AVANT que le client confirme l'annulation.
    Utilisé pour afficher le message d'avertissement sur le frontend.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.ref, r.arrivee, r.total, r.paiement_sim, r.statut
                FROM reservations r
                JOIN clients c ON c.id = r.client_id
                WHERE r.ref = %s AND c.cni = %s
            """, (ref.upper(), cni.upper()))
            r = cur.fetchone()
    finally:
        conn.close()

    if not r:
        raise HTTPException(404, "Réservation introuvable")
    if r["statut"] in ("Annulee", "Terminee"):
        raise HTTPException(400, f"Réservation déjà {r['statut']}")

    arrivee_d = r["arrivee"]
    if isinstance(arrivee_d, str):
        arrivee_d = date.fromisoformat(arrivee_d)

    return calculer_penalite(arrivee_d, r["total"], r["paiement_sim"])

# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — ANNULER RÉSERVATION
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/annuler", tags=["Page 0"])
def annuler_reservation(data: DemandeAnnulation, bg: BackgroundTasks):
    """
    Annule une réservation avec calcul automatique des pénalités.
    Si pénalité > 0 : le frontend doit avoir affiché le message d'avertissement.
    Le remboursement Orange Money est simulé (enregistré en base).
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.ref, r.arrivee, r.total, r.paiement_sim,
                       r.statut, r.type_chambre, r.ref_chambre
                FROM reservations r
                JOIN clients c ON c.id = r.client_id
                WHERE r.ref = %s AND c.cni = %s
            """, (data.ref.upper(), data.cni.upper()))
            r = cur.fetchone()

            if not r:
                raise HTTPException(404, "Réservation introuvable")
            if r["statut"] in ("Annulee", "Terminee"):
                raise HTTPException(400, f"Réservation déjà {r['statut']}")

            arrivee_d = r["arrivee"]
            if isinstance(arrivee_d, str):
                arrivee_d = date.fromisoformat(arrivee_d)

            pen = calculer_penalite(arrivee_d, r["total"], r["paiement_sim"])
            if pen["bloque"]:
                raise HTTPException(403, pen["message"])

            # Mettre à jour statut + montant remboursé
            cur.execute("""
                UPDATE reservations SET
                    statut           = 'Annulee',
                    montant_rembourse = %s,
                    modifie_le       = NOW()
                WHERE id = %s
            """, (pen["montant_rembourse"], r["id"]))

            # Enregistrer dans la table annulations
            cur.execute("""
                INSERT INTO annulations
                    (reservation_id, ref, jours_penalite, taux_penalite,
                     montant_penalite, montant_rembourse, motif)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (r["id"], r["ref"], pen["jours_penalite"], pen["taux_penalite"],
                  pen["montant_penalite"], pen["montant_rembourse"], data.motif))

        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()

    # Webhook BACnet — arrêter la clim si chambre attribuée
    if r["ref_chambre"] and r["ref_chambre"] != "A attribuer":
        bg.add_task(envoyer_webhook, {
            "evenement": "ANNULATION", "ref": r["ref"],
            "type_chambre": r["type_chambre"],
            "numero": r["ref_chambre"], "arrivee": "", "depart": "",
        })

    return {
        "success": True,
        "ref": r["ref"],
        "statut": "Annulee",
        "penalite": pen,
        "message": pen["message"],
    }

# ══════════════════════════════════════════════════════════════════════════════
# API PUBLIQUE — MODIFIER RÉSERVATION (dates seulement, page 2)
# ══════════════════════════════════════════════════════════════════════════════

@app.post("/api/modifier", tags=["Page 0"])
def modifier_reservation_client(data: ModificationReservation, bg: BackgroundTasks):
    """
    Modification des dates uniquement (page 2, pas de changement de chambre).
    Autorisée uniquement avant J-3 (délai de pénalité).
    Retourne un nouveau total + nouvelle facture.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.ref, r.arrivee, r.depart, r.total, r.nuits,
                       r.type_chambre, r.paiement_sim, r.statut,
                       r.ref_chambre, c.nom, c.prenom, c.cni, c.telephone, c.email
                FROM reservations r
                JOIN clients c ON c.id = r.client_id
                WHERE r.ref = %s AND c.cni = %s
            """, (data.ref.upper(), data.cni.upper()))
            r = cur.fetchone()

            if not r:
                raise HTTPException(404, "Réservation introuvable")
            if r["statut"] in ("Annulee", "Terminee"):
                raise HTTPException(400, f"Impossible de modifier une réservation {r['statut']}")

            arrivee_d = r["arrivee"]
            if isinstance(arrivee_d, str):
                arrivee_d = date.fromisoformat(arrivee_d)

            if not peut_modifier(arrivee_d):
                raise HTTPException(403, (
                    "Modification impossible : vous êtes dans la période de pénalité "
                    f"(moins de {DELAI_ANNULATION_GRATUITE} jours avant l'arrivée)."
                ))

            try:
                n_arr = date.fromisoformat(data.nouvel_arrivee)
                n_dep = date.fromisoformat(data.nouvel_depart)
            except ValueError:
                raise HTTPException(400, "Format de date invalide")

            n_nuits = (n_dep - n_arr).days
            if n_nuits <= 0:
                raise HTTPException(400, "Le départ doit être après l'arrivée")

            n_total  = n_nuits * TARIFS[r["type_chambre"]]
            diff     = n_total - r["total"]
            new_ref  = r["ref"] + "-MOD"

            # Sauvegarder la modification
            cur.execute("""
                INSERT INTO modifications
                    (reservation_id, ref, ancien_arrivee, nouvel_arrivee,
                     ancien_depart, nouvel_depart, ancien_total, nouveau_total, observations)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (r["id"], r["ref"], r["arrivee"], n_arr,
                  r["depart"], n_dep, r["total"], n_total, data.observations))

            # Mettre à jour la réservation
            cur.execute("""
                UPDATE reservations SET
                    arrivee    = %s,
                    depart     = %s,
                    nuits      = %s,
                    total      = %s,
                    observations = COALESCE(%s, observations),
                    modifie_le = NOW()
                WHERE id = %s
            """, (n_arr, n_dep, n_nuits, n_total, data.observations, r["id"]))

        conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()

    # Re-planifier le préconditionning
    if r["ref_chambre"] and r["ref_chambre"] != "A attribuer":
        bg.add_task(envoyer_webhook, {
            "evenement": "MODIFICATION", "ref": r["ref"],
            "type_chambre": r["type_chambre"],
            "numero": r["ref_chambre"],
            "arrivee": str(n_arr), "depart": str(n_dep),
        })

    return {
        "success": True,
        "ref": r["ref"],
        "type_chambre": r["type_chambre"],
        "nouvel_arrivee": str(n_arr),
        "nouvel_depart": str(n_dep),
        "nuits": n_nuits,
        "nouveau_total": n_total,
        "difference": diff,
        "message": f"Réservation modifiée — nouveau total : {n_total:,} FCFA",
    }

# ══════════════════════════════════════════════════════════════════════════════
# API ADMIN
# ══════════════════════════════════════════════════════════════════════════════

@app.get("/api/admin/stats", tags=["Admin"])
def stats(admin=Depends(verifier_admin)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM clients")
            nb_cl = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM reservations")
            nb_res = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM reservations WHERE statut = 'En cours'")
            en_cours = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM reservations WHERE statut = 'Confirmee'")
            conf = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM reservations WHERE statut = 'Terminee'")
            term = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM reservations WHERE statut = 'Annulee'")
            annul = cur.fetchone()["n"]
            cur.execute(
                "SELECT COALESCE(SUM(total),0) AS s FROM reservations "
                "WHERE statut NOT IN ('Annulee')"
            )
            revenus = cur.fetchone()["s"]
            cur.execute("SELECT COUNT(*) AS n FROM reservations WHERE paiement_sim = TRUE")
            pay = cur.fetchone()["n"]
    finally:
        conn.close()

    return {
        "clients": nb_cl, "reservations": nb_res, "en_cours": en_cours,
        "confirmees": conf, "terminees": term, "annulees": annul,
        "revenus": revenus, "paiements_sim": pay,
    }


@app.get("/api/admin/reservations", tags=["Admin"])
def liste_reservations(admin=Depends(verifier_admin)):
    """Liste complète avec toutes les colonnes admin (ref_chambre, ref_clim, etc.)."""
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    r.id, r.ref, r.client_id, r.client_nom,
                    c.prenom, c.cni, c.telephone, c.email, c.nationalite,
                    c.cree_le AS client_depuis,
                    r.type_chambre, r.ref_chambre, r.ref_climatisation,
                    r.arrivee::text, r.depart::text, r.nuits, r.total,
                    r.montant_rembourse, r.observations, r.statut,
                    r.paiement_statut, r.paiement_mode, r.paiement_sim,
                    r.reference_om,
                    r.cree_le::text, r.modifie_le::text
                FROM reservations r
                LEFT JOIN clients c ON c.id = r.client_id
                ORDER BY r.id DESC
            """)
            return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


@app.get("/api/admin/clients", tags=["Admin"])
def liste_clients(admin=Depends(verifier_admin)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM clients ORDER BY nom, prenom")
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


@app.post("/api/admin/clients", status_code=201, tags=["Admin"])
def creer_client(data: ClientCreate, admin=Depends(verifier_admin)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clients (nom, prenom, cni, telephone, email, nationalite)
                VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
            """, (data.nom, data.prenom, data.cni, data.telephone, data.email, data.nationalite))
            res_id = cur.fetchone()["id"]
        conn.commit()
        return {"id": res_id, "message": "Client créé"}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(400, f"CNI '{data.cni}' déjà existante")
    finally:
        conn.close()


@app.delete("/api/admin/clients/{client_id}", tags=["Admin"])
def supprimer_client(client_id: int, admin=Depends(verifier_admin)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM clients WHERE id = %s", (client_id,))
        conn.commit()
    finally:
        conn.close()
    return {"message": "Client supprimé"}


@app.patch("/api/admin/reservations/{res_id}", tags=["Admin"])
def modifier_res_admin(res_id: int, data: ReservationUpdate,
                       admin=Depends(verifier_admin),
                       bg: BackgroundTasks = BackgroundTasks()):
    """
    Admin : mise à jour statut + ref_chambre + ref_climatisation.
    Check-In (vert) → déclenche HVAC via BACnet.
    Check-Out (rouge) → arrête HVAC.
    """
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            sets  = ["statut = %s", "modifie_le = NOW()"]
            params = [data.statut]

            if data.ref_chambre:
                sets.append("ref_chambre = %s")
                params.append(data.ref_chambre)
            if data.ref_climatisation:
                sets.append("ref_climatisation = %s")
                params.append(data.ref_climatisation)
            if data.reference_om:
                sets += ["reference_om = %s", "paiement_sim = TRUE",
                         "paiement_mode = 'Orange Money USSD'",
                         "paiement_statut = 'Orange Money confirme'"]
                params.append(data.reference_om.strip().upper())

            params.append(res_id)
            cur.execute(
                f"UPDATE reservations SET {', '.join(sets)} WHERE id = %s RETURNING *",
                params
            )
            r = cur.fetchone()
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()

    if r:
        evt_map = {"En cours": "CHECK_IN", "Terminee": "CHECK_OUT", "Annulee": "ANNULATION"}
        evt = evt_map.get(data.statut)
        if evt:
            bg.add_task(envoyer_webhook, {
                "evenement": evt, "ref": r["ref"],
                "type_chambre": r["type_chambre"],
                "numero": data.ref_chambre or r["ref_chambre"],
                "arrivee": str(r["arrivee"]), "depart": str(r["depart"]),
            })

    return {"message": f"Réservation mise à jour — {data.statut}"}


@app.delete("/api/admin/reservations/{res_id}", tags=["Admin"])
def supprimer_reservation(res_id: int, admin=Depends(verifier_admin)):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM reservations WHERE id = %s", (res_id,))
        conn.commit()
    finally:
        conn.close()
    return {"message": "Réservation supprimée"}


@app.post("/api/admin/enregistrer", status_code=201, tags=["Admin"])
def enregistrement_manuel(data: EnregistrementManuel,
                          bg: BackgroundTasks,
                          admin=Depends(verifier_admin)):
    if data.type_chambre not in TARIFS:
        raise HTTPException(400, f"Type invalide. Valeurs : {list(TARIFS.keys())}")
    try:
        arr = date.fromisoformat(data.arrivee)
        dep = date.fromisoformat(data.depart)
    except ValueError:
        raise HTTPException(400, "Format de date invalide")

    nuits = (dep - arr).days
    if nuits <= 0:
        raise HTTPException(400, "Départ doit être après arrivée")

    total       = nuits * TARIFS[data.type_chambre]
    ref         = "RES-MAN-" + datetime.now().strftime("%Y%m%d%H%M%S")
    nom_complet = f"{data.nom.upper()} {data.prenom}"

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO clients (nom, prenom, cni, telephone, email, nationalite)
                VALUES (%s,%s,%s,%s,%s,%s)
                ON CONFLICT(cni) DO UPDATE SET telephone=EXCLUDED.telephone
                RETURNING id
            """, (data.nom, data.prenom, data.cni, data.telephone, data.email, data.nationalite))
            client_id = cur.fetchone()["id"]

            cur.execute("""
                INSERT INTO reservations
                    (ref, client_id, client_nom, type_chambre, ref_chambre, ref_climatisation,
                     arrivee, depart, nuits, total, observations, statut,
                     paiement_sim, paiement_mode, paiement_statut, reference_om)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (ref, client_id, nom_complet, data.type_chambre,
                  data.ref_chambre or "A attribuer", data.ref_climatisation,
                  data.arrivee, data.depart, nuits, total,
                  data.observations, data.statut or "Confirmee",
                  bool(data.reference_om),
                  "Orange Money USSD" if data.reference_om else None,
                  "Orange Money confirme" if data.reference_om else "En attente",
                  data.reference_om.strip().upper() if data.reference_om else None))
            res_id = cur.fetchone()["id"]
        conn.commit()
    except Exception as e:
        conn.rollback()
        raise HTTPException(500, str(e))
    finally:
        conn.close()

    evt = "CHECK_IN" if data.statut == "En cours" else "RESERVATION_CONFIRMEE"
    bg.add_task(envoyer_webhook, {
        "evenement": evt, "ref": ref,
        "type_chambre": data.type_chambre,
        "numero": data.ref_chambre or "A attribuer",
        "arrivee": data.arrivee, "depart": data.depart,
    })

    return {"ref": ref, "total": total, "nuits": nuits, "id": res_id,
            "message": f"Enregistrement effectué — {nom_complet} · {ref}"}


@app.get("/api/health", tags=["Sante"])
def health():
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS n FROM reservations")
            nb_res = cur.fetchone()["n"]
            cur.execute("SELECT COUNT(*) AS n FROM clients")
            nb_cl = cur.fetchone()["n"]
        conn.close()
        return {"status": "ok", "db": "postgresql", "reservations": nb_res,
                "clients": nb_cl, "version": "7.0.0"}
    except Exception as e:
        raise HTTPException(500, f"DB inaccessible : {e}")
