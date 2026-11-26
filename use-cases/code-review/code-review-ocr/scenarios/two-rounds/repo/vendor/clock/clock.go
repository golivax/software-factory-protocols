package clock

import "time"

// Now is time.Now, replaceable in tests.
var Now = time.Now
