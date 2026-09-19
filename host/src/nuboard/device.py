from __future__ import annotations

import hashlib
import json
import queue
import struct
import threading
import time
from pathlib import Path
from typing import Callable, Iterator, Protocol

from .protocol import EVENT, HEADER, MAX_PAYLOAD, EventRecord, EventType, Kind, Message, Opcode, Status

VID = 0x2E8A
PID = 0x000A
EP_BULK_OUT = 0x03
EP_BULK_IN = 0x83
EP_EVENT_IN = 0x84


class Transport(Protocol):
    def write(self, endpoint: int, data: bytes, timeout: int | None = None): ...
    def read(self, endpoint: int, size: int, timeout: int | None = None): ...
    def close(self): ...


class USBTransport:
    """Small PyUSB adapter that owns and releases both vendor interfaces."""

    def __init__(self, device, usb_util):
        self._device = device
        self._usb_util = usb_util
        self._interfaces = (2, 3)

        # Linux may already have configured the composite device and attached
        # its CDC driver. Reapplying configuration 1 would disrupt CDC and can
        # fail with EBUSY, so configure only an unconfigured device.
        active_configuration = device.get_active_configuration()
        if active_configuration is None:
            device.set_configuration()
        for interface in self._interfaces:
            usb_util.claim_interface(device, interface)

    def write(self, endpoint: int, data: bytes, timeout: int | None = None):
        return self._device.write(endpoint, data, timeout=timeout)

    def read(self, endpoint: int, size: int, timeout: int | None = None):
        return self._device.read(endpoint, size, timeout=timeout)

    def close(self) -> None:
        for interface in reversed(self._interfaces):
            self._usb_util.release_interface(self._device, interface)
        self._usb_util.dispose_resources(self._device)


class NuBoardError(RuntimeError):
    def __init__(self, status: Status, message: str | None = None):
        self.status = status
        super().__init__(message or status.name.lower().replace("_", " "))


