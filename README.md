# tmf882x-driver
Easy-to-use python driver for the AMS [TMF8820](https://ams.com/tmf8820) and  [TMF8821](https://ams.com/tmf8821) ToF sensors

![GitHub Workflow Status](https://img.shields.io/github/actions/workflow/status/rogiervandergeer/tmf882x-driver/test.yaml?branch=main) 
![PyPI](https://img.shields.io/pypi/v/tmf882x-driver)
![PyPI - License](https://img.shields.io/pypi/l/tmf882x-driver)
![PyPI - Downloads](https://img.shields.io/pypi/dm/tmf882x-driver) 

## Installation

The package is available on [PyPI](https://pypi.org/project/tmf882x-driver/). Installation is can be done with your favourite package manager. For example:

```bash
pip install tmf882x-driver
```

## Usage
In order to initialise the device we need an open `SMBus` object. 
Depending on the machine that you are running on you may need to provide another bus number or path:
```python
from smbus2 import SMBus
from tmf882x import TMF882x


with SMBus(1) as bus:
    device = TMF882x(bus=bus)
```

The address of the `TMF882x` defaults to `0x41`. If your device's address is different, you can provide it 
like `TMF882x(bus=bus, address=0x59)`.

When powering up, the device is in standby mode. To enable it, call `device.enable()`, and subsequently
put it back in standby using `device.standby()`. Or better yet, use a context manager:

```python

with device:
    pass  # Here the device is enabled.
```

### Measuring

To make a measurement, do:

```python
with device:
    measurement = device.measure()
```

This will yield a `TMF882xMeasurement`, which has (among others) the following fields:

- `result_number`, an incremental counter for deduplicating results,
- `temperature`, the device's temperature in degrees C.
- `ambient_light`, a measure for the ambient light,
- `photon_count`, the number of photons measured.
- `results`, a list of SPAD results.

The property `measurement.grid` will returns a list-of-list of results,
representing the actual arrangement of SPADs. Each result has a `confidence` (the confidence of measurement, 255 is absolutely sure, 0 when no result)
and a `distance` in mm (0 when no result), as well as a `secondary_confidence` and `secondary_distance` for a secondary object.

The measurement also has `primary_grid` and `secondary_grid` properties which return list-of-list-of-ints of the primary
and secondary distances.
 
For example:

```python
with device:
    print(device.measure().primary_grid)
```
might yield `[[0, 169, 196], [131, 197, 240], [192, 214, 199], [256, 210, 190], [185, 183, 165], [182, 185, 169]]`.

### Configuration

The following configuration options are implemented:

- `measurement_period`, the measurement period in ms (default = 33)
- `kilo_iterations`, number of measurement iterations x 1024 (default = 537, representing 549888 iterations)
- `confidence_threshold`, confidence threshold below which measurements are 0 (default = 6, max = 255).
- `spad_map`, defining the configuration of SPADs (see below). 

To get / set a configuration field, do for example:

```python
with device:
    print(device.measurement_period)
    device.spad_map = 6
```


#### SPAD maps

For a full list of pre-programmed SPAD Maps, see [page 23 of this document](https://cdn.sparkfun.com/assets/learn_tutorials/2/2/8/9/TMF8820_TMF8821_Host_Driver_Communication_AN001015_3-00.pdf),
but a few useful ones are:
- `1`: normal 3x3,
- `6`: wide 3x3,
- `7`: normal 4x4 (TMF8821 only),
- `10`: 3x6 (TMF8821 only).

### Calibration

The device is supposed to be calibrated before use.

The calibration test shall be done in the final housing with minimal ambient light and
no target within 40 cm in field of view of the device. The calibration generates
a calibration data set, which should be permanently stored on the host.

The calibration data can be loaded after power-up using the write_calibration method.
Note that the calibration data is tied to the spad map. Any change in spad map requires
re-calibration (and/or loading of other calibration data).

For example:

```python
with device:
    calibration_data = device.calibrate()
```

And to restore:
```python
with device:
    device.write_calibration(calibration_data)
```

After a measurement, you can check the `calibration_ok` property to see whether calibration was successful. 

### References

See the [datasheet](https://cdn.sparkfun.com/assets/learn_tutorials/2/2/8/9/TMF882X_DataSheet.pdf)
and the [communication note](https://cdn.sparkfun.com/assets/learn_tutorials/2/2/8/9/TMF8820_TMF8821_Host_Driver_Communication_AN001015_3-00.pdf)
for more details.
