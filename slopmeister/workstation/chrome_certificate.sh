#!/usr/bin/env bash
# Operator-run setup. Agents never run it, because it reads a private key through real op.
# Puts a client certificate from 1Password into Chrome's Linux store and lets Chrome choose it
# without its prompt, which no agent can answer.
set -euo pipefail

if [ "$#" -ne 3 ]; then
    echo "usage: task browser:certificate -- <vault> <document item> <url pattern>" >&2
    exit 2
fi
vault=$1 item=$2 pattern=$3
if [ "${SLOPMEISTER_SECRET_BROKER:-}" = 1 ]; then
    echo "browser:certificate: run this in your own terminal, not in an agent session" >&2
    exit 2
fi
if [ "$(uname -s)" != Linux ]; then
    echo "browser:certificate: on a Mac, import the certificate into Keychain Access" >&2
    exit 2
fi

command -v pk12util >/dev/null || sudo apt-get install -y libnss3-tools

private=$(mktemp -d)
trap 'rm -rf "$private"' EXIT
op document get "$item" --vault "$vault" --out-file "$private/client.p12"

store="$HOME/.pki/nssdb"
if [ ! -e "$store/cert9.db" ]; then
    mkdir -p "$store"
    chmod 700 "$store"
    certutil -d "sql:$store" -N --empty-password
fi
pk12util -d "sql:$store" -i "$private/client.p12" -w <(op read -n "op://$vault/$item/password")

python3 -c '
import json, sys
rule = json.dumps({"pattern": sys.argv[1], "filter": {}})
print(json.dumps({"AutoSelectCertificateForUrls": [rule]}))
' "$pattern" | sudo install -D -m 644 /dev/stdin \
    /etc/opt/chrome/policies/managed/slopmeister-client-certificate.json

echo "Certificate installed. Restart Chrome once so it loads the store and the rule."
