import time
import os
from twython import Twython
import settings


def tweet_with_media(text, file_path):
    assert os.path.isfile(file_path), file_path

    t0 = time.time()
    twitter = Twython(
        twitter_token=settings.TWITTER_CONSUMER_KEY,
        twitter_secret=settings.TWITTER_CONSUMER_SECRET,
        oauth_token=settings.TWITTER_ACCESS_TOKEN,
        oauth_token_secret=settings.TWITTER_ACCESS_TOKEN_SECRET
    )
    t1 = time.time()
    new_entry = twitter.updateStatusWithMedia(
        file_path,
        status=text
    )
    t2 = time.time()
    print "Took %s seconds to connect" % (t1 - t0)
    print "Took %s seconds to tweet with media" % (t2 - t1)
    return new_entry['id']
