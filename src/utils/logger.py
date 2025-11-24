import logging, sys
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
)
logger = logging.getLogger('account-plan-agent')
