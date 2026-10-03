#!/usr/bin/env bash
# Provision one edge device identity for AWS IoT Core (Phase 1).
#
# Creates an X.509 certificate + key pair, attaches the IoT policy and the
# Thing, and writes everything to a directory OUTSIDE this repo. Nothing here
# is ever committed. Requires the AWS CLI with credentials that may call iot:*.
#
# Usage:
#   scripts/provision_device.sh <thing-name> [policy-name] [out-dir]
#
# Defaults: policy-name=urban-edge-device, out-dir=$HOME/.urban-edge/certs/<thing-name>
#
# The Thing and the policy are expected to exist already (CDK infra/iot_stack.py,
# not yet in this repo); pass --create-thing to create the Thing here for a
# manual test.
set -euo pipefail

THING_NAME="${1:?usage: $0 <thing-name> [policy-name] [out-dir] [--create-thing]}"
POLICY_NAME="${2:-urban-edge-device}"
OUT_DIR="${3:-$HOME/.urban-edge/certs/$THING_NAME}"
CREATE_THING=0
for arg in "$@"; do [[ "$arg" == "--create-thing" ]] && CREATE_THING=1; done

command -v aws >/dev/null || { echo "aws CLI not found" >&2; exit 1; }
command -v curl >/dev/null || { echo "curl not found" >&2; exit 1; }

# Refuse to write inside a git checkout: device keys never enter the repo.
probe="$OUT_DIR"
while [[ ! -d "$probe" && "$probe" != "/" ]]; do probe="$(dirname "$probe")"; done
if command -v git >/dev/null && git -C "$probe" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "refusing to write device keys inside a git repository: $OUT_DIR" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
chmod 700 "$OUT_DIR"

if [[ "$CREATE_THING" == "1" ]]; then
  aws iot create-thing --thing-name "$THING_NAME" >/dev/null
fi

CERT_ARN="$(aws iot create-keys-and-certificate \
  --set-as-active \
  --certificate-pem-outfile "$OUT_DIR/device.pem.crt" \
  --public-key-outfile "$OUT_DIR/public.pem.key" \
  --private-key-outfile "$OUT_DIR/private.pem.key" \
  --query certificateArn --output text)"
chmod 600 "$OUT_DIR"/*.key "$OUT_DIR"/*.crt

curl -fsSL https://www.amazontrust.com/repository/AmazonRootCA1.pem -o "$OUT_DIR/AmazonRootCA1.pem"

aws iot attach-policy --policy-name "$POLICY_NAME" --target "$CERT_ARN"
aws iot attach-thing-principal --thing-name "$THING_NAME" --principal "$CERT_ARN"

ENDPOINT="$(aws iot describe-endpoint --endpoint-type iot:Data-ATS --query endpointAddress --output text)"

cat <<MSG

Provisioned '$THING_NAME' (certificate: $CERT_ARN)
Files in $OUT_DIR (mode 600, outside the repo):
  device.pem.crt  private.pem.key  public.pem.key  AmazonRootCA1.pem

Configure the edge app with environment variables (never put paths' contents in configs/):
  export URBAN_EDGE_CLOUD_ENABLED=true
  export URBAN_EDGE_CLOUD_PUBLISHER=iot_core
  export URBAN_EDGE_CLOUD_THING_NAME='$THING_NAME'
  export URBAN_EDGE_CLOUD_IOT_ENDPOINT='$ENDPOINT'
  export URBAN_EDGE_CLOUD_CERT_PATH='$OUT_DIR/device.pem.crt'
  export URBAN_EDGE_CLOUD_KEY_PATH='$OUT_DIR/private.pem.key'
  export URBAN_EDGE_CLOUD_CA_PATH='$OUT_DIR/AmazonRootCA1.pem'
MSG
