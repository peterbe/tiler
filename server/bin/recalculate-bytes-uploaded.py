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
    connection = motor.MotorConnection().open_sync()
    db = connection.tiler


    try:
        cursor = (
            db.images.find()
        )
        image = yield motor.Op(cursor.next_object)
        while image:
            _redis.incr('bytes_downloaded', image['size'])
            image = yield motor.Op(cursor.next_object)

    finally:
        IOLoop.instance().stop()


if __name__ == '__main__':
    run(*sys.argv[1:])
    IOLoop.instance().start()