class NuBoard:
    def __init__(self, transport: Transport | None = None, timeout_ms: int = 5000):
        self.transport = transport or self._open_usb()
        self.timeout_ms = timeout_ms
        self._sequence = 0
        self._command_lock = threading.Lock()
        self._read_buffers: dict[int, bytearray] = {}
        self._event_queue: queue.Queue[EventRecord | BaseException] = queue.Queue()
        self._event_stop = threading.Event()
        self._event_thread: threading.Thread | None = None
        self._packet_lock = threading.Lock()
        self._packet_tag = 0

    @staticmethod
    def _open_usb():
        import usb.core
        import usb.util

        device = usb.core.find(idVendor=VID, idProduct=PID)
        if device is None:
            raise NuBoardError(Status.LINK, "nuBoard USB device not found")
        return USBTransport(device, usb.util)

    def _read_exact(
        self,
        endpoint: int,
        length: int,
        timeout: int | None = None,
    ) -> bytes:
        buffered = self._read_buffers.setdefault(endpoint, bytearray())
        timeout_ms = self.timeout_ms if timeout is None else timeout
        deadline = time.monotonic() + timeout_ms / 1000.0
        while len(buffered) < length:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise NuBoardError(Status.TIMEOUT, "USB response deadline expired")
            # Bulk endpoint 0x83 has 64-byte USB packets. Supplying a shorter
            # libusb buffer causes an overflow when header and payload share a
            # packet, so retain any bytes beyond the caller's immediate need.
            transfer_size = max(64, length - len(buffered))
            chunk = bytes(
                self.transport.read(
                    endpoint,
                    transfer_size,
                    timeout=max(1, int(remaining * 1000)),
                )
            )
            if not chunk:
                # TinyUSB terminates exact packet-size transfers with a ZLP.
                # It may arrive after the complete previous NUB1 frame, so it
                # is a transport boundary, not EOF or a failed command. Keep
                # reading under the same deadline without resending anything.
                continue
            buffered.extend(chunk)

        result = bytes(buffered[:length])
        del buffered[:length]
        return result

    def command(self, opcode: Opcode, payload: bytes = b"") -> bytes:
        with self._command_lock:
            self._sequence = (self._sequence + 1) & 0xFFFFFFFF
            request = Message(opcode, self._sequence, payload)
            self.transport.write(
                EP_BULK_OUT,
                request.pack(),
                timeout=self.timeout_ms,
            )
            header = self._read_exact(EP_BULK_IN, HEADER.size)
            length = HEADER.unpack(header)[-1]
            if length > MAX_PAYLOAD:
                raise NuBoardError(
                    Status.LENGTH,
                    "device returned oversized response",
                )
            response = Message.unpack(
                header + self._read_exact(EP_BULK_IN, length)
            )
            if (
                response.kind != Kind.RESPONSE
                or response.sequence != self._sequence
                or response.opcode != opcode
            ):
                raise NuBoardError(
                    Status.LINK,
                    "response opcode or sequence mismatch",
                )
            if response.status != Status.OK:
                detail = response.payload.decode("utf-8", "replace") or None
                raise NuBoardError(response.status, detail)
            return response.payload

    def info(self) -> bytes:
        return self.command(Opcode.GET_INFO)

    def state(self) -> bytes:
        return self.command(Opcode.GET_STATE)

    def configure(
        self,
        path: str | Path,
        progress: Callable[[int, int], None] | None = None,
    ) -> None:
        image_path = Path(path)
        size = image_path.stat().st_size
        if not 0 < size <= 32 * 1024 * 1024:
            raise ValueError("bitstream size must be 1..33554432 bytes")
        digest = hashlib.sha256()
        with image_path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        name = image_path.name.encode("utf-8")
        if not name or len(name) > 63 or b"\0" in name:
            raise ValueError("bitstream basename must be 1..63 UTF-8 bytes")
        metadata = struct.pack("<64sI32s", name, size, digest.digest())
        self.command(Opcode.CONFIG_BEGIN, metadata)
        sent = 0
        try:
            self._wait_for_configuration_stream()
            with image_path.open("rb") as source:
                while block := source.read(MAX_PAYLOAD - 4):
                    self.command(Opcode.CONFIG_DATA, struct.pack("<I", sent) + block)
                    sent += len(block)
                    if progress:
                        progress(sent, size)
            self.command(Opcode.CONFIG_END)
            self._wait_for_configuration_complete()
        except BaseException:
            try:
                self.command(Opcode.CONFIG_ABORT)
            except BaseException:
                pass
            raise

    def _wait_for_configuration_stream(self) -> None:
        """Wait for asynchronous rail and reset sequencing to finish."""

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            state = json.loads(self.state())
            phase = state.get("phase")
            if phase == 5:
                return
            if phase == 0:
                failure = state.get("failure", 0)
                raise NuBoardError(
                    Status.CONFIGURATION,
                    f"FPGA left configuration state (failure {failure})",
                )
            time.sleep(0.01)

        raise NuBoardError(
            Status.TIMEOUT,
            "FPGA did not become ready for configuration data",
        )

    def _wait_for_configuration_complete(self) -> None:
        """Wait for CDONE, heartbeat, and mailbox identity qualification."""

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            state = json.loads(self.state())
            phase = state.get("phase")
            if phase == 11:
                return
            if phase == 0:
                failure = state.get("failure", 0)
                raise NuBoardError(
                    Status.CONFIGURATION,
                    f"FPGA qualification failed (failure {failure})",
                )
            time.sleep(0.01)

        raise NuBoardError(
            Status.TIMEOUT,
            "FPGA configuration did not pass runtime qualification",
        )

    def fpga_send(self, channel: int, data: bytes, tag: int = 0) -> None:
        if not 0 <= channel <= 255 or not 0 <= tag <= 0xFFFFFFFF:
            raise ValueError("invalid channel or tag")
        # The FPGA packet is 4096 bytes including its 16-byte mailbox header.
        max_chunk = 4080
        chunks = [
            data[offset:offset + max_chunk]
            for offset in range(0, len(data), max_chunk)
        ] or [b""]
        for index, chunk in enumerate(chunks):
            first = index == 0
            last = index == len(chunks) - 1
            flags = (1 if first else 0) | (2 if last else 0)
            header = struct.pack("<BBHI", channel, flags, 0, tag)
            self.command(Opcode.FPGA_SEND, header + chunk)

    def fpga_recv(self) -> tuple[int, int, int, bytes]:
        raw = self.command(Opcode.FPGA_RECV)
        if len(raw) < 8:
            raise NuBoardError(Status.LINK, "short FPGA packet response")
        channel, flags, _reserved, tag = struct.unpack_from("<BBHI", raw)
        return channel, flags, tag, raw[8:]

    def link_status(self) -> bytes:
        return self.command(Opcode.LINK_STATUS)

    def fpga_exchange(self, channel: int, data: bytes, timeout: float = 5.0) -> bytes:
        """Exchange one application packet, waiting on interrupt-IN for its reply.

        This owns the event consumer until the reply arrives. Applications must
        not concurrently consume ``events()`` on the same device instance.
        """
        if len(data) > 4080:
            raise ValueError("a packet exchange is limited to 4080 bytes")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        with self._packet_lock:
            self._start_events()
            self._packet_tag = (self._packet_tag + 1) & 0xFFFFFFFF
            tag = self._packet_tag
            self.fpga_send(channel, data, tag)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise NuBoardError(Status.TIMEOUT, "FPGA reply timed out")
                try:
                    event = self._event_queue.get(timeout=remaining)
                except queue.Empty as exc:
                    raise NuBoardError(Status.TIMEOUT, "FPGA reply timed out") from exc
                if isinstance(event, BaseException):
                    raise event
                if event.lost or event.event_type == EventType.OVERFLOW:
                    raise NuBoardError(Status.LINK, "FPGA event stream overflow")
                if event.event_type in (EventType.LINK_FAULT, EventType.CONFIG_FAILURE,
                                        EventType.VCCB_SHUTDOWN):
                    raise NuBoardError(Status.LINK, f"board event: {event.event_type.name}")
                if event.event_type != EventType.FPGA_IRQ:
                    continue
                try:
                    reply_channel, flags, reply_tag, reply = self.fpga_recv()
                except NuBoardError as exc:
                    if exc.status == Status.BUSY:
                        continue  # A previously queued IRQ whose slot was read.
                    raise
                if (reply_channel, flags, reply_tag) != (channel, 3, tag):
                    raise NuBoardError(Status.LINK, "FPGA reply channel, flags, or tag mismatch")
                return reply

    def vccb_enable(self) -> None:
        self.command(Opcode.VCCB_ENABLE)

    def vccb_disable(self) -> None:
        self.command(Opcode.VCCB_DISABLE)

    def power_off(self) -> None:
        self.command(Opcode.POWER_OFF)

    def _event_worker(self) -> None:
        while not self._event_stop.is_set():
            try:
                raw = bytes(self.transport.read(EP_EVENT_IN, EVENT.size, timeout=250))
                if raw:
                    self._event_queue.put(EventRecord.unpack(raw))
            except BaseException as exc:
                if not self._event_stop.is_set() and "timed out" not in str(exc).lower():
                    self._event_queue.put(exc)
                    return

    def _start_events(self) -> None:
        if self._event_thread is None:
            self._event_thread = threading.Thread(
                target=self._event_worker,
                name="nuboard-events",
                daemon=True,
            )
            self._event_thread.start()

    def events(self) -> Iterator[EventRecord]:
        self._start_events()
        while True:
            item = self._event_queue.get()
            if isinstance(item, BaseException):
                raise item
            yield item

    def close(self) -> None:
        self._event_stop.set()
        if self._event_thread:
            self._event_thread.join(timeout=1)
        close = getattr(self.transport, "close", None)
        if close:
            close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.close()
