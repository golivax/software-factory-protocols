"""Nightly maintenance jobs."""
import logging

log = logging.getLogger(__name__)


def purge(cache):
    """Drop the cache's expired entries."""
    dropped = cache.purge()
    log.info("purged %d entries", dropped)
    return dropped
