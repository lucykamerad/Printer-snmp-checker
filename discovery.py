"""Finds hosts on the local network before probing them for SNMP printer data."""

import ipaddress
import shutil
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed


def get_local_subnet():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip.rsplit(".", 1)[0] + ".0/24"
    except Exception:
        return "192.168.1.0/24"


def ping_host(ip_str):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "1", str(ip_str)],
                           capture_output=True, timeout=2)
        return r.returncode == 0
    except Exception:
        return False


def discover_hosts(subnet):
    nmap_bin = shutil.which("nmap")
    if nmap_bin:
        try:
            r = subprocess.run(
                [nmap_bin, "-sU", "-p", "161", "--open", "-T4",
                 "--host-timeout", "3s", "-oG", "-", subnet],
                capture_output=True, text=True, timeout=120
            )
            hosts = []
            for line in r.stdout.splitlines():
                if "Host:" in line and "open" in line.lower():
                    parts = line.split()
                    if len(parts) >= 2:
                        hosts.append(parts[1])
            if hosts:
                return hosts
        except Exception:
            pass
    # Ping sweep fallback
    try:
        host_list = [str(h) for h in ipaddress.ip_network(subnet, strict=False).hosts()]
    except ValueError:
        return []
    alive = []
    with ThreadPoolExecutor(max_workers=80) as ex:
        futures = {ex.submit(ping_host, h): h for h in host_list}
        for f in as_completed(futures):
            if f.result():
                alive.append(futures[f])
    return alive
