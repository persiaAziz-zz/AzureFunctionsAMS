#!/usr/bin/env python3
#
#       Azure Monitor for SAP Solutions payload script
#       (deployed on collector VM)
#
#       License:        GNU General Public License (GPL)
#       (c) 2020        Microsoft Corp.
#

# Python modules
import re
import sys
import os

# Payload modules
from _app_.shared_code.tracing import *
from _app_.shared_code.const import *
from _app_.shared_code.azure import *

# Internal context handler
class Context(object):
   azKv = None
   sapmonId = None
   vmInstance = None
   vmTage = None
   analyticsTracer = None
   tracer = None

   globalParams = {}
   instances = []

   def __init__(self,
                tracer,
                operation: str):
      self.tracer = tracer
      self.tracer.info("initializing context")

      # Retrieve sapmonId via IMDS
      # self.vmInstance = azure.AzureInstanceMetadataService.getComputeInstance(self.tracer, operation)
      self.vmInstance = dict()
      self.vmInstance["subscriptionId"] = os.environ["SUBSCRIPTION_ID"]
      self.vmInstance["resourceGroupName"] = os.environ["RESOURCE_GROUP"]
      # vmName = self.vmInstance.get("name", None)
      # if not vmName:
      #    self.tracer.critical("could not obtain VM name from IMDS")
      #    sys.exit(const.ERROR_GETTING_SAPMONID)
      try:
         #self.sapmonId = re.search("sapmon-vm-(.*)", vmName).group(1)
         self.sapmonId = os.environ["SAPMON_ID"]
      except AttributeError:
         self.tracer.critical("could not extract sapmonId from VM name")
         sys.exit(const.ERROR_GETTING_SAPMONID)

      self.msiClientId = os.environ["MSI_CLIENT_ID"]

      self.tracer.debug("sapmonId=%s" % self.sapmonId)
      self.tracer.debug("msiClientId=%s" % self.msiClientId)

      # Add storage queue log handler to tracer
      tracing.addQueueLogHandler(self.tracer, self)

      # Initializing tracer for emitting metrics
      self.analyticsTracer = tracing.initCustomerAnalyticsTracer(self.tracer, self)

      # Get KeyVault
      self.azKv = azure.AzureKeyVault(self.tracer,
                                const.KEYVAULT_NAMING_CONVENTION % self.sapmonId,
                                msiClientId = self.msiClientId)
      if not self.azKv.exists():
         sys.exit(const.ERROR_KEYVAULT_NOT_FOUND)

      self.tracer.info("successfully initialized context")
