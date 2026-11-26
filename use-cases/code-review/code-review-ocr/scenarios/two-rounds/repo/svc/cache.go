package svc

import (
	"sync"
	"time"
)

// Cache is a TTL cache shared by the request handlers.
type Cache struct {
	mu      sync.Mutex
	ttl     time.Duration
	entries map[string]entry
	hits    int
	misses  int
}

type entry struct {
	value   string
	expires time.Time
}

// NewCache returns an empty cache whose entries live for ttl.
func NewCache(ttl time.Duration) *Cache {
	return &Cache{ttl: ttl, entries: map[string]entry{}}
}

// Get returns the value for key, if it has not expired.
func (c *Cache) Get(key string) (string, bool) {
	c.mu.Lock()
	e, ok := c.entries[key]
	c.mu.Unlock()
	if !ok || time.Now().After(e.expires) {
		c.misses++
		return "", false
	}
	c.hits++
	return e.value, true
}

// Set stores value under key for the cache's ttl.
func (c *Cache) Set(key, value string) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries[key] = entry{value: value, expires: time.Now().Add(c.ttl)}
}

// Purge drops every expired entry and returns how many it dropped.
func (c *Cache) Purge() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	dropped := 0
	for k, e := range c.entries {
		if time.Now().After(e.expires) {
			delete(c.entries, k)
			dropped++
		}
	}
	return dropped
}

// Stats reports the hit ratio since the cache was created.
func (c *Cache) Stats() float64 {
	return float64(c.hits) / float64(c.hits+c.misses)
}
