//go:build !unix

package oltquery

import "errors"

// Fails closed: without a cross-process lock and a directory sync the at-most-once guarantee cannot be kept, and the Edge is only supported on unix hosts.
func lockFile(string) (func(), error) {
	return nil, errors.New("oltquery: file locking is not supported on this platform")
}

func syncDir(string) error {
	return errors.New("oltquery: directory sync is not supported on this platform")
}
