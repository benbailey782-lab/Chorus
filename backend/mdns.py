import logging
import socket
from typing import Optional

from zeroconf import ServiceInfo, Zeroconf

log = logging.getLogger(__name__)

_zc: Optional[Zeroconf] = None
_info: Optional[ServiceInfo] = None


def _local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def advertise(name: str, port: int) -> None:
    global _zc, _info
    if _zc is not None:
        return
    ip = _local_ip()
    service_name = f"{name}._http._tcp.local."
    _info = ServiceInfo(
        type_="_http._tcp.local.",
        name=service_name,
        addresses=[socket.inet_aton(ip)],
        port=port,
        server=f"{name}.local.",
        properties={"path": "/"},
    )
    _zc = Zeroconf()
    _zc.register_service(_info)
    log.info("mDNS: advertising http://%s.local:%d (ip=%s)", name, port, ip)


def stop() -> None:
    global _zc, _info
    if _zc is None:
        return
    try:
        if _info is not None:
            try:
                _zc.unregister_service(_info)
            except Exception as e:
                log.debug("mDNS unregister failed (non-fatal): %s", e)
    finally:
        try:
            _zc.close()
        except Exception:
            pass
        _zc = None
        _info = None
