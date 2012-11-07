#!/usr/bin/env python
import time
import os
import logging
import subprocess


def resize_image(path, width, save_path):
    # by default, `-sample` is quicker when then picture is large
    _resize_tool = 'sample'
    if width < 1000:
        # only use `-resize` if it's a small picture
        _resize_tool = 'resize'
    cmd = (
        'convert %s -%s %d %s' %
        (path, _resize_tool, width, save_path)
    )
    cmd = 'MAGICK_THREAD_LIMIT=1 ' + cmd
    cmd = 'time ' + cmd
    print "CMD", repr(cmd)
    process = subprocess.Popen(
        cmd,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    out, err = process.communicate()
    if err:
        logging.warning("resizer: %s" % err)
    return save_path


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
    return resized


def _resize(path, zoom, extra=0):
    width = 256 * (2 ** zoom)

    start, ext = os.path.splitext(path)
    save_path = path.replace(
        ext,
        '-%s-%s%s' % (zoom, width, ext)
    )
    if os.path.isfile(save_path):
        return save_path
    return resize_image(path, width, save_path)
