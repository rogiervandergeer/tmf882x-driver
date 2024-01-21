from dataclasses import dataclass

from tmf882x import SPAD_MAP_DIMENSIONS


@dataclass
class TMF882xSpadResult:
    confidence: int
    distance: int
    secondary_confidence: int
    secondary_distance: int
    histogram: list[int] | None = None


@dataclass
class TMF882xMeasurement:
    result_number: int
    temperature: int
    n_valid_results: int
    ambient_light: int
    photon_count: int
    reference_count: int
    system_tick: int
    results: list[TMF882xSpadResult]
    spad_map: int

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
                TMF882xSpadResult(
                    confidence=data[24 + 3 * i],
                    distance=int.from_bytes(data[25 + 3 * i : 27 + 3 * i], "little"),
                    secondary_confidence=data[24 + 3 * (i + 18)],
                    secondary_distance=int.from_bytes(data[25 + 3 * (i + 18) : 27 + 3 * (i + 18)], "little"),
                )
                for i in range(18)
            ],
            spad_map=spad_map,
        )

    @property
    def grid(self) -> list[list[TMF882xSpadResult]]:
        try:
            x, y = SPAD_MAP_DIMENSIONS[self.spad_map]
        except KeyError:
            raise NotImplementedError("Result grid not implemented for custom spad maps.")
        if x == 4 and y == 4:
            applicable_results = self.results[0:8] + self.results[9:17]
        else:
            applicable_results = self.results[0 : (x * y)]

        return [[applicable_results[column + x * row] for column in range(x)] for row in range(y)]

    @property
    def primary_grid(self) -> list[list[int]]:
        return [[column.distance for column in row] for row in self.grid]

    @property
    def secondary_grid(self) -> list[list[int]]:
        return [[column.secondary_distance for column in row] for row in self.grid]
