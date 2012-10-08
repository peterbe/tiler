#!/usr/bin/env python
import os
import motor
import shutil
from tornado import gen
from tornado.ioloop import IOLoop

HERE = os.path.dirname(__file__)

@gen.engine
def run(*fileids):
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
        yield motor.Op(
            db.images.remove,
            {'_id': document['_id']}
        )
    IOLoop.instance().stop()


if __name__ == '__main__':
    import sys
    if not sys.argv[1:]:
        print "%s fileid1 fileid2 fileidN" % __file__
        exit()
    run(*sys.argv[1:])
    IOLoop.instance().start()
