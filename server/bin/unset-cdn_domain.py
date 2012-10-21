#!/usr/bin/env python
import os
import motor
import shutil
from tornado import gen
from tornado.ioloop import IOLoop
import redis.client
import sys
sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(__file__), '..')))
import settings



@gen.engine
def run(*fileids):
    _redis = redis.client.Redis(
        settings.REDIS_HOST,
        settings.REDIS_PORT
    )
    connection = motor.MotorConnection().open_sync()
    db = connection.tiler

    try:
        cursor = db.images.find({'fileid': {'$in': fileids}})
        for document in (yield motor.Op(cursor.to_list)):
            print document
            yield motor.Op(
                db.images.update,
                {'_id': document['_id']},
                {'$set': {'cdn_domain': None}}
            )
            metadata_key = 'metadata:%s' % document['fileid']
            if _redis.get(metadata_key):
                print "Invalidated metadata cache"
                _redis.delete(metadata_key)
            lock_key = 'uploading:%s' % document['fileid']
            # locking it from aws upload for 1 hour
            _redis.setex(lock_key, 1, 60 * 60)

    finally:
        IOLoop.instance().stop()


if __name__ == '__main__':
    import sys
    if not sys.argv[1:]:
        print "%s fileid1 fileid2 fileidN" % __file__
        exit()
    run(*sys.argv[1:])
    IOLoop.instance().start()
