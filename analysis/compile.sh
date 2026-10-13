#!/bin/bash
# 사용법: ./compile.sh <name> [name ...]

cd "$(dirname "$0")" || exit 1

if [ $# -eq 0 ]; then
	echo "usage: ./compile.sh <name> [name ...]"
	echo "available:"
	for f in *.C; do echo "  ${f%.C}"; done
	exit 1
fi

status=0
for arg in "$@"; do
	fname=$(basename "${arg}" .C)
	if [ ! -f "${fname}.C" ]; then
		echo "no such file: ${fname}.C"
		status=1
		continue
	fi
	echo "Compiling ${fname}.C to ${fname}"
	if g++ -O2 -Wall $(root-config --cflags) "${fname}.C" -o "${fname}" $(root-config --glibs); then
		echo "Done!"
	else
		echo "FAILED: ${fname}"
		status=1
	fi
done
exit ${status}
