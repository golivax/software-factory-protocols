package svc

import (
	"net/http"
	"time"
)

var shared = NewCache(5 * time.Minute)

// CacheHandler serves GET /cache?key=… from the shared cache.
func CacheHandler(w http.ResponseWriter, r *http.Request) {
	key := r.URL.Query().Get("key")
	value, ok := shared.Get(key)
	if !ok {
		http.NotFound(w, r)
		return
	}
	w.Write([]byte(value))
}
