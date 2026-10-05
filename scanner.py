"""Probes each discovered host for ink/toner levels and holds the scan state."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from config import CONFIG
from discovery import discover_hosts
from log import log
from snmp import (
    OID_SYS_DESCR, OID_SYS_NAME, OID_PRINTER_NAME,
    OID_MODEL, OID_SERIAL, OID_PAGE_COUNT,
    OID_SUPPLY_CURRENT, OID_SUPPLY_MAX, OID_SUPPLY_DESC, OID_SUPPLY_TYPE,
    snmp_get, snmp_walk,
)

WARN_LEVEL   = 15.0
CRIT_LEVEL   = 5.0
SCAN_WORKERS = 30
CACHE_FILE   = Path(__file__).parent / "printers_cache.json"

# Valori SNMP speciali (RFC 3805): -1 = altro/sconosciuto,
# -2 = illimitato/non misurabile, -3 = sconosciuto
SNMP_SPECIAL = {-1, -2, -3}

STATE_LOCK  = threading.Lock()
SCAN_LOCK   = threading.Lock()
PRINTERS    = []      # lista di dict con i dati stampanti
SCAN_STATUS = {"running": False, "progress": 0, "total": 0,
                "started": None, "finished": None, "error": None}


def save_cache():
    """Salva su disco l'ultimo risultato, così al riavvio non si riparte da zero."""
    with STATE_LOCK:
        data = {
            "printers": list(PRINTERS),
            "scanned_at": SCAN_STATUS.get("finished"),
            "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    try:
        CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as e:
        log(f"[!] Errore salvataggio cache: {e}")


def load_cache():
    if not CACHE_FILE.exists():
        return
    try:
        data = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log(f"[!] Errore caricamento cache: {e}")
        return
    with STATE_LOCK:
        PRINTERS[:] = data.get("printers", [])
    if PRINTERS:
        log(f"[✓] Caricate {len(PRINTERS)} stampanti dalla cache ({CACHE_FILE.name})")


def auto_scan_worker(interval_minutes, community):
    """Rilancia la scansione ogni N minuti, usando la subnet di default."""
    while True:
        time.sleep(interval_minutes * 60)
        subnet = CONFIG.get("subnet")
        with STATE_LOCK:
            busy = SCAN_STATUS["running"]
        if subnet and not busy:
            log(f"[*] Scansione automatica programmata (ogni {interval_minutes} min)")
            run_scan(subnet, community)


def check_printer(ip, community):
    descr = snmp_get(ip, OID_SYS_DESCR, community)
    if not descr:
        return None

    name = None
    for oid in (OID_SYS_NAME, OID_PRINTER_NAME, OID_SYS_DESCR):
        v = snmp_get(ip, oid, community)
        if v and len(v) > 1:
            name = v.split("\n")[0][:60].strip()
            break
    name = name or "Stampante sconosciuta"

    model  = snmp_get(ip, OID_MODEL, community)
    serial = snmp_get(ip, OID_SERIAL, community)
    page_count = None
    try:
        page_count = int(snmp_get(ip, OID_PAGE_COUNT, community))
    except (TypeError, ValueError):
        pass

    # Lettura forniture:
    # OID_SUPPLY_CURRENT (.43.11.1.1.9) e OID_SUPPLY_MAX (.43.11.1.1.8)
    # .43.11.1.1.6  ← nome dal subtree .11 (usato da HP)
    # OID_SUPPLY_DESC (.43.12.1.1.4) ← nome dal subtree .12 (usato da Sharp/Brother)
    currents = snmp_walk(ip, OID_SUPPLY_CURRENT, community)
    maxes    = snmp_walk(ip, OID_SUPPLY_MAX, community)
    types    = snmp_walk(ip, OID_SUPPLY_TYPE, community)
    descs_11 = snmp_walk(ip, "1.3.6.1.2.1.43.11.1.1.6", community)
    descs_12 = snmp_walk(ip, OID_SUPPLY_DESC, community)

    if not currents:
        return None

    supplies = []
    for idx, raw_curr in currents.items():
        try:
            current = int(raw_curr)
            maximum = int(maxes.get(idx, "-1"))
            raw_type = types.get(idx, "-1")
            try:
                type_code = int(raw_type)
            except ValueError:
                type_code = -1

            # .12 ha priorità se presente e non è hex spazzatura, altrimenti usa .11
            desc_12 = descs_12.get(idx, "").strip()
            desc_11 = descs_11.get(idx, "").strip()
            if desc_12 and len(desc_12) > 1:
                desc = desc_12
            elif desc_11 and len(desc_11) > 1:
                desc = desc_11
            else:
                desc = f"Supply {idx}"

            # -2 = illimitato (waste toner), -3 = sconosciuto
            if current in SNMP_SPECIAL or maximum in SNMP_SPECIAL or maximum <= 0:
                pct = None
            elif current < 0:
                pct = None
            else:
                pct = round(max(0.0, min(100.0, current / maximum * 100)), 1)

            supplies.append({"index": idx, "desc": desc, "type_code": type_code,
                             "current": current, "maximum": maximum, "percent": pct})
        except (ValueError, ZeroDivisionError):
            continue

    # min_pct esclude le forniture non misurabili (waste toner ecc.)
    valid = [s["percent"] for s in supplies if s["percent"] is not None]
    min_pct = min(valid) if valid else None

    return {
        "ip": ip, "name": name, "model": model, "serial": serial,
        "page_count": page_count, "supplies": supplies,
        "min_pct": min_pct,
        "scanned_at": datetime.now().strftime("%H:%M:%S"),
        "scanned_ts": time.time(),
    }


def run_scan(subnet, community, hosts_override=None):
    with SCAN_LOCK:
        if SCAN_STATUS["running"]:
            return
        with STATE_LOCK:
            SCAN_STATUS.update({"running": True, "progress": 0, "total": 0,
                                "started": datetime.now().strftime("%H:%M:%S"),
                                "finished": None, "error": None})

    try:
        host_list = hosts_override if hosts_override else discover_hosts(subnet)

        with STATE_LOCK:
            SCAN_STATUS["total"] = len(host_list)

        found = []
        with ThreadPoolExecutor(max_workers=SCAN_WORKERS) as ex:
            futures = {ex.submit(check_printer, ip, community): ip for ip in host_list}
            done = 0
            for f in as_completed(futures):
                done += 1
                try:
                    res = f.result()
                    if res:
                        found.append(res)
                except Exception:
                    pass
                with STATE_LOCK:
                    SCAN_STATUS["progress"] = done

        found.sort(key=lambda p: (p["min_pct"] is None, p["min_pct"] or 0))
        with STATE_LOCK:
            # Mutate the existing list in place (PRINTERS[:] = ...), not a rebind:
            # other modules hold "from scanner import PRINTERS" references to this
            # same list object, and a plain reassignment here would leave them
            # pointing at the stale, empty list forever.
            PRINTERS[:] = found
            SCAN_STATUS["running"] = False
            SCAN_STATUS["finished"] = datetime.now().strftime("%H:%M:%S")
        save_cache()
    except Exception as e:
        with STATE_LOCK:
            SCAN_STATUS["running"] = False
            SCAN_STATUS["error"] = str(e)
