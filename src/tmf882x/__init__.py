from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from importlib import resources
from json import dumps
from time import sleep
from typing import Iterable, Literal

from smbus2 import SMBus, i2c_msg

from tmf882x.constants import SPAD_MAP_DIMENSIONS


class TMF882xException(RuntimeError):
    pass


class TMF882xMode(Enum):
    OFF = 0x00
    STANDBY = 0x02
    ENABLED = 0x41
    # Note: STANDBY_TIMED not implemented

    @classmethod
    def from_register(cls, value: int) -> "TMF882xMode":
        # Bits 4 and 5 should be ignored
        return cls(value & 0xCF)


@dataclass
class TMF882xResult:
    confidence: int
    distance: int

    @property
    def result_detected(self):
        return self.confidence > 0


@dataclass
class TMF882xMeasurement:
    result_number: int
    temperature: int
    n_valid_results: int
    ambient_light: int
    photon_count: int
    reference_count: int
    system_tick: int
    results: list[TMF882xResult]
    spad_map: int
    raw: bytes

    @classmethod
    def from_bytes(cls, data: list[int], spad_map: int) -> "TMF882xMeasurement":
        return TMF882xMeasurement(
            result_number=data[4],
            temperature=int.from_bytes(data[5:6], "little", signed=True),
            n_valid_results=data[6],
            ambient_light=int.from_bytes(data[8:12], "little"),
            photon_count=int.from_bytes(data[12:16], "little"),
            reference_count=int.from_bytes(data[16:20], "little"),
            system_tick=int.from_bytes(data[20:24], "little"),
            results=[
                TMF882xResult(
                    confidence=data[24 + 3 * i],
                    distance=int.from_bytes(data[25 + 3 * i : 27 + 3 * i], "little"),
                )
                for i in range(36)
            ],
            spad_map=spad_map,
            raw=bytes(data),
        )

    def grid(self, secondary: bool = False) -> list[list[int | None]]:
        try:
            x, y = SPAD_MAP_DIMENSIONS[self.spad_map]
        except KeyError:
            raise NotImplementedError("Result grid not implemented for custom spad maps.")
        offset = 18 if secondary else 0
        if x == 4 and y == 4:
            applicable_results = self.results[offset : offset + 8] + self.results[offset + 9 : offset + 17]
        else:
            applicable_results = self.results[offset : offset + (x * y)]

        return [
            [
                applicable_results[row + x * column].distance
                if applicable_results[row + x * column].distance > 0
                else None
                for row in range(x)
            ]
            for column in range(y)
        ]

