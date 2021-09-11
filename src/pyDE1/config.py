"""
Copyright © 2021 Jeff Kletsky. All Rights Reserved.

License for this software, part of the pyDE1 package, is granted under
GNU General Public License v3.0 only
SPDX-License-Identifier: GPL-3.0-only

Deciding no how to handle "global" config is a bit more complicated
for multiprocessing than it is for a single process (with or without threads).

Since each process loads Python, to get the same config values for all processes
they all need to either read the same config file, or create copies of the
"original" for themselves. Using something like a multiprocessing.Manager()
seems excessive, as it is unlikely that the values will change during a run.
Leaving that open for the future makes some sense.

That means that each process will need to be either passed the name of the
config file to be read, or the results of that (and any changes prior to
creation of the child processes). Passing the config instance seems to be
no more complex than passing the file reference.

The config data should be easy to access in each of the modules.
Several options for "singleton" behavior:

1) Use a bare module

Advantages:

    Simple access

        import pyDE1.config as config
        do_something_with(config.section.VALUE)

    Only one instance "guaranteed"

Disadvantages:

    No top-level properties

        Though there may be a way to define them, the @property decorator
        will create a property object, but it doesn't seem useful.

        This is one of the main reasons that the Singleton object is used
        for the primary components of pyDE1 (the other is no dangling instances)


2) Module that defines an instance, refer to the instance

Advantages:

    Simple access

        from pyDE1.config import config
        do_something_with(config.section.VALUE)

Disadvantages:

    It is possible that second instance, disconnected from the "real" one,
    could be generated with config = Config()

3) Subclass Singleton

Advantages:

    Only one instance "guaranteed"

Disadvantages:

    More complex access

        from pyDE1.config import Config
        pointer_to_config = Config()    # At the module or function level
        do_something_with(config.section.VALUE)



"""

import logging
import sys
from typing import Optional

import toml

DEFAULT_CONFIG_FILE = '/usr/local/etc/pyde1/pyde1.conf'

logger = logging.getLogger('config')

