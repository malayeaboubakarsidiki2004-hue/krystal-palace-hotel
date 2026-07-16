"""
bacnet_client.py — Couche BACnet/IP via bacpypes3
Écrit et lit des objets sur l'simulateur YABE.
"""

import asyncio
import logging
from bacpypes3.app import Application
from bacpypes3.local.device import DeviceObject
from bacpypes3.pdu import Address
from bacpypes3.primitivedata import Real, Boolean, Unsigned
from bacpypes3.basetypes import PropertyIdentifier
from bacpypes3.apdu import ErrorRejectAbortNack

from .config import BACNET_DEVICE_IP, BACNET_DEVICE_PORT, BACNET_TIMEOUT, YABE_DEVICE_INSTANCE

logger = logging.getLogger("bacnet_client")

# Instance globale de l'application BACnet (initialisée une seule fois)
_app: Application | None = None


async def get_app() -> Application:
    global _app
    if _app is None:
        device_obj = DeviceObject(
            objectIdentifier=("device", 500),   # Device ID de la passerelle elle-même
            objectName="KrystalPalaceGateway",
            description="Passerelle BACnet Hôtel Krystal Palace",
            vendorIdentifier=999,
        )
        _app = Application(device_obj, "0.0.0.0")
        logger.info("Application BACnet initialisée (device 500)")
    return _app


def _itm_address() -> Address:
    return Address(f"{BACNET_DEVICE_IP}:{BACNET_DEVICE_PORT}")


async def write_analog_output(instance: int, value: float) -> bool:
    """Écrit une consigne de température sur un Analog Output de l'iTM."""
    app = await get_app()
    addr = _itm_address()
    try:
        await asyncio.wait_for(
            app.write_property(
                address=addr,
                objid=("analogOutput", instance),
                prop=PropertyIdentifier("presentValue"),
                value=Real(value),
                priority=8,          # Priorité manuelle (8 = supervision BMS)
            ),
            timeout=BACNET_TIMEOUT,
        )
        logger.info(f"[BACnet] AO[{instance}] ← {value}°C  OK")
        return True
    except (ErrorRejectAbortNack, asyncio.TimeoutError) as e:
        logger.error(f"[BACnet] AO[{instance}] écriture échouée : {e}")
        return False


async def write_binary_output(instance: int, on: bool) -> bool:
    """Allume (True) ou éteint (False) une unité via Binary Output."""
    app = await get_app()
    addr = _itm_address()
    try:
        await asyncio.wait_for(
            app.write_property(
                address=addr,
                objid=("binaryOutput", instance),
                prop=PropertyIdentifier("presentValue"),
                value=Boolean(on),
                priority=8,
            ),
            timeout=BACNET_TIMEOUT,
        )
        etat = "ON" if on else "OFF"
        logger.info(f"[BACnet] BO[{instance}] ← {etat}  OK")
        return True
    except (ErrorRejectAbortNack, asyncio.TimeoutError) as e:
        logger.error(f"[BACnet] BO[{instance}] écriture échouée : {e}")
        return False


async def write_multistate_value(instance: int, mode: int) -> bool:
    """Écrit le mode de fonctionnement (1=Auto, 2=Froid, 3=Chaud, 4=Vent.)."""
    app = await get_app()
    addr = _itm_address()
    try:
        await asyncio.wait_for(
            app.write_property(
                address=addr,
                objid=("multiStateValue", instance),
                prop=PropertyIdentifier("presentValue"),
                value=Unsigned(mode),
                priority=8,
            ),
            timeout=BACNET_TIMEOUT,
        )
        logger.info(f"[BACnet] MV[{instance}] ← mode {mode}  OK")
        return True
    except (ErrorRejectAbortNack, asyncio.TimeoutError) as e:
        logger.error(f"[BACnet] MV[{instance}] écriture échouée : {e}")
        return False


async def demarrer_chambre(numero: str, temp: float, mode: int) -> bool:
    """
    Lance la climatisation d'une chambre :
      1. Met le mode (Froid)
      2. Écrit la consigne de température
      3. Allume l'unité
    """
    from config import CHAMBRES_BACNET
    objs = CHAMBRES_BACNET.get(numero)
    if not objs:
        logger.warning(f"Chambre {numero} absente du mapping BACnet — vérifiez config.py")
        return False

    ok_mode = await write_multistate_value(objs["mv_mode"], mode)
    ok_temp = await write_analog_output(objs["ao_setpoint"], temp)
    ok_on   = await write_binary_output(objs["bo_power"], True)

    success = ok_mode and ok_temp and ok_on
    logger.info(f"[HVAC] Chambre {numero} démarrée : mode={mode} temp={temp}°C — {'OK' if success else 'ERREUR'}")
    return success


async def arreter_chambre(numero: str) -> bool:
    """Éteint la climatisation d'une chambre."""
    from config import CHAMBRES_BACNET
    objs = CHAMBRES_BACNET.get(numero)
    if not objs:
        logger.warning(f"Chambre {numero} absente du mapping BACnet")
        return False

    ok = await write_binary_output(objs["bo_power"], False)
    logger.info(f"[HVAC] Chambre {numero} arrêtée — {'OK' if ok else 'ERREUR'}")
    return ok


async def read_temperature(numero: str) -> float | None:
    """Lit la température courante d'une chambre (Analog Input si disponible)."""
    from config import CHAMBRES_BACNET
    objs = CHAMBRES_BACNET.get(numero)
    if not objs or "ai_temp" not in objs:
        return None
    app = await get_app()
    addr = _itm_address()
    try:
        result = await asyncio.wait_for(
            app.read_property(
                address=addr,
                objid=("analogInput", objs["ai_temp"]),
                prop=PropertyIdentifier("presentValue"),
            ),
            timeout=BACNET_TIMEOUT,
        )
        return float(result)
    except Exception as e:
        logger.error(f"[BACnet] Lecture température chambre {numero} : {e}")
        return None
