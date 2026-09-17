#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web UI per il monitoraggio del livello di inchiostro/toner delle stampanti
di rete tramite SNMP.

Richiede snmpget/snmpwalk installati sulla macchina che esegue il server:
  sudo apt install snmp           (Debian/Ubuntu/Mint)
  sudo dnf install net-snmp-utils (Fedora/RHEL)

Uso:
  python3 main.py
  python3 main.py --port 8081
  python3 main.py --subnet 10.0.0.0/24 --community public
"""

import argparse
import socket
import socketserver
import sys

from config import CONFIG
from discovery import get_local_subnet
from handlers import Handler
from snmp import SNMPGET, SNMPWALK

DEFAULT_PORT      = 8081
DEFAULT_COMMUNITY = "public"


def main():
    parser = argparse.ArgumentParser(description="Ink Monitor — Web UI per il livello inchiostro stampanti")
    parser.add_argument("--port",      type=int, default=DEFAULT_PORT)
    parser.add_argument("--subnet",    default=None)
    parser.add_argument("--community", default=DEFAULT_COMMUNITY)
    parser.add_argument("--bind",      default="0.0.0.0")
    args = parser.parse_args()

    subnet = args.subnet or get_local_subnet()
    CONFIG["subnet"] = subnet
    CONFIG["community"] = args.community

    if not SNMPWALK or not SNMPGET:
        print("\n[!] ATTENZIONE: snmpwalk/snmpget non trovati.")
        print("    Installa con: sudo apt install snmp")
        print("    Il server si avvia comunque ma la scansione non funzionerà.\n")
    else:
        print(f"[✓] snmpget:  {SNMPGET}")
        print(f"[✓] snmpwalk: {SNMPWALK}")

    try:
        server = socketserver.ThreadingTCPServer((args.bind, args.port), Handler)
        server.allow_reuse_address = True
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
        except Exception:
            local_ip = "127.0.0.1"

        print(f"\n[✓] Ink Monitor avviato")
        print(f"    http://localhost:{args.port}")
        print(f"    http://{local_ip}:{args.port}")
        print(f"    Subnet default: {subnet}  |  Community: {args.community}")
        print(f"\n    Premi Ctrl+C per fermare\n")
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Server fermato.")
    except OSError as e:
        print(f"\n[!] Errore: {e}")
        print(f"    La porta {args.port} potrebbe essere già in uso.")
        print(f"    Usa --port 8082 per cambiare porta.")
        sys.exit(1)


if __name__ == "__main__":
    main()
