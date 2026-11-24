#!/bin/sh
# runs every host test exactly as its own header says.  each test_*.c file carries its build lines in the
# header comment (the lines that start with " *   cc "), one plain and one with the sanitizers.  this script
# runs each of them from this folder, so it cannot drift from the headers.  exit status is non-zero when any
# build or test fails.
cd "$(dirname "$0")" || exit 1
export TMPDIR="${TMPDIR:-/tmp}"
status=0
count=0
for f in test_*.c; do
    grep -E '^ \*   cc ' "$f" | sed 's/^ \*   //' | while IFS= read -r line; do
        out=$(sh -c "$line" 2>&1)
        rc=$?
        if [ $rc -eq 0 ]; then
            printf 'PASS  %s: %s\n' "$f" "$(printf '%s\n' "$out" | tail -1)"
        else
            printf 'FAIL  %s\n      %s\n%s\n' "$f" "$line" "$out" | head -20
            exit 1
        fi
    done || status=1
    count=$((count + 1))
done
[ $count -eq 0 ] && { echo "no test files found"; exit 1; }
exit $status
