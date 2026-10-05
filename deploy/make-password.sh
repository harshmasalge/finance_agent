#!/bin/sh
# Prints a BASIC_AUTH_HASH line for .env.   Usage: sh deploy/make-password.sh 'your-password'
[ -z "$1" ] && { echo "usage: sh deploy/make-password.sh 'your-password'"; exit 1; }
HASH=$(docker run --rm caddy:2-alpine caddy hash-password --plaintext "$1")
echo "BASIC_AUTH_HASH='$HASH'"
