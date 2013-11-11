#!/usr/bin/env python
import os
import time
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
def run(*args):
    _redis = redis.client.Redis(
        settings.REDIS_HOST,
        settings.REDIS_PORT
    )
    connection = motor.MotorClient().open_sync()
    db = connection.tiler

    try:
        cursor = (
            db.comments.find()
        )
        comment = yield motor.Op(cursor.next_object)
        _fileids = {}
        while comment:
            if comment['image'] not in _fileids:
                image = yield motor.Op(
                    db.images.find_one,
                    {'_id': comment['image']}
                )
                _fileids[comment['image']] = image['fileid']
            fileid = _fileids[comment['image']]
            print fileid
            _redis.hincrby('comments', fileid, 1)
            print _redis.hget('comments', fileid)
            #_redis.incr('bytes_downloaded', image['size'])
            comment = yield motor.Op(cursor.next_object)

    finally:
        IOLoop.instance().stop()


if __name__ == '__main__':
    run(*sys.argv[1:])
    IOLoop.instance().start()
