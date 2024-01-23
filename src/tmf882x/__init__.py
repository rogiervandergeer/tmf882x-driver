from contextlib import contextmanager
from enum import Enum
from importlib import resources
from time import sleep
from typing import Iterable

from smbus2 import SMBus, i2c_msg

from tmf882x.constants import SPAD_MAP_DIMENSIONS
from tmf882x.measurement import TMF882xMeasurement


class TMF882xException(RuntimeError):
    pass


class TMF882x:
    def __init__(self, bus: SMBus, address: int = 0x41, poll_delay: float = 0.001):
        self.address = address
        self.bus = bus
        self.poll_delay = poll_delay

    @property
    def mode(self) -> int:
        return self.bus.read_byte_data(self.address, 0xE0) & 0xCF  # Ignore bits 4 & 5

    @property
    def serial_number(self) -> int:
        """Read the serial number of the device."""
        data = self.bus.read_i2c_block_data(self.address, 0x1C, 4)
        return int.from_bytes(data, "little")

    def enable(self, auto_load_firmware: bool = True) -> None:
        """Enable the device."""
        self.bus.write_byte_data(self.address, 0xE0, 0x21)
        for _ in range(100):
            if self.mode == 0x04:
                break
            sleep(self.poll_delay)
        if self.mode != 0x04:
            raise TMF882xException(f"Failed to set mode to enabled. Mode is: {self.mode}.")
        if self.app_id == 0x80 and auto_load_firmware:
            self._load_firmware()

    def standby(self) -> None:
        """Set the device in standby mode."""
        self.bus.write_byte_data(self.address, 0xE0, 0x20)  # Set wake-up to application.
        for _ in range(100):
            if self.mode == 0x02:
                return
            sleep(self.poll_delay)
        raise TMF882xException(f"Failed to set mode to standby. Mode is: {self.mode}.")

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

    def measure(self) -> TMF882xMeasurement:
        # Clear interrupts
        self.bus.write_byte_data(self.address, 0xE1, 0xFF)
        # MEASURE
        self._send_command(0x10)
        while not (self.bus.read_byte_data(self.address, 0xE1) & 0b10):
            sleep(self.poll_delay)
        data = _block_read(self.bus, self.address, 0x20, 132)
        # STOP
        self.bus.write_byte_data(self.address, 0x08, 0xFF)
        return TMF882xMeasurement.from_bytes(data, spad_map=self.spad_map)

    ###################
    ### Calibration ###
    ###################

    def calibrate(self) -> bytes:
        """
        Perform factory calibration.

        The calibration test shall be done in a housing with minimal ambient light and
        no target within 40 cm in field of view of the device. The calibration generates
        a calibration data set, which should be permanently stored on the host.

        The calibration data can be loaded after power-up using the write_calibration method.
        Note that the calibration data is tied to the spad map. Any change in spad map requires
        re-calibration (and/or loading of other calibration data).
        """
        # Set iterations to 4M
        iterations = self.kilo_iterations
        self.kilo_iterations = 4000
        # Perform calibration
        self._send_command(0x20)
        # Load calibration page
        self._send_command(0x19)
        # Read calibration data
        data = _block_read(self.bus, self.address, 0x20, 192)
        # Write config page
        self._send_command(0x15)
        # Reset the # of iterations
        self.kilo_iterations = iterations
        return bytes(data[4:])

    def write_calibration(self, data: bytes) -> None:
        """
        Write calibration data to the device.
        """
        if len(data) != 188:
            raise ValueError("Calibration data must be 188 bytes long.")
        # Load calibration page
        self._send_command(0x19)
        _block_write(self.bus, self.address, 0x24, list(data))
        # WRITE_CONFIG_PAGE
        self._send_command(0x15)

    @property
    def calibration_ok(self) -> bool:
        """
        Calibration status.

        This is True if the last measurement was performed with correct calibration.
        """
        return self.bus.read_byte_data(self.address, register=0x07) == 0x00

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
            raise TMF882xException("Configuration not loaded as expected.")
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

    def _read_status(self) -> int:
        return self.bus.read_byte_data(self.address, 0x08)

    def _send_command(self, command: int) -> None:
        self.bus.write_byte_data(self.address, 0x08, command)
        while (status := self._read_status()) >= 0x10:
            sleep(self.poll_delay)
        if status > 0x01:
            raise TMF882xException(f"Command failed with status {status}.")


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


def _block_write(bus: SMBus, address: int, register: int, data: list[int]) -> None:
    while len(data):
        bus.write_i2c_block_data(address, register, data[:32])
        register += 32
        data = data[32:]
