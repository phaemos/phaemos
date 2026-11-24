//go:build !unix

package cli

import "os"

func ownedByMe(os.FileInfo) bool { return true }

const permissionBitsApply = false
