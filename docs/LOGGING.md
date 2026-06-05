# Logging

The OSCAL library uses the [Loguru](https://loguru.readthedocs.io/en/stable/) library for logging. 
Log messages from the library are disabled. 

To enable logging within the class, add the following to the top of your module:

```python

from loguru import logger
logger.enable("oscal")

```
