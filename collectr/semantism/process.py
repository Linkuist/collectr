"""
    Index an URL into collectr
"""

# python
import logging
import os
import sys

sys.path.append('../')
sys.path.append('../../')

os.environ['DJANGO_SETTINGS_MODULE'] ='collectr.settings'

# django
from django.db.models import Q, F

# collectr
from source.models import (Author, Source, Origin, LinkSum, Filter,
                           Collection, Url, UrlViews, Tag)

# semantism
try:
    from semantism.embed import oembed
except Exception, exc:
    oembed = {}
from semantism.link import UrlParser
from semantism.exceptions import (DeleteLinkException, UnsupportedContentException,
                                  UrlExtractException)



logger = logging.getLogger('index_url')
logger.setLevel(logging.DEBUG)

sources = dict((source.name.lower(), source) for source in Source.objects.all())
default_collection = Collection.objects.get(name__iexact="all", user__isnull=True)


def init():
    logger = logging.getLogger('index_url')

    sources = dict((source.name.lower(), source) for source in Source.objects.all())
    default_collection = Collection.objects.get(name__iexact="all", user__isnull=True)

    return logger, sources, default_collection

def find_urls(content):
    if isinstance(content, basestring):
        if 'http://' or 'https://' in content:
            return [content]
    if not hasattr(content, "text"):
        return False
    if "http://" not in content.text:
        return False
    if not 'urls' in content.entities:
        return False
    urls = [d['url'] for d in content.entities['urls']]
    return urls

def index_url(link, user_id, link_at, author_name, source_name):
    user_id = int(user_id)
    filters = Filter.objects.filter(Q(user__pk=user_id)|Q(user__isnull=True))

    try:
        source = sources[source_name.lower()]
    except KeyError:
        logger.info("source %s unknown" % source_name)
        return -1
    try:
        author, created = Author.objects.get_or_create(name=author_name, source=source)
    except Exception, exc:
        print exc
        author = Author.objects.get(name=author_name)

    urls = find_urls(link)
    if not urls:
        #logger.info("status invalid and ignored")
        pass
        return
    for url in urls:
        url_parser = UrlParser(logger, url)

        try:
            url_parser.extract_url_content()
        except Exception, exc:
            logger.warning("Can't extract url_content from %s" % url)
            logger.exception(exc)
            return -1


        try:
            url_m = Url.objects.get(link=url_parser.url)
        except Url.DoesNotExist:
            uv = UrlViews.objects.create(count=0)
            try:
                summary = url_parser.summary or ""
                url_m = Url.objects.create(link=url_parser.url, views=uv,
                                           content=summary,
                                           image=url_parser.image)

            except Exception, exc:
                logger.error("Can't find or create an Url object")
                logger.exception(exc)
                return -1

        try:
            links_numb = LinkSum.objects.get(url__pk=url_m.pk, user__id=user_id)
            links_numb.recommanded += 1
            links_numb.save()
            links_numb.authors.add(author)
            logger.info("url already in database")
            continue

        except LinkSum.DoesNotExist:
            # link does not exist for now and will be created later
            pass

        tagstring = ""
        if url_parser.is_html_page():
            tags = url_parser.find_tags()

            for tag in tags:
                tag = tag.title()
                try:
                    tag_m, created = Tag.objects.get_or_create(name=tag)
                except Exception, e:
                    tag_m = Tag.objects.get(name=tag)
                url_m.tags.add(tag_m)

            tagstring = url_parser.tagstring or ""
            url_m.raw_tags = tagstring
            url_m.save()

        lsum = LinkSum(
            tags=tagstring, summary=url_parser.summary, url=url_m,
            title=url_parser.title, link=url_parser.url, collection_id=default_collection.pk,
            read=False, recommanded=1, source=source,
            user_id=user_id,
        )

        if isinstance(lsum.summary, basestring) and len(lsum.summary) == 0:
            lsum.summary = ""

        if url_parser.image and not url_m.image:
            url_m.image = url_parser.image
            url_m.save()

        try:
            filtr = url_parser.find_collection(lsum, filters)
            if filtr and filtr.xpath is not None and len(filtr.xpath.strip()) == 0:
                filtr.xpath = None
                filtr.save()
            if filtr and filtr.xpath is not None:
                lsum.summary = url_parser.extract_link_xpath(filtr.xpath)
                lsum.collection_id = filtr.to_collection_id
                logger.info("new collection : %d" % filtr.to_collection_id)

        except DeleteLinkException:
            logger.info("Link not saved, filtered")
            return
        try:
            if isinstance(lsum.summary, unicode) and len(lsum.summary) == 0:
                lsum.summary = ""
                lsum.tags = ""
            lsum.save()
            lsum.authors.add(author)
        except Exception, exc:
            logger.exception(exc)
        logger.info("Added new link for user %s" % user_id)
