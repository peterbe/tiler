#!/usr/bin/env python
import os
import motor
import shutil
from pprint import pprint
from tornado import gen
from tornado.ioloop import IOLoop
import redis.client
import sys
ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
import settings



@gen.engine
def run(*fileids):
    _redis = redis.client.Redis(
        settings.REDIS_HOST,
        settings.REDIS_PORT
    )
    connection = motor.MotorClient().open_sync()
    db = connection.tiler

    try:
        cursor = db.images.find({'fileid': {'$in': fileids}})
        for document in (yield motor.Op(cursor.to_list)):
            pprint(document)
            yield motor.Op(
                db.images.update,
                {'_id': document['_id']},
                {'$set': {'featured': False}}
            )

            cache_keys_key = 'thumbnail_grid:keys'
            for key in _redis.lrange(cache_keys_key, 0, -1):
                _redis.delete(key)
            _redis.delete(cache_keys_key)

    finally:
        IOLoop.instance().stop()


if __name__ == '__main__':
    import sys
    if not sys.argv[1:]:
        print "%s fileid1 fileid2 fileidN" % __file__
        exit()
    run(*sys.argv[1:])
    IOLoop.instance().start()
