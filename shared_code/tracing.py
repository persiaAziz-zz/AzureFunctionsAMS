# Azure modules
from azure_storage_logging.handlers import QueueStorageHandler


# Python modules
import argparse
# from collections import OrderedDict
import logging.config

# Payload modules
from .azure import *
from .const import *
#from .const import JsonFormatter

# Helper class to enable all kinds of tracing
class tracing:
   config = {
       "version": 1,
       "disable_existing_loggers": True,
       "formatters": {
           "json": {
               "class": "__app__.shared_code.const.JsonFormatter",
               "fieldMapping": {
                   "pid": "process",
                   "timestamp": "asctime",
                   "traceLevel": "levelname",
                   "module": "filename",
                   "lineNum": "lineno",
                   "function": "funcName",
                   "payloadVersion": "payloadversion",
                   "sapmonId": "sapmonid"
               }
           },
           "detailed": {
               "format": "[%(process)d] %(asctime)s %(levelname).1s %(filename)s:%(lineno)d %(message)s"
           },
           "simple": {
               "format": "%(levelname)-8s %(message)s"
           }
       },
       "handlers": {
           "consolex": {
               "class": "logging.StreamHandler",
               "formatter": "simple",
               "level": DEFAULT_CONSOLE_TRACE_LEVEL
           },
           "console": {
               "class": "logging.StreamHandler",
               "formatter": "simple",
               "level": DEFAULT_CONSOLE_TRACE_LEVEL
           },
       },
       "root": {
           "level": logging.DEBUG,
           "handlers": ["console"]
       }
   }

   # Initialize the tracer object
   @staticmethod
   def initTracer() -> logging.Logger:
      tracing.config["handlers"]["console"]["formatter"] = "detailed"
      tracing.config["handlers"]["console"]["level"] = logging.DEBUG
      logging.config.dictConfig(tracing.config)
      return logging.getLogger(__name__)

   # Add a storage queue log handler to an existing tracer
   @staticmethod
   def addQueueLogHandler(
           tracer: logging.Logger,
           ctx) -> None:
      # Provide access to custom (payload-specific) fields
      oldFactory = logging.getLogRecordFactory()
      def recordFactory(*args, **kwargs):
         record = oldFactory(*args, **kwargs)
         record.sapmonid = ctx.sapmonId
         record.payloadversion = PAYLOAD_VERSION
         return record
      tracer.info("adding storage queue log handler")
      try:
         storageQueue = AzureStorageQueue(tracer,
                                          ctx.sapmonId,
                                          ctx.vmInstance["subscriptionId"],
                                          ctx.vmInstance["resourceGroupName"],
                                          queueName = STORAGE_QUEUE_NAMING_CONVENTION % ctx.sapmonId)
         storageKey = tracing.getAccessKeys(tracer, ctx)
         queueStorageLogHandler = QueueStorageHandler(account_name=storageQueue.accountName,
                                                      account_key = storageKey,
                                                      protocol = "https",
                                                      queue = storageQueue.name)
         queueStorageLogHandler.level = DEFAULT_QUEUE_TRACE_LEVEL
         jsonFormatter = JsonFormatter(tracing.config["formatters"]["json"]["fieldMapping"])
         queueStorageLogHandler.setFormatter(jsonFormatter)
         logging.setLogRecordFactory(recordFactory)

      except Exception as e:
         tracer.error("could not add handler for the storage queue logging (%s) " % e)
         return

      queueStorageLogHandler.level = DEFAULT_QUEUE_TRACE_LEVEL
      tracer.addHandler(queueStorageLogHandler)
      return

   # Initialize customer metrics tracer object
   @staticmethod
   def initCustomerAnalyticsTracer(tracer: logging.Logger,
                                   ctx) -> logging.Logger:
       tracer.info("creating customer metrics tracer object")
       try:
           storageQueue = AzureStorageQueue(tracer,
                                            ctx.sapmonId,
                                            ctx.vmInstance["subscriptionId"],
                                            ctx.vmInstance["resourceGroupName"],
                                            CUSTOMER_METRICS_QUEUE_NAMING_CONVENTION % ctx.sapmonId)
           storageKey = tracing.getAccessKeys(tracer, ctx)
           customerMetricsLogHandler = QueueStorageHandler(account_name = storageQueue.accountName,
                                                           account_key = storageKey,
                                                           protocol = "https",
                                                           queue = storageQueue.name)
       except Exception as e:
           tracer.error("could not add handler for the storage queue logging (%s) " % e)
           return

       logger = logging.getLogger("customerMetricsLogger")
       logger.addHandler(customerMetricsLogHandler)
       return logger

   # Ingest metrics into customer analytics
   @staticmethod
   def ingestCustomerAnalytics(tracer: logging.Logger,
                               ctx,
                               customLog: str,
                               resultJson: str) -> None:
      tracer.info("sending customer analytics")
      results = json.loads(resultJson)
      for result in results:
         metrics = {
            "Type": customLog,
            "Data": result,
         }
         j = json.dumps(metrics)
         ctx.analyticsTracer.debug(j)
      return

   # Fetches the storage access keys from keyvault or directly from storage account
   @staticmethod
   def getAccessKeys(tracer: logging.Logger, ctx) -> str:
      try :
         tracer.info("fetching queue access keys from key vault")
         kv = AzureKeyVault(tracer,
                            KEYVAULT_NAMING_CONVENTION % ctx.sapmonId,
                            ctx.msiClientId)
         return kv.getSecret(STORAGE_ACCESS_KEY_NAME).value
      except Exception as e:
         tracer.warning("unable to get access keys from key vault, fetching from storage account (%s) " % e)

      tracer.info("fetching queue access keys from storage account")
      storageQueue = AzureStorageQueue(tracer,
                                       ctx.sapmonId,
                                       ctx.vmInstance["subscriptionId"],
                                       ctx.vmInstance["resourceGroupName"],
                                       CUSTOMER_METRICS_QUEUE_NAMING_CONVENTION % ctx.sapmonId)
      return storageQueue.getAccessKey()
