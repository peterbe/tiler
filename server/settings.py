COOKIE_SECRET = 'override this with local settings'

DATABASE_NAME = 'tiler'

REDIS_HOST = 'localhost'
REDIS_PORT = 6379

PROJECT_TITLE = 'Tiler'

# complete this in your local_settings.py to get emails sent on errors
ADMIN_EMAILS = (
)

DEFAULT_CDN_TILER_DOMAIN = 'd220r9wol91huc.cloudfront.net'
TILES_BUCKET_ID = 'tiler-tiles'
ORIGINALS_BUCKET_ID = 'tiler-originals'

from local_settings import *

assert BROWSERID_DOMAIN
assert AWS_ACCESS_KEY
assert AWS_SECRET_KEY
