import datetime

from helper.context import *
from helper.tracing import *

import azure.functions as func


def main(mytimer: func.TimerRequest) -> None:

    tracer = tracing.initTracer()
    ctx = Context(tracer, "monitor")
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    if mytimer.past_due:
        tracer.info('Persia test The timer is past due!')

    tracer.info('Persia\'s Python timer trigger function ran at %s', utc_timestamp)
