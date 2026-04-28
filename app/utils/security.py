import ipaddress
import logging
from typing import List, Optional
from fastapi import Request, HTTPException

logger = logging.getLogger(__name__)


class SecurityManager:
    """Security utilities for IP validation and request limits"""

    def __init__(
        self,
        allowed_ips: List[str] = None,
        max_body_size: int = 1048576,
        enforce_client_ip_rules: bool = False,
    ):
        self.allowed_networks = []
        if allowed_ips:
            for ip_range in allowed_ips:
                try:
                    self.allowed_networks.append(ipaddress.ip_network(ip_range, strict=False))
                except ValueError as e:
                    logger.warning(f"Invalid IP range: {ip_range} - {e}")

        self.max_body_size = max_body_size
        self.enforce_client_ip_rules = enforce_client_ip_rules

    def validate_ip(self, client_ip: str) -> bool:
        """
        Validate if client IP is in allowed ranges

        Args:
            client_ip: Client IP address

        Returns:
            True if allowed, False otherwise
        """
        if not self.allowed_networks:
            # If no restrictions, allow all
            return True

        try:
            client_addr = ipaddress.ip_address(client_ip)
            for network in self.allowed_networks:
                if client_addr in network:
                    return True

            logger.warning(f"Blocked request from unauthorized IP: {client_ip}")
            return False

        except ValueError:
            logger.warning(f"Invalid IP address: {client_ip}")
            return False

    def validate_body_size(self, body_size: int) -> bool:
        """
        Validate request body size

        Args:
            body_size: Size of request body in bytes

        Returns:
            True if within limits, False otherwise
        """
        if body_size > self.max_body_size:
            logger.warning(f"Request body too large: {body_size} bytes (max: {self.max_body_size})")
            return False
        return True

    def validate_camera_ip(self, camera_ip: str) -> str:
        """Validate camera IP to reduce SSRF risk (IP literals only, private networks only)."""
        try:
            ip_addr = ipaddress.ip_address(camera_ip)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid camera_ip: {camera_ip}")

        # Reject risky and non-routable targets commonly used in SSRF attacks.
        if ip_addr.is_loopback or ip_addr.is_multicast or ip_addr.is_unspecified or ip_addr.is_reserved:
            raise HTTPException(status_code=400, detail=f"Blocked camera_ip: {camera_ip}")

        if self.allowed_networks:
            if not any(ip_addr in network for network in self.allowed_networks):
                raise HTTPException(status_code=400, detail=f"camera_ip not in allowed networks: {camera_ip}")
        elif not ip_addr.is_private:
            raise HTTPException(status_code=400, detail=f"Only private camera_ip is allowed: {camera_ip}")

        return camera_ip

    async def get_client_ip(self, request: Request) -> str:
        """
        Extract client IP from request, handling proxies

        Args:
            request: FastAPI request object

        Returns:
            Client IP address
        """
        # Check for forwarded headers (behind proxy)
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # Take first IP if multiple
            client_ip = forwarded_for.split(",")[0].strip()
        else:
            # Direct connection
            client_ip = request.client.host if request.client else "unknown"

        return client_ip

    async def validate_request(self, request: Request) -> None:
        """
        Validate incoming request

        Args:
            request: FastAPI request object

        Raises:
            HTTPException: If validation fails
        """
        client_ip = await self.get_client_ip(request)

        if self.enforce_client_ip_rules and not self.validate_ip(client_ip):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied from IP: {client_ip}"
            )

        # For POST requests, check body size
        if request.method == "POST":
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    body_size = int(content_length)
                    if not self.validate_body_size(body_size):
                        raise HTTPException(
                            status_code=413,
                            detail=f"Request body too large: {body_size} bytes (max: {self.max_body_size})"
                        )
                except ValueError:
                    pass  # Invalid content-length header, skip validation


# Global security instance
security_manager = None


def init_security_manager(
    allowed_ips: List[str] = None,
    max_body_size: int = 1048576,
    enforce_client_ip_rules: bool = False,
) -> SecurityManager:
    """Initialize global security manager"""
    global security_manager
    security_manager = SecurityManager(
        allowed_ips=allowed_ips,
        max_body_size=max_body_size,
        enforce_client_ip_rules=enforce_client_ip_rules,
    )
    return security_manager


def get_security_manager() -> Optional[SecurityManager]:
    """Get global security manager instance"""
    return security_manager
