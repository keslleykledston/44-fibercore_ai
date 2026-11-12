//go:build !unix

package oltsecrets

import "errors"

// The Edge is only supported on unix hosts: without ownership checks the key file cannot be trusted, so it fails closed.
func checkPrivateDir(string) error { return errors.New("oltsecrets: not supported on this platform") }
