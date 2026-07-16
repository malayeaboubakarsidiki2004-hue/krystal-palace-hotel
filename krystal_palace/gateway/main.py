"""
main.py — Passerelle BACnet Krystal Palace Hôtel Yaoundé
Lancer sur le même PC Windows avec :
    python -m uvicorn main:app --host 127.0.0.1 --port 8001 --reload
Simulateur BACnet : YABE (127.0.0.1:47808)
"""

import logging
from fastapi import FastAPI, HTTPException, Header
from pydantic import BaseModel
from typing import Optional
from contextlib import asynccontextmanager

from .config import GATEWAY_TOKEN
from .scheduler import (
    scheduler,
    planifier_reservation,
    annuler_jobs,
    demarrage_immediat,
    arret_immediat,
)
from .bacnet_client import demarrer_chambre, arreter_chambre

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("gateway")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    logger.info("=== Passerelle BACnet démarrée — YABE simulateur actif ===")
    yield
    scheduler.shutdown(wait=False)
    logger.info("=== Passerelle BACnet arrêtée ===")


app = FastAPI(title="Passerelle BACnet — Krystal Palace Yaoundé", lifespan=lifespan)


def verifier_token(x_gateway_token: str = Header(...)):
    if x_gateway_token != GATEWAY_TOKEN:
        raise HTTPException(status_code=403, detail="Token invalide")


class WebhookPayload(BaseModel):
    evenement: str        # RESERVATION_CONFIRMEE | CHECK_IN | CHECK_OUT | ANNULATION | MODIFICATION
    ref: str
    type_chambre: str
    numero: str
    arrivee: str          # YYYY-MM-DD (nouvelle date d'arrivée si MODIFICATION)
    depart: str           # YYYY-MM-DD (nouvelle date de départ si MODIFICATION)


@app.post("/webhook/reservation")
async def webhook_reservation(payload: WebhookPayload, token=verifier_token):
    evt = payload.evenement
    ref = payload.ref
    num = payload.numero

    logger.info(f"[Webhook] {evt} | {ref} | chambre {num} | {payload.arrivee} → {payload.depart}")

    if evt == "RESERVATION_CONFIRMEE":
        if num and num != "À attribuer":
            planifier_reservation(ref, num, payload.arrivee, payload.depart)
        else:
            logger.info(f"[Webhook] Chambre non encore attribuée pour {ref} — jobs différés")

    elif evt == "CHECK_IN":
        annuler_jobs(ref)
        if num and num != "À attribuer":
            demarrage_immediat(ref, num)
        else:
            logger.warning(f"[Webhook] CHECK_IN sans numéro de chambre pour {ref}")

    elif evt == "CHECK_OUT":
        if num and num != "À attribuer":
            arret_immediat(ref, num)
        annuler_jobs(ref)

    elif evt == "ANNULATION":
        annuler_jobs(ref)
        logger.info(f"[Webhook] Réservation {ref} annulée — jobs supprimés")

    elif evt == "MODIFICATION":
        # Les dates ont changé : on supprime les anciens jobs puis on
        # replanifie le pré-conditionnement / arrêt sur les nouvelles dates.
        annuler_jobs(ref)
        if num and num != "À attribuer":
            planifier_reservation(ref, num, payload.arrivee, payload.depart)
            logger.info(f"[Webhook] Réservation {ref} modifiée — jobs replanifiés sur {payload.arrivee} → {payload.depart}")
        else:
            logger.info(f"[Webhook] Réservation {ref} modifiée — chambre non encore attribuée, jobs différés")

    else:
        logger.warning(f"[Webhook] Événement inconnu : {evt}")

    return {"status": "ok", "evenement": evt, "ref": ref}


class NumeroPatch(BaseModel):
    ref: str
    numero: str
    arrivee: str
    depart: str


@app.post("/webhook/attribuer_chambre")
async def attribuer_chambre(payload: NumeroPatch, token=verifier_token):
    annuler_jobs(payload.ref)
    planifier_reservation(payload.ref, payload.numero, payload.arrivee, payload.depart)
    logger.info(f"[Webhook] Chambre attribuée : {payload.ref} → {payload.numero}")
    return {"status": "ok"}


@app.get("/health")
def health():
    jobs = [
        {"id": j.id, "next_run": str(j.next_run_time)}
        for j in scheduler.get_jobs()
    ]
    return {"status": "ok", "simulateur": "YABE BACnet/IP 127.0.0.1:47808", "jobs_planifies": len(jobs), "jobs": jobs}


@app.post("/test/demarrer/{numero}")
async def test_demarrer(numero: str, token=verifier_token):
    """Test manuel : démarre la climatisation d'une chambre via YABE."""
    from config import TEMP_OCCUPIED, MODE_COOLING
    ok = await demarrer_chambre(numero, TEMP_OCCUPIED, MODE_COOLING)
    return {"numero": numero, "resultat": "ok" if ok else "erreur", "simulateur": "YABE"}


@app.post("/test/arreter/{numero}")
async def test_arreter(numero: str, token=verifier_token):
    """Test manuel : éteint la climatisation d'une chambre via YABE."""
    ok = await arreter_chambre(numero)
    return {"numero": numero, "resultat": "ok" if ok else "erreur"}
