import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import settings
from app.email.sender import send_gemini_key_alert

logger = logging.getLogger(__name__)


class KeyExhaustedError(Exception):
    """Raised when the current API key has hit its quota limit."""


class AllKeysExhaustedError(Exception):
    """Raised when every configured API key has been exhausted."""


@dataclass
class ManagedKey:
    api_key: str
    label: str = ""
    exhausted: bool = False
    exhausted_at: datetime | None = None

    def mark_exhausted(self) -> None:
        self.exhausted = True
        self.exhausted_at = datetime.now(UTC)

    @property
    def masked(self) -> str:
        """Safe masked version for logs and emails."""
        if len(self.api_key) <= 8:
            return "***"
        return self.api_key[:4] + "****" + self.api_key[-4:]

    def as_dict(self) -> dict:
        return {
            "label": self.label,
            "masked_key": self.masked,
            "exhausted": self.exhausted,
            "exhausted_at": (
                self.exhausted_at.strftime("%Y-%m-%d %H:%M:%S UTC") if self.exhausted_at else None
            ),
        }


class GeminiKeyManager:
    """
    Asyncio-safe round-robin key manager for Gemini API keys.
    """

    def __init__(
        self,
        keys: list[str],
    ) -> None:
        if not keys:
            raise ValueError("At least one API key must be provided.")

        self._keys: list[ManagedKey] = [
            ManagedKey(api_key=k, label=f"key-{i + 1}") for i, k in enumerate(keys)
        ]
        self._index: int = 0
        self._lock = asyncio.Lock()
        self._recipients: list[str] = getattr(settings, "ALERT_EMAIL_RECIPIENTS", [])
        self._send_alert_fn = send_gemini_key_alert
        self._app_name = getattr(settings, "PROJECT_NAME", "ANVILA")

    @property
    def current_key(self) -> str:
        return self._keys[self._index].api_key

    @property
    def active_key_label(self) -> str:
        return self._keys[self._index].label

    @property
    def available_count(self) -> int:
        return sum(1 for k in self._keys if not k.exhausted)

    async def rotate(self, exhausted_key: str) -> str:
        """
        Mark *exhausted_key* exhausted, fire an alert, advance to the next key.
        """
        async with self._lock:
            current = self._keys[self._index]

            # Guard: only mark if this key is actually the current one and
            # hasn't already been marked (concurrent requests may race here).
            if current.api_key == exhausted_key and not current.exhausted:
                current.mark_exhausted()
                logger.warning(
                    "Gemini key %s (%s) exhausted — rotating.",
                    current.label,
                    current.masked,
                )

            # Advance to next non-exhausted key
            for _ in range(len(self._keys)):
                self._index = (self._index + 1) % len(self._keys)
                candidate = self._keys[self._index]
                if not candidate.exhausted:
                    logger.info("Rotated to %s (%s).", candidate.label, candidate.masked)
                    asyncio.create_task(self._dispatch_alert(exhausted=current, next_key=candidate))
                    return candidate.api_key

            asyncio.create_task(self._dispatch_alert(exhausted=current, next_key=None))
            raise AllKeysExhaustedError(f"All {len(self._keys)} Gemini API key(s) are exhausted.")

    def status(self) -> list[dict]:
        """Snapshot of all managed keys — safe to expose in a /health endpoint."""
        return [k.as_dict() for k in self._keys]

    async def _dispatch_alert(self, exhausted: ManagedKey, next_key: ManagedKey | None) -> None:
        if not self._send_alert_fn or not self._recipients:
            print("sending emails to", self._recipients)
            logger.debug("No alert function or recipients configured — skipping.")
            return

        remaining = self.available_count
        all_exhausted = remaining == 0

        ctx = {
            "app_name": self._app_name,
            "key_label": exhausted.label,
            "masked_key": exhausted.masked,
            "exhausted_at": (
                exhausted.exhausted_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                if exhausted.exhausted_at
                else "unknown"
            ),
            "remaining_keys": remaining,
            "total_keys": len(self._keys),
            "all_exhausted": all_exhausted,
            "next_key_label": next_key.label if next_key else "—",
            "all_keys": [k.as_dict() for k in self._keys],
        }

        try:
            self._send_alert_fn(
                recipients=self._recipients,
                all_exhausted=all_exhausted,
                ctx=ctx,
            )
        except Exception:
            logger.exception("Failed to dispatch key-exhaustion alert email.")
