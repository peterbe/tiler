#!/usr/bin/env python
import json
import time
import os
import logging
from PIL import Image
import redis
import settings

import subprocess


def main():
    r = redis.Redis(settings.REDIS_HOST, settings.REDIS_PORT)
    ps = r.pubsub()
    ps.subscribe(['resizer'])
    for message in ps.listen():
        data = message['data']
        if data == 1L:  # some sort of initialization
            continue
        try:
            data = json.loads(data)
        except ValueError:
            pass
        make_resizes(data['path'], data['ranges'])


def make_resizes(path, ranges):
    for zoom in ranges:
        #print path, zoom
        t0 = time.time()
        resized = _resize(path, zoom)
        t1 = time.time()
        print "Created", resized, "in", round(t1 - t0, 3), "seconds"


def make_resize(path, zoom):
    t0 = time.time()
    resized = _resize(path, zoom)
    t1 = time.time()
    print "Created", resized, "in", round(t1 - t0, 3), "seconds"


def _resize(path, zoom):
    return _resize_2(path, zoom)

    import time
    t0=time.time()
    r = _resize_1(path, zoom)
    t1=time.time()
    print "USING PIL", r, (t1-t0), "seconds"

    t0=time.time()
    r2 = _resize_2(path, zoom)
    t1=time.time()
    print "USING CONVERT", r2, (t1-t0), "seconds"

    return r


def _resize_1(path, zoom):
    width = 256 * (2 ** zoom)
    im = Image.open(path)
    x, y = [float(v) for v in im.size]
    xr, yr = [float(v) for v in (width, width)]
    r = min(xr / x, yr / y)
    w, h = int(round(x * r)), int(round(y * r))
    start, ext = os.path.splitext(path)
    save_path = path.replace(
        ext,
        '-%s-%s%s' % (zoom, w, ext)
    )
    im = im.resize((w, h), resample=Image.ANTIALIAS)
    im.save(save_path)
    del im
    return save_path


def _resize_2(path, zoom):
    width = 256 * (2 ** zoom)
    start, ext = os.path.splitext(path)
    save_path = path.replace(
        ext,
        '-%s-%s%s' % (zoom, width, ext)
    )
    cmd = 'convert %s -resize %d %s' % (path, width, save_path)
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out, err = process.communicate()
    #print "OUT"
    #print repr(out)
    #print "ERR"
    if err:
        logging.warning("resizer: %s" % err)
    #print repr(err)
    return save_path


def push_path(path):
    r = redis.Redis(settings.REDIS_HOST, settings.REDIS_PORT)
    data = {'path': path, 'ranges': range(1, 6)}
    r.publish(
        'resizer',
        json.dumps(data)
    )

if __name__ == '__main__':
    import sys
    args = sys.argv[1:]
    if args and os.path.isfile(args[0]):
        push_path(args[0])
    else:
        try:
            print "Starting resizer pump"
            main()
        except KeyboardInterrupt:
            pass