class TMF882x:
    def __init__(self, bus: SMBus, address: int = 0x41, poll_delay: float = 0.001):
        self.address = address
        self.bus = bus
        self.poll_delay = poll_delay

    @property
    def mode(self) -> TMF882xMode:
        return TMF882xMode.from_register(self.bus.read_byte_data(self.address, 0xE0))

    @property
    def serial_number(self) -> int:
        """Read the serial number of the device."""
        data = self.bus.read_i2c_block_data(self.address, 0x1C, 4)
        return int.from_bytes(data, "little")

    def enable(self, auto_load_firmware: bool = True) -> None:
        """Enable the device."""
        self.bus.write_byte_data(self.address, 0xE0, 0x21)
        for _ in range(100):
            if self.mode == TMF882xMode.ENABLED:
                break
            sleep(self.poll_delay)
        if self.mode != TMF882xMode.ENABLED:
            raise TMF882xException(f"Failed to set mode to enabled. Mode is: {self.mode}.")
        if self.app_id == 0x80 and auto_load_firmware:
            self._load_firmware()

    def standby(self) -> None:
        """Set the device in standby mode."""
        # TODO: stop measurements
        self.bus.write_byte_data(self.address, 0xE0, 0x20)  # Set wake-up to application.
        for _ in range(100):
            if self.mode == TMF882xMode.STANDBY:
                return
            sleep(self.poll_delay)
        raise RuntimeError(f"Failed to set mode to standby. Mode is: {self.mode}.")

    def __enter__(self):
        self.enable()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.standby()

    @property
    def app_id(self) -> int:
        """
        Read the app id.

        This has two options:
        - 0x80: bootloader,
        - 0x03: application.
        """
        return self.bus.read_byte_data(self.address, 0x00)

    @property
    def minor(self):
        return self.bus.read_byte_data(self.address, 0x01)

    def _read_status(self) -> int:
        return self.bus.read_byte_data(self.address, 0x08)

    def _send_command(self, command: int) -> None:
        self.bus.write_byte_data(self.address, 0x08, command)
        while (status := self._read_status()) >= 0x10:
            sleep(0.001)
        if status > 0x01:
            raise RuntimeError()  # TODO

    def measure(self) -> TMF882xMeasurement:
        # Clear interrupts
        self.bus.write_byte_data(self.address, 0xE1, 0xFF)
        # MEASURE
        self.bus.write_byte_data(self.address, 0x08, 0x10)
        while (status := self._read_status()) >= 0x10:
            sleep(0.001)
        if status > 0x01:
            raise RuntimeError()  # TODO
        while not (self.bus.read_byte_data(self.address, 0xE1) & 0b10):
            sleep(0.001)
        data = _block_read(self.bus, self.address, 0x20, 132)
        # STOP
        self.bus.write_byte_data(self.address, 0x08, 0xFF)
        return TMF882xMeasurement.from_bytes(data, spad_map=self.spad_map)


    #####################
    ### Configuration ###
    #####################

    @property
    def measurement_period(self) -> int:
        with self._configuration_mode():
            return self.bus.read_word_data(self.address, register=0x24)

    @measurement_period.setter
    def measurement_period(self, value: int) -> None:
        with self._configuration_mode():
            self.bus.write_word_data(self.address, register=0x24, value=value)

    @property
    def kilo_iterations(self) -> int:
        with self._configuration_mode():
            return self.bus.read_word_data(self.address, register=0x26)

    @kilo_iterations.setter
    def kilo_iterations(self, value: int) -> None:
        with self._configuration_mode():
            self.bus.write_word_data(self.address, register=0x26, value=value)

    @property
    def confidence_threshold(self) -> int:
        with self._configuration_mode():
            return self.bus.read_byte_data(self.address, register=0x30)

    @confidence_threshold.setter
    def confidence_threshold(self, value: int) -> None:
        with self._configuration_mode():
            self.bus.write_byte_data(self.address, register=0x30, value=value)

    @property
    def spad_map(self) -> int:
        with self._configuration_mode():
            return self.bus.read_byte_data(self.address, register=0x34)

    @spad_map.setter
    def spad_map(self, map_id: int) -> None:
        with self._configuration_mode():
            self.bus.write_byte_data(self.address, register=0x34, value=map_id)

    ################
    ### Internal ###
    ################

    @contextmanager
    def _configuration_mode(self):
        # LOAD_CONFIG_PAGE
        self._send_command(0x16)
        # Verify config page is loaded
        data = self.bus.read_i2c_block_data(self.address, 0x20, 4)
        if data[0] != 0x16 or data[2] != 0xBC or data[3] != 0x00:
            raise RuntimeError()  # Configuration not correctly loaded.
        yield
        # WRITE_CONFIG_PAGE
        self._send_command(0x15)

    def _load_firmware(self):
        """Load the firmware into the device."""
        if self.app_id != 0x80:
            raise TMF882xException("Can only load firmware when in bootloader.")
        # DOWNLOAD INIT
        self._send_bootloader_command(0x14, [0x29])
        # SET ADDR
        self._send_bootloader_command(0x43, [0x00, 0x00])
        # W RAM
        driver = resources.read_binary("tmf882x", "firmware.bin")
        for chunk in _chunks(list(driver)):
            self._send_bootloader_command(0x41, chunk)
        # RAMREMAP RESET
        self._send_bootloader_command(0x11, [])
        sleep(0.003)

    def _send_bootloader_command(self, command: int, data: list[int]):
        """Send a command to the bootloader."""
        message = [command, len(data)] + data
        checksum = (sum(message) & 0xFF) ^ 0xFF
        message.append(checksum)
        self.bus.i2c_rdwr(i2c_msg.write(self.address, [0x08] + message))
        for i in range(100):
            if self._bootloader_status() == 0x00:
                return
            sleep(self.poll_delay)
        raise TMF882xException(f"Bootloader error {self._bootloader_status()}")

    def _bootloader_status(self) -> int:
        """Get the status of the bootloader."""
        self.bus.i2c_rdwr(i2c_msg.write(self.address, [0x08]))
        read = i2c_msg.read(self.address, 3)
        self.bus.i2c_rdwr(read)
        # Returns three fields: [value, size=0, checksum]
        return list(read)[0]


def _chunks(lst: list[int], chunk_size: int = 80) -> Iterable[list[int]]:
    i = 0
    while i < len(lst):
        yield lst[i : i + chunk_size]
        i += chunk_size


def _block_read(bus: SMBus, address: int, register: int, size: int) -> list[int]:
    result = []
    while size > 0:
        result += bus.read_i2c_block_data(address, register, min(size, 32))
        register += 32
        size -= 32
    return result
