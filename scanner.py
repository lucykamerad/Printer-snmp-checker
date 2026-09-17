"""Probes each discovered host for ink/toner levels and holds the scan state."""

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from discovery import discover_hosts
from snmp import (
    OID_SYS_DESCR, OID_SYS_NAME, OID_PRINTER_NAME,
    OID_SUPPLY_CURRENT, OID_SUPPLY_MAX, OID_SUPPLY_DESC,
    snmp_get, snmp_walk,
)

WARN_LEVEL   = 15.0
CRIT_LEVEL   = 5.0
SCAN_WORKERS = 30

# Valori SNMP speciali (RFC 3805): -1 = altro/sconosciuto,
# -2 = illimitato/non misurabile, -3 = sconosciuto
SNMP_SPECIAL = {-1, -2, -3}

STATE_LOCK  = threading.Lock()
SCAN_LOCK   = threading.Lock()
PRINTERS    = []      # lista di dict con i dati stampanti
SCAN_STATUS = {"running": False, "progress": 0, "total": 0,
                "started": None, "finished": None, "error": None}


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

    # Lettura forniture:
    # OID_SUPPLY_CURRENT (.43.11.1.1.9) e OID_SUPPLY_MAX (.43.11.1.1.8)
    # .43.11.1.1.6  ← nome dal subtree .11 (usato da HP)
    # OID_SUPPLY_DESC (.43.12.1.1.4) ← nome dal subtree .12 (usato da Sharp/Brother)
    currents = snmp_walk(ip, OID_SUPPLY_CURRENT, community)
    maxes    = snmp_walk(ip, OID_SUPPLY_MAX, community)
    descs_11 = snmp_walk(ip, "1.3.6.1.2.1.43.11.1.1.6", community)
    descs_12 = snmp_walk(ip, OID_SUPPLY_DESC, community)

    if not currents:
        return None

    supplies = []
    for idx, raw_curr in currents.items():
        try:
            current = int(raw_curr)
            maximum = int(maxes.get(idx, "-1"))

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

            supplies.append({"index": idx, "desc": desc,
                             "current": current, "maximum": maximum, "percent": pct})
        except (ValueError, ZeroDivisionError):
            continue

    # min_pct esclude le forniture non misurabili (waste toner ecc.)
    valid = [s["percent"] for s in supplies if s["percent"] is not None]
    min_pct = min(valid) if valid else None

    return {
        "ip": ip, "name": name, "supplies": supplies,
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
    except Exception as e:
        with STATE_LOCK:
            SCAN_STATUS["running"] = False
            SCAN_STATUS["error"] = str(e)
