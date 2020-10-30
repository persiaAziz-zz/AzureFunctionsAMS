# Python modules
import logging
import os
from collections import OrderedDict
from typing import Tuple
from typing import Callable, Dict, Optional
import json

# Version of the payload script
PAYLOAD_VERSION = "2.4"

# Default file/directory locations
PATH_PAYLOAD       = os.path.dirname(os.path.realpath(__file__))
PATH_ROOT          = os.path.abspath(os.path.join(PATH_PAYLOAD, "../PersiaHttpExample2/sapmon/payload"))
PATH_CONTENT       = os.path.join(PATH_PAYLOAD, "content")
PATH_TRACE         = os.path.join(PATH_ROOT, "trace")
PATH_STATE         = os.path.join(PATH_ROOT, "state")
FILENAME_TRACE     = os.path.join(PATH_TRACE, "sapmon.trc")

# Time formats
TIME_FORMAT_LOG_ANALYTICS = "%a, %d %b %Y %H:%M:%S GMT"
TIME_FORMAT_JSON          = "%Y-%m-%dT%H:%M:%S.%fZ"
TIME_FORMAT_HANA          = "%Y-%m-%d %H:%M:%S.%f"

# Trace levels
DEFAULT_CONSOLE_TRACE_LEVEL = logging.DEBUG
DEFAULT_FILE_TRACE_LEVEL    = logging.INFO
DEFAULT_QUEUE_TRACE_LEVEL   = logging.DEBUG

# Config parameters
CONFIG_SECTION_GLOBAL = "-global-"
METHODNAME_ACTION     = "_action%s"
STORAGE_ACCESS_KEY_NAME = "storageAccessKey"

# Naming conventions for generated resources
KEYVAULT_NAMING_CONVENTION               = "sapmon-kv-%s"
STORAGE_ACCOUNT_NAMING_CONVENTION        = "sapmonsto%s"
STORAGE_QUEUE_NAMING_CONVENTION          = "sapmon-que-%s"
CUSTOMER_METRICS_QUEUE_NAMING_CONVENTION = "sapmon-anl-%s"

# Error codes
ERROR_GETTING_AUTH_TOKEN       = 10
ERROR_GETTING_SAPMONID         = 11
ERROR_SETTING_KEYVAULT_SECRET  = 20
ERROR_KEYVAULT_NOT_FOUND       = 21
ERROR_GETTING_LOG_CREDENTIALS  = 22
ERROR_GETTING_HANA_CREDENTIALS = 23
ERROR_HANA_CONNECTION          = 30
ERROR_FILE_PERMISSION_DENIED   = 40
ERROR_ONBOARDING               = 50
ERROR_LOADING_CONFIG           = 60
ERROR_ADDING_PROVIDER          = 70
ERROR_DELETING_PROVIDER        = 80

# Formats a log/trace payload as JSON-formatted string
class JsonFormatter(logging.Formatter):
   def __init__(self,
                fieldMapping: Dict[str, str] = {},
                datefmt: Optional[str] = None,
                customJson: Optional[json.JSONEncoder] = None):
      logging.Formatter.__init__(self, None, datefmt)
      self.fieldMapping = fieldMapping
      self.customJson = customJson

   # Overridden from the parent class to look for the asctime attribute in the fields attribute
   def usesTime(self) -> bool:
      return "asctime" in self.fieldMapping.values()

   # Formats time using a specific date format
   def _formatTime(self,
                   record: logging.LogRecord) -> None:
      if self.usesTime():
         record.asctime = self.formatTime(record, self.datefmt)

   # Combines any supplied fields with the log record msg field into an object to convert to JSON
   def _getJsonData(self,
                    record: logging.LogRecord) -> OrderedDict():
      if len(self.fieldMapping.keys()) > 0:
         # Build a temporary list of tuples with the actual content for each field
         jsonContent = []
         for f in sorted(self.fieldMapping.keys()):
            jsonContent.append((f, getattr(record, self.fieldMapping[f])))
         jsonContent.append(("msg", record.msg))

         # An OrderedDict is used to ensure that the converted data appears in the same order for every record
         return OrderedDict(jsonContent)
      else:
         return record.msg

   # Overridden from the parent class to take a log record and output a JSON-formatted string
   def format(self,
              record: logging.LogRecord) -> str:
      self._formatTime(record)
      jsonData = self._getJsonData(record)
      formattedJson = json.dumps(jsonData, cls=self.customJson)
      return formattedJson