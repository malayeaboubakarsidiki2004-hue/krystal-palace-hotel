"""
scheduler.py — Planification des démarrages et arrêts HVAC
Utilise APScheduler pour déclencher les actions BACnet au bon moment.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger

from .config import (
    MINUTES_AVANT_ARRIVEE,
    MINUTES_APRES_DEPART,
    TEMP_PRECOOLING,
    TEMP_OCCUPIED,
    MODE_COOLING,
)
from .bacnet_client import demarrer_chambre, arreter_chambre

logger = logging.getLogger("scheduler")

# Scheduler global (démarré une fois dans main.py)
scheduler = AsyncIOScheduler(timezone="Africa/Douala")


def _job_id_precooling(ref: str) -> str:
    return f"precool_{ref}"

def _job_id_arret(ref: str) -> str:
    return f"arret_{ref}"


def planifier_reservation(ref: str, numero: str, arrivee: str, depart: str):
    """
    Planifie deux jobs pour une réservation :
      - Job 1 : démarrage MINUTES_AVANT_ARRIVEE avant l'heure d'arrivée (J à 14h par défaut)
      - Job 2 : arrêt MINUTES_APRES_DEPART après le checkout (J à 12h par défaut)
    """
    # Heure d'arrivée standard : 14h00 le jour d'arrivée
    dt_arrivee = datetime.fromisoformat(arrivee).replace(hour=14, minute=0, second=0)
    # Heure de checkout standard : 12h00 le jour de départ
    dt_depart  = datetime.fromisoformat(depart).replace(hour=12, minute=0, second=0)

    t_demarrage = dt_arrivee  - timedelta(minutes=MINUTES_AVANT_ARRIVEE)
    t_arret     = dt_depart   + timedelta(minutes=MINUTES_APRES_DEPART)

    now = datetime.now(tz=scheduler.timezone)

    # ── Job de démarrage (pré-refroidissement) ──
    if t_demarrage > now.replace(tzinfo=None):
        scheduler.add_job(
            _job_demarrer,
            trigger=DateTrigger(run_date=t_demarrage),
            args=[ref, numero, TEMP_PRECOOLING, MODE_COOLING],
            id=_job_id_precooling(ref),
            replace_existing=True,
            misfire_grace_time=300,   # tolère jusqu'à 5 min de retard (ex: redémarrage Pi)
        )
        logger.info(f"[Scheduler] Job démarrage planifié → chambre {numero} le {t_demarrage}")
    else:
        logger.warning(f"[Scheduler] Heure de démarrage dépassée pour {ref} — job ignoré")

    # ── Job d'arrêt ──
    if t_arret > now.replace(tzinfo=None):
        scheduler.add_job(
            _job_arreter,
            trigger=DateTrigger(run_date=t_arret),
            args=[ref, numero],
            id=_job_id_arret(ref),
            replace_existing=True,
            misfire_grace_time=600,
        )
        logger.info(f"[Scheduler] Job arrêt planifié → chambre {numero} le {t_arret}")


def annuler_jobs(ref: str):
    """Supprime les deux jobs liés à une réservation (en cas d'annulation)."""
    for jid in [_job_id_precooling(ref), _job_id_arret(ref)]:
        try:
            scheduler.remove_job(jid)
            logger.info(f"[Scheduler] Job {jid} annulé")
        except Exception:
            pass   # job inexistant (déjà exécuté ou jamais créé)


def demarrage_immediat(ref: str, numero: str):
    """
    Déclenche immédiatement le démarrage HVAC.
    Appelé quand l'admin passe le statut à 'En cours' manuellement.
    """
    asyncio.create_task(_job_demarrer(ref, numero, TEMP_OCCUPIED, MODE_COOLING))


def arret_immediat(ref: str, numero: str):
    """Déclenche immédiatement l'arrêt HVAC (checkout manuel)."""
    asyncio.create_task(_job_arreter(ref, numero))


# ── Fonctions exécutées par APScheduler ─────────────────────────────────────

async def _job_demarrer(ref: str, numero: str, temp: float, mode: int):
    logger.info(f"[Job] → Démarrage HVAC chambre {numero} (réf {ref}) à {temp}°C")
    success = await demarrer_chambre(numero, temp, mode)
    if not success:
        logger.error(f"[Job] Échec démarrage chambre {numero} — vérifier la connexion BACnet")


async def _job_arreter(ref: str, numero: str):
    logger.info(f"[Job] → Arrêt HVAC chambre {numero} (réf {ref})")
    success = await arreter_chambre(numero)
    if not success:
        logger.error(f"[Job] Échec arrêt chambre {numero}")
