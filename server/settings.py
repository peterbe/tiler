COOKIE_SECRET = 'override this with local settings'

DATABASE_NAME = 'tiler'

REDIS_HOST = 'localhost'
REDIS_PORT = 6379

# complete this in your local_settings.py to get emails sent on errors
ADMIN_EMAILS = (
)


from local_settings import *

assert BROWSERID_DOMAIN
