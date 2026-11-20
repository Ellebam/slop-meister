#!/usr/bin/env bash
# Operator-run setup. Agents never run it, because it reads a private key through real op.
# Lets Chrome choose a client certificate without its prompt, which no agent can answer. On Linux it
# puts the certificate from 1Password into Chrome's store, on a Mac Chrome reads it from the keychain.
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
if [ "$(uname -s)" = Darwin ]; then
    # Chrome on a Mac takes this policy only as a managed setting, so a defaults write is ignored.
    # A Mac mktemp ignores TMPDIR without a template.
    profile="$(mktemp -d "${TMPDIR:-/tmp}/slopmeister-certificate.XXXXXX")/slopmeister-client-certificate.mobileconfig"
    python3 -c '
import json, plistlib, sys, uuid
rule = json.dumps({"pattern": sys.argv[1], "filter": {}})
name = "slopmeister.chrome.client-certificate"
chrome = {
    "PayloadType": "com.google.Chrome",
    "PayloadIdentifier": name + ".chrome",
    "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_DNS, name + ".chrome")).upper(),
    "PayloadVersion": 1,
    "AutoSelectCertificateForUrls": [rule],
}
sys.stdout.buffer.write(plistlib.dumps({
    "PayloadType": "Configuration",
    "PayloadDisplayName": "Chrome client certificate selection",
    "PayloadIdentifier": name,
    "PayloadUUID": str(uuid.uuid5(uuid.NAMESPACE_DNS, name)).upper(),
    "PayloadScope": "User",
    "PayloadVersion": 1,
    "PayloadContent": [chrome],
}))
' "$pattern" > "$profile"
    open "$profile"
    echo "Install the profile in System Settings, General, Device Management. The certificate must be in your login keychain, else import it with Keychain Access. Then restart Chrome."
    exit 0
fi
if [ "$(uname -s)" != Linux ]; then
    echo "browser:certificate: runs on Linux and macOS only" >&2
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
