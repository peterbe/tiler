Tiler
=====

App for allowing you to host some huge ass photos on the web.

This is basically the code for the site: [HUGEpic](http://hugepic.io) which I maintain.

Examples
--------

* [The Garden of Earthly Delights - 222Mb](http://hugepic.io/4ab2ef08b)
* [Lord of the Rings mosaic - 11.7Mb](http://hugepic.io/afacfabeb)

The code
--------

The code consists of the following major pieces:

* all server-side code is [Tornado](http://www.tornadoweb.org/)
* there are two databases:
    * [MongoDB](http://mongodb.org) main storage
    * [Redis](http://redis.io) primarily for caching
* connecting Tornado and MongoDB is [Motor](http://emptysquare.net/motor/)
* all message queue processes handled by [RQ](http://python-rq.org/)
* the client-side browsing is all thanks to [Leaflet](http://leafletjs.com/)
    * with the annotation drawing thanks to [Leaflet.Draw](https://github.com/jacobtoye/Leaflet.draw)
* Amazon S3 and CloudFront keeps all the images except for temporary copies
* vipsthumbnail from [VIPS](http://www.vips.ecs.soton.ac.uk/index.php?title=VIPS)

More has been [written about the technical here](http://www.peterbe.com/plog/introducing-hugepic.io).
