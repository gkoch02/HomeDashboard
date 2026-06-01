"""Fetch host system metrics using only Python stdlib (no subprocess, no new deps).

All fields are optional — any individual failure is caught and returns None for
that field, so the rest still populate. Returns None only if *every* field fails.
"""

import logging
import os
import socket
from typing import Optional

from src.data.models import HostData

logger = logging.getLogger(__name__)


def fetch_host_data() -> Optional[HostData]:
    """Collect host system metrics synchronously.

    Uses /proc filesystem and stdlib — safe for Raspberry Pi and any Linux host.
    Fields that are unavailable (e.g. CPU temp on non-Pi) are returned as None
    and the diags panel omits those rows silently.
    """
    host = HostData()
    any_success = False

    # Hostname
    try:
        host.hostname = socket.gethostname()
        any_success = True
    except Exception:
        pass

    # Uptime from /proc/uptime (first field = seconds since boot)
    try:
        with open("/proc/uptime") as f:
            host.uptime_seconds = float(f.read().split()[0])
        any_success = True
    except Exception:
        pass

    # Load average (1m, 5m, 15m) via os.getloadavg()
    try:
        host.load_1m, host.load_5m, host.load_15m = os.getloadavg()
        any_success = True
    except Exception:
        pass

    # RAM from /proc/meminfo (MemTotal and MemAvailable in kB)
    try:
        mem = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if parts[0] in ("MemTotal:", "MemAvailable:"):
                    mem[parts[0]] = int(parts[1])  # kB
        if "MemTotal:" in mem and "MemAvailable:" in mem:
            total_kb = mem["MemTotal:"]
            avail_kb = mem["MemAvailable:"]
            host.ram_total_mb = total_kb / 1024.0
            host.ram_used_mb = (total_kb - avail_kb) / 1024.0
            any_success = True
    except Exception:
        pass

    # Disk usage for root filesystem via os.statvfs('/')
    try:
        st = os.statvfs("/")
        total_bytes = st.f_blocks * st.f_frsize
        free_bytes = st.f_bavail * st.f_frsize
        used_bytes = total_bytes - free_bytes
        host.disk_total_gb = total_bytes / (1024**3)
        host.disk_used_gb = used_bytes / (1024**3)
        any_success = True
    except Exception:
        pass

    # CPU temperature from thermal_zone0 (Raspberry Pi and most Linux SBCs)
    try:
        with open("/sys/class/thermal/thermal_zone0/temp") as f:
            host.cpu_temp_c = int(f.read().strip()) / 1000.0
        any_success = True
    except Exception:
        pass

    # Primary outbound IP via a UDP socket (no packets are actually sent)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            # UDP connect normally returns instantly, but a host with no default
            # route can block; this fetch runs synchronously outside the pipeline's
            # 120s executor ceiling, so cap it defensively.
            s.settimeout(0.5)
            s.connect(("8.8.8.8", 80))
            host.ip_address = s.getsockname()[0]
            any_success = True
        finally:
            s.close()
    except Exception:
        pass

    if not any_success:
        logger.debug("host fetcher: all fields failed, returning None")
        return None

    return host
