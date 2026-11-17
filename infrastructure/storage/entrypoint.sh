#!/bin/sh
# SeaweedFS (S3-compatible) for development. Writes the S3 identity file from environment
# variables at start-up so no credentials are committed, then starts a single-node server.
set -eu

: "${STORAGE_ACCESS_KEY_ID:?STORAGE_ACCESS_KEY_ID is required}"
: "${STORAGE_SECRET_ACCESS_KEY:?STORAGE_SECRET_ACCESS_KEY is required}"

umask 077
cat > /tmp/s3.json <<EOF
{"identities":[{"name":"oscc","credentials":[{"accessKey":"${STORAGE_ACCESS_KEY_ID}","secretKey":"${STORAGE_SECRET_ACCESS_KEY}"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
EOF

exec weed server \
  -dir=/data \
  -ip=storage \
  -ip.bind=0.0.0.0 \
  -master.volumeSizeLimitMB=256 \
  -s3 \
  -s3.port=8333 \
  -s3.config=/tmp/s3.json
