"""SNMP CLI wrappers: talks to snmpget/snmpwalk and decodes their output."""

import shutil
import subprocess

SNMP_TIMEOUT = 2

# SNMP OID (RFC 3805 / Printer-MIB)
OID_SYS_DESCR      = "1.3.6.1.2.1.1.1.0"
OID_SYS_NAME       = "1.3.6.1.2.1.1.5.0"
OID_PRINTER_NAME   = "1.3.6.1.2.1.25.3.2.1.3.1"
OID_SUPPLY_MAX     = "1.3.6.1.2.1.43.11.1.1.8"
OID_SUPPLY_CURRENT = "1.3.6.1.2.1.43.11.1.1.9"
OID_SUPPLY_DESC    = "1.3.6.1.2.1.43.12.1.1.4"

SNMPGET  = shutil.which("snmpget")
SNMPWALK = shutil.which("snmpwalk")


def decode_snmp_string(raw):
    """
    Le stampanti HP restituiscono i nomi delle forniture come Hex-STRING
    (es: "43 61 72 74 75 63 63 69 61 00") invece di STRING normale.
    Questa funzione decodifica entrambi i formati in testo leggibile.
    """
    if not raw:
        return raw
    raw = raw.strip()
    for pfx in ("Hex-STRING:", "STRING:", "hex-string:"):
        if raw.startswith(pfx):
            raw = raw[len(pfx):].strip()
    parts = raw.split()
    if parts and all(len(p) == 2 and all(c in '0123456789abcdefABCDEF' for c in p) for p in parts):
        try:
            decoded = bytes(int(b, 16) for b in parts).decode('utf-8', errors='replace')
            decoded = decoded.rstrip('\x00').strip()
            if decoded:
                return decoded
        except Exception:
            pass
    return raw.strip('"').strip()


def snmp_get(ip, oid, community):
    if not SNMPGET:
        return None
    try:
        r = subprocess.run(
            [SNMPGET, "-v", "2c", "-c", community,
             "-t", str(SNMP_TIMEOUT), "-r", "1", "-On", "-Oq", ip, oid],
            capture_output=True, text=True, timeout=SNMP_TIMEOUT + 2
        )
        if r.returncode != 0:
            return None
        val = r.stdout.strip()
        if "=" in val:
            val = val.split("=", 1)[1].strip()
        val = val.strip('"').strip()
        return None if ("No Such" in val or "Timeout" in val or not val) else val
    except Exception:
        return None


def snmp_walk_raw(ip, oid_base, community):
    """Walk SNMP restituendo {indice: valore_grezzo} senza decodifica."""
    if not SNMPWALK:
        return {}
    result = {}
    try:
        r = subprocess.run(
            [SNMPWALK, "-v", "2c", "-c", community,
             "-t", str(SNMP_TIMEOUT), "-r", "1", ip, oid_base],
            capture_output=True, text=True, timeout=SNMP_TIMEOUT * 5 + 5
        )
        if r.returncode != 0:
            return result
        lines = r.stdout.splitlines()
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            i += 1
            if not line or "No Such" in line or "End of MIB" in line:
                continue
            if " = " not in line:
                continue
            oid_part, rest = line.split(" = ", 1)
            # Hex-STRING può essere multi-riga: accumula finché non troviamo la riga successiva con OID
            while i < len(lines) and lines[i] and not lines[i][0].isalpha() and " = " not in lines[i]:
                rest += " " + lines[i].strip()
                i += 1
            idx = oid_part.strip().strip(".").split(".")[-1]
            result[idx] = rest.strip()
    except Exception:
        pass
    return result


def snmp_walk(ip, oid_base, community):
    """Walk SNMP con decodifica automatica di Hex-STRING. Restituisce {indice: valore_decoded}."""
    raw = snmp_walk_raw(ip, oid_base, community)
    result = {}
    for idx, val in raw.items():
        if ":" in val:
            type_part, data = val.split(":", 1)
            type_part = type_part.strip().upper()
            data = data.strip()
            if "HEX" in type_part or "HEX-STRING" in type_part:
                result[idx] = decode_snmp_string(data)
            elif type_part in ("STRING", "Timeticks", "IpAddress", "OID"):
                result[idx] = data.strip('"').strip()
            else:
                result[idx] = data.strip()
        else:
            result[idx] = decode_snmp_string(val)
    return result