class Config:

    # Enumerate here to keep from loading "phantom" sections
    sections = ('bluetooth',
                'de1',
                'database',
                'http',
                'logging',
                'mqtt')

    def __init__(self):

        self.bluetooth = self._Bluetooth()
        self.database = self._Database()
        self.de1 = self._DE1()
        self.http = self._HTTP(self)    # Calculating timeout needs bluetooth
        self.logging = self._Logging()
        self.mqtt = self._MQTT()

    # This craziness is so pyCharm autocompletes
    # Otherwise typing.SimpleNamespace() would be sufficient

    class _MQTT:
        def __init__(self):
            self.TOPIC_ROOT = 'pyDE1'
            self.CLIENT_ID_PREFIX = 'pyde1'
            self.BROKER_HOSTNAME = '::1'
            self.BROKER_PORT = 1883
            self.TRANSPORT = 'tcp'
            self.TLS_CONTEXT = None
            self.KEEPALIVE = 60
            self.USERNAME = None
            self.PASSWORD = None
            self.DEBUG = False



    class _HTTP:
        def __init__(self, parent):
            self.SERVER_HOST = ''
            self.SERVER_PORT = 1234
            self.SERVER_ROOT = '/'
            # adaptive_allonge.json is 7632 bytes
            self.PATCH_SIZE_LIMIT = 16384
            # Seconds, before abandoning the request
            self.ASYNC_TIMEOUT = 1.0
            # Seconds, 20*2 frames + head + tail at ~100 ms each
            self.PROFILE_TIMEOUT = 4.5
            self._response_timeout = None

            # If true, don't output nodes that have no value (write-only)
            # or are empty dicts
            # Otherwise math.nan fills in for the missing value
            # As not compliant with RFC 7159, some parsers may fail with NaN
            # although it is permitted by ECMAScript and JavaScript
            # A False setting is intended to be a development/exploration tool
            # This feature be considered as deprecated
            self.PRUNE_EMPTY_NODES = True

            self._parent = parent   # Path to get to bluetooth

        @property
        def RESPONSE_TIMEOUT(self):
            # See pyDE1/dispatcher/implementation.py
            # Right now, single timeout, bounded by scan/connect
            if self._response_timeout:
                retval = self._response_timeout
            else:
                retval = (  self._parent.bluetooth.SCAN_TIME
                          + self._parent.bluetooth.CONNECT_TIMEOUT
                          + self.ASYNC_TIMEOUT
                          + 0.100 )
            return retval

        @RESPONSE_TIMEOUT.setter
        def RESPONSE_TIMEOUT(self, value):
            self._response_timeout = value


    class _Logging:
        def __init__(self):
            self.LOG_DIRECTORY = '/var/log/pyde1/'
            # NB: The log file name is matched against [a-zA-Z0-9._-]
            self.LOG_FILENAME = 'combined.log'
            self.LEVEL_MAIN = logging.DEBUG
            self.LEVEL_MQTT = logging.INFO
            self.LEVEL_UPLOAD = logging.INFO

    def set_logging(self):
        # TODO: Collect these together
        logging.getLogger().setLevel(self.logging.LEVEL_MAIN)


    class _Bluetooth:
        def __init__(self):
            self.SCAN_TIME = 5  # Seconds
            self.CONNECT_TIMEOUT = 10  # Seconds
            self.DISCONNECT_TIMEOUT = 5  # Seconds
            self.SCAN_CACHE_EXPIRY = 300  # Seconds, probably too long
            self.RECONNECT_MAX_INTERVAL = 10 # Seconds
            # Files that hold the Bluetooth ID of connected devices
            # for potential cleanup by supervisor scripts
            self.ID_FILE_DIRECTORY = '/var/lib/pyde1/'
            self.ID_FILE_SUFFIX = '.btid'


    class _Database:
        def __init__(self):
            self.FILENAME = '/var/lib/pyde1/pyde1.sqlite3'
            self.BACKUP_TIMEOUT = 60  # seconds
            self.BACKUP_COMPRESSION_EXECUTABLE = 'xz'


    class _DE1:
        def __init__(self):
            self.LINE_FREQUENCY = 60
            self.MAX_WAIT_FOR_READY_EVENTS = 3.0
            # Do these "settings" belong here,
            # or should they be separated from parameters?
            self.DEFAULT_AUTO_OFF_TIME = None   # Minutes


    def load_from_toml(self, filename: Optional[str] = None):
        if filename is None:
            filename = DEFAULT_CONFIG_FILE
        parsed = {}
        try:
            parsed = toml.load(filename)
        except FileNotFoundError as e:
            if filename != DEFAULT_CONFIG_FILE:
                logger.critical(
                    f"Unable to open config file '{filename}', exiting.")
                raise e
            else:
                logger.warning(
                    f"Could not find default config file {DEFAULT_CONFIG_FILE}")
                return

        except Exception as e:
            logger.critical(
                f"Error parsing config from '{filename}', exiting.")
            raise e

        for table, kv_dict in parsed.items():
            lc_table = table.lower()
            try:
                if lc_table not in self.sections:
                    raise KeyError
                section = getattr(self, lc_table)
                for k,v in kv_dict.items():
                    uc_key = k.upper()
                    if hasattr(section, uc_key) and not uc_key.startswith('_'):
                        if lc_table == 'logging':
                            if uc_key.startswith('LEVEL_'):
                                if isinstance(v, str):
                                    v = logging._nameToLevel[
                                        v.removeprefix('logging.')]
                        setattr(section, uc_key, v)
                    else:
                        logger.warning(
                            f"Config: '{k}' is not valid in [{table}], ignoring.")
            except KeyError:
                logger.warning(
                    f"Config: '{table}' is not a valid config table, ignoring.")

        logger.info(f"Config loaded from {filename}")


config = Config()