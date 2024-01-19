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

See the [datasheet](https://cdn.sparkfun.com/assets/learn_tutorials/2/2/8/9/TMF882X_DataSheet.pdf) for more details.
