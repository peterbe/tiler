#!/usr/bin/env python
import os
import motor
import shutil
from tornado import gen
from tornado.ioloop import IOLoop
import redis.client
import sys
ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, ROOT)
import settings


HERE = os.path.dirname(__file__)

@gen.engine
def run(*fileids):
    _redis = redis.client.Redis(
        settings.REDIS_HOST,
        settings.REDIS_PORT
    )
    connection = motor.MotorConnection().open_sync()
    db = connection.tiler
    cursor = db.images.find({'fileid': {'$in': fileids}})
    _ids = []
    for document in (yield motor.Op(cursor.to_list)):
        print document
        image_split = document['fileid'][:1] + '/' + document['fileid'][1:3] + '/' + document['fileid'][3:]
        for each in ('tiles', 'uploads', 'thumbnails'):
            d = os.path.join(HERE, '..', 'static', 'tiles', image_split)
            d = os.path.normpath(d)
            if os.path.isdir(d):
                print "DEL", d
                shutil.rmtree(d)

        metadata_key = 'metadata:%s' % document['fileid']
        if _redis.get(metadata_key):
            print "Invalidated metadata cache"
            _redis.delete(metadata_key)
        lock_key = 'uploading:%s' % document['fileid']
        _redis.delete(lock_key)

        all_fileids_key = 'allfileids'
        _redis.delete(all_fileids_key)
        all_fileids_key += ':%s' % document['user']
        _redis.delete(all_fileids_key)

        cache_keys_key = 'thumbnail_grid:keys'
        for key in _redis.lrange(cache_keys_key, 0, -1):
            _redis.delete(key)
        _redis.delete(cache_keys_key)

        yield motor.Op(
            db.images.remove,
            {'_id': document['_id']}
        )

    IOLoop.instance().stop()


if __name__ == '__main__':
    import re
    import sys
    if not sys.argv[1:]:
        print "%s fileid1 fileid2 fileidN" % __file__
        exit()
    fileids = []
    for each in sys.argv[1:]:
        if len(each) == 9:
            fileid = each
        elif '://' in each:
            fileid = re.findall('[a-f0-9]{9}', each)[0]
        fileids.append(fileid)
    run(*fileids)
    IOLoop.instance().start()
