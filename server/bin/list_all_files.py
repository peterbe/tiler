#!/usr/bin/env python

import os, sys
sys.path.insert(
    0,
    os.path.join(os.path.dirname(__file__), '..')
)

from utils import find_all_tiles


def run(fileids):
    static_path = os.path.join(os.path.abspath(os.curdir), 'static')
    for fileid in fileids:
        for each in find_all_tiles(fileid, static_path):
            print each
            assert os.path.isfile(each), each


if __name__ == '__main__':
    import sys
    run(*sys.argv[1:])
