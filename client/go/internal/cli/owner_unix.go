//go:build unix

package cli

import (
	"os"
	"syscall"
)

// ownedByMe reports whether the file belongs to the user running the tool. It is true where the owner
// cannot be told.
func ownedByMe(info os.FileInfo) bool {
	stat, ok := info.Sys().(*syscall.Stat_t)
	if !ok {
		return true
	}
	return int(stat.Uid) == os.Getuid()
}

const permissionBitsApply = true
