import datetime
import threading
import json
import sys

from ..shared_code import context
from ..shared_code import tracing
from ..shared_code import azure, const
from ..shared_code.providerfactory import *

import azure.functions as func
###############################################################################

class ProviderInstanceThread(threading.Thread):
   def __init__(self, providerInstance):
      threading.Thread.__init__(self)
      self.providerInstance = providerInstance

   def run(self):
      global ctx, tracer
      for check in self.providerInstance.checks:
         tracer.info("starting check %s" % (check.fullName))

         # Skip this check if it's not enabled or not due yet
         if (check.isEnabled() == False) or (check.isDue() == False):
            continue

         # Run all actions that are part of this check
         resultJson = check.run()

         # Ingest result into Log Analytics
         ctx.azLa.ingest(check.customLog,
                         resultJson,
                         check.colTimeGenerated)

         # Persist updated internal state to provider state file
         self.providerInstance.writeState()

         # Ingest result into Customer Analytics
         enableCustomerAnalytics = ctx.globalParams.get("enableCustomerAnalytics", True)
         if enableCustomerAnalytics and check.includeInCustomerAnalytics:
             tracing.tracing.ingestCustomerAnalytics(tracer,
                                             ctx,
                                             check.customLog,
                                             resultJson)
         tracer.info("finished check %s" % (check.fullName))
      return

###############################################################################
# Load entire config from KeyVault (global parameters and provider instances)
def loadConfig() -> bool:
   global ctx, tracer
   tracer.info("loading config from KeyVault")

   secrets = ctx.azKv.getCurrentSecrets()
   for secretName in secrets.keys():
      tracer.debug("parsing KeyVault secret %s" % secretName)
      secretValue = secrets[secretName]
      try:
         providerProperties = json.loads(secretValue)
      except json.decoder.JSONDecodeError as e:
         tracer.error("invalid JSON format for secret %s (%s)" % (secretName,
                                                                  e))
         continue
      if secretName == const.CONFIG_SECTION_GLOBAL:
         ctx.globalParams = providerProperties
         tracer.debug("successfully loaded global config")
      else:
         instanceName = providerProperties.get("name", None)
         providerType = providerProperties.get("type", None)
         try:
            providerInstance = ProviderFactory.makeProviderInstance(providerType,
                                                                    tracer,
                                                                    ctx,
                                                                    providerProperties,
                                                                    skipContent = False)
         except Exception as e:
            tracer.error("could not validate provider instance %s (%s)" % (instanceName,
                                                                           e))
            continue
         ctx.instances.append(providerInstance)
         tracer.debug("successfully loaded config for provider instance %s" % instanceName)
   if ctx.globalParams == {} or len(ctx.instances) == 0:
      tracer.error("did not find any provider instances in KeyVault")
      return False
   return True

# Execute the actual monitoring payload
def monitor() -> None:
   global ctx, tracer
   tracer.info("starting monitor payload")

   threads = []
   if not loadConfig():
      tracer.critical("failed to load config from KeyVault")
      sys.exit(const.ERROR_LOADING_CONFIG)
   logAnalyticsWorkspaceId = ctx.globalParams.get("logAnalyticsWorkspaceId", None)
   logAnalyticsSharedKey = ctx.globalParams.get("logAnalyticsSharedKey", None)
   if not logAnalyticsWorkspaceId or not logAnalyticsSharedKey:
      tracer.critical("global config must contain logAnalyticsWorkspaceId and logAnalyticsSharedKey")
      sys.exit(const.ERROR_GETTING_LOG_CREDENTIALS)
   ctx.azLa = azure.AzureLogAnalytics(tracer,
                                logAnalyticsWorkspaceId,
                                logAnalyticsSharedKey)
   for i in ctx.instances:
      thread = ProviderInstanceThread(i)
      thread.start()
      threads.append(thread)

   for t in threads:
      t.join()

   tracer.info("monitor payload successfully completed")
   return

def main(mytimer: func.TimerRequest) -> None:
    global ctx, tracer
    tracer = tracing.initTracer()
    ctx = context.Context(tracer, "monitor")
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    if mytimer.past_due:
        tracer.info('Persia test The timer is past due!')

    monitor()
    tracer.info('Persia\'s Python timer trigger function ran at %s', utc_timestamp)
