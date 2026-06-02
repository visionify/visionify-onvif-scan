"""Camera discovery: WS-Discovery multicast + active TCP probe fallback."""
from __future__ import annotations

import ipaddress
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional
from urllib.parse import urlparse

from .config import PROBE_PORTS
from .models import Device


def _xaddr_to_ip(xaddr: str) -> str:
    try:
        return urlparse(xaddr).hostname or ""
    except Exception:
        return ""


def ws_discover(timeout: int = 5) -> List[Device]:
    """Find ONVIF devices that answer WS-Discovery multicast."""
    try:
        from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
        from wsdiscovery import QName
    except Exception as e:  # pragma: no cover
        print(f"[discovery] WS-Discovery unavailable: {e}")
        return []

    wsd = WSDiscovery()
    devices: dict[str, Device] = {}
    try:
        wsd.start()
        nvt = QName("http://www.onvif.org/ver10/network/wsdl", "NetworkVideoTransmitter")
        services = wsd.searchServices(types=[nvt], timeout=timeout)
        for svc in services:
            xaddrs = svc.getXAddrs() or []
            if not xaddrs:
                continue
            url = xaddrs[0]
            ip = _xaddr_to_ip(url)
            if not ip or ip in devices:
                continue
            devices[ip] = Device(ip=ip, onvif_url=url, reachable=True)
    finally:
        try:
            wsd.stop()
        except Exception:
            pass
    return list(devices.values())


def _check_port(ip: str, port: int, timeout: float) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except Exception:
        return False


def _probe_host(ip: str, ports: List[int], timeout: float) -> Optional[Device]:
    open_ports = [p for p in ports if _check_port(ip, p, timeout)]
    if not open_ports:
        return None
    onvif_url = ""
    if 80 in open_ports:
        onvif_url = f"http://{ip}/onvif/device_service"
    return Device(ip=ip, onvif_url=onvif_url, open_ports=open_ports, reachable=True)


def probe_subnets(
    subnets: List[str], ports: List[int] | None = None, timeout: float = 1.0, workers: int = 64
) -> List[Device]:
    """Active TCP probe of subnets for cameras that ignore multicast."""
    ports = ports or PROBE_PORTS
    hosts: List[str] = []
    for cidr in subnets:
        try:
            net = ipaddress.ip_network(cidr, strict=False)
            hosts.extend(str(h) for h in net.hosts())
        except ValueError as e:
            print(f"[discovery] bad subnet {cidr}: {e}")
    found: List[Device] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(_probe_host, h, ports, timeout): h for h in hosts}
        for fut in as_completed(futs):
            dev = fut.result()
            if dev:
                found.append(dev)
    return found


def auto_subnets() -> List[str]:
    """Best-effort detection of local /24 subnets from the primary interface."""
    subnets: set[str] = set()
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        net = ipaddress.ip_network(local_ip + "/24", strict=False)
        subnets.add(str(net))
    except Exception:
        pass
    return sorted(subnets)


def merge_devices(*lists: List[Device]) -> List[Device]:
    """Merge device lists by IP, preferring entries that already have an onvif_url."""
    by_ip: dict[str, Device] = {}
    for lst in lists:
        for d in lst:
            existing = by_ip.get(d.ip)
            if existing is None:
                by_ip[d.ip] = d
            else:
                if not existing.onvif_url and d.onvif_url:
                    existing.onvif_url = d.onvif_url
                existing.open_ports = sorted(set(existing.open_ports) | set(d.open_ports))
    return sorted(by_ip.values(), key=lambda d: tuple(int(x) for x in d.ip.split(".")) if d.ip.count(".") == 3 else (0,))
