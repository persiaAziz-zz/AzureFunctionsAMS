import datetime
import logging

import azure.functions as func


def main(mytimer: func.TimerRequest) -> None:
    utc_timestamp = datetime.datetime.utcnow().replace(
        tzinfo=datetime.timezone.utc).isoformat()

    if mytimer.past_due:
        logging.info('Persia test The timer is past due!')

    logging.info('Persia\'s Python timer trigger function ran at %s', utc_timestamp)
