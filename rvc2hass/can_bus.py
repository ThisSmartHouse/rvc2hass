"""CAN bus interface wrapper using python-can.

Provides async read/write access to a CAN bus interface (real or virtual).
Handles connection, reconnection, and graceful shutdown.
"""

import asyncio
import logging
from typing import Callable

import can

log = logging.getLogger(__name__)


class CANBusReader:
    """Async CAN bus frame reader.

    Wraps python-can's Bus interface for async operation. Reads frames
    from the CAN bus and passes them to a callback for processing.
    """

    def __init__(self, interface: str = "socketcan", channel: str = "can0",
                 bitrate: int = 250000):
        self.interface = interface
        self.channel = channel
        self.bitrate = bitrate
        self._bus: can.Bus | None = None
        self._running = False

    def connect(self):
        """Connect to the CAN bus interface."""
        log.info("Connecting to CAN bus: %s/%s", self.interface, self.channel)
        self._bus = can.Bus(
            interface=self.interface,
            channel=self.channel,
            bitrate=self.bitrate,
        )
        log.info("CAN bus connected")

    def disconnect(self):
        """Disconnect from the CAN bus."""
        if self._bus:
            self._bus.shutdown()
            self._bus = None
            log.info("CAN bus disconnected")

    async def read_frames(self, callback: Callable[[can.Message], None],
                          reconnect_delay: float = 5.0):
        """Read CAN frames continuously, calling callback for each.

        Runs until stop() is called. Automatically reconnects on errors.

        Args:
            callback: Called with each CAN message received.
            reconnect_delay: Seconds to wait before reconnecting on error.
        """
        self._running = True
        while self._running:
            try:
                if self._bus is None:
                    self.connect()
                # Use a reader in a thread to avoid blocking the event loop
                loop = asyncio.get_event_loop()
                msg = await loop.run_in_executor(
                    None, lambda: self._bus.recv(timeout=1.0)
                )
                if msg is not None:
                    callback(msg)
            except can.CanError as e:
                log.error("CAN bus error: %s — reconnecting in %ss", e, reconnect_delay)
                self.disconnect()
                await asyncio.sleep(reconnect_delay)
            except Exception as e:
                if self._running:
                    log.error("Unexpected CAN error: %s — reconnecting in %ss", e, reconnect_delay)
                    self.disconnect()
                    await asyncio.sleep(reconnect_delay)

    def stop(self):
        """Signal the reader to stop."""
        self._running = False
        self.disconnect()

    def send(self, arbitration_id: int, data: bytes, is_extended: bool = True):
        """Send a CAN frame.

        Args:
            arbitration_id: The CAN arbitration ID.
            data: The data bytes to send.
            is_extended: Whether this is an extended (29-bit) frame.
        """
        if self._bus is None:
            raise RuntimeError("CAN bus not connected")
        msg = can.Message(
            arbitration_id=arbitration_id,
            data=data,
            is_extended_id=is_extended,
        )
        self._bus.send(msg)
        log.debug("Sent CAN frame: %08X#%s", arbitration_id, data.hex().upper())
