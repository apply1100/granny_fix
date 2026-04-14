#!/usr/bin/env bash

set -uo pipefail

# Oracle A1 auto-retry launcher for OCI Cloud Shell / OCI CLI.
#
# Easiest usage in OCI Cloud Shell:
#   COMPARTMENT_ID='ocid1.tenancy...' \
#   SUBNET_ID='ocid1.subnet...' \
#   MAX_ATTEMPTS=60 \
#   SLEEP_SECONDS=120 \
#   bash oracle_a1_retry_create.sh
#
# Or, if you prefer, you can still edit the defaults below and then run:
#   bash oracle_a1_retry_create.sh
#
# This script is intentionally narrow:
# - It assumes you already have a PUBLIC subnet OCID.
# - It rotates through the region's availability domains.
# - It retries only when the error looks like an A1 capacity shortage.
# - It stops immediately on configuration or permission errors.
#
# Tip:
# - Run this in OCI Cloud Shell from the same region where you want the server.
# - If you do not have an SSH key yet in Cloud Shell, you can make one with:
#     ssh-keygen -t ed25519 -f ~/.ssh/oracle_a1 -N ""

COMPARTMENT_ID="${COMPARTMENT_ID:-ocid1.compartment.oc1..REPLACE_ME}"
SUBNET_ID="${SUBNET_ID:-ocid1.subnet.oc1..REPLACE_ME}"

# Choose ONE of the two SSH key options below.
SSH_PUBLIC_KEY_VALUE="${SSH_PUBLIC_KEY_VALUE:-}"
SSH_PUBLIC_KEY_PATH="${SSH_PUBLIC_KEY_PATH:-$HOME/.ssh/oracle_a1.pub}"

INSTANCE_NAME_PREFIX="${INSTANCE_NAME_PREFIX:-granny-a1}"
SHAPE="${SHAPE:-VM.Standard.A1.Flex}"
OCPU_COUNT="${OCPU_COUNT:-2}"
MEMORY_IN_GBS="${MEMORY_IN_GBS:-24}"

# Leave IMAGE_ID blank to auto-pick the newest Ubuntu 24.04 image for A1.
IMAGE_ID="${IMAGE_ID:-}"
OPERATING_SYSTEM="${OPERATING_SYSTEM:-Canonical Ubuntu}"
OPERATING_SYSTEM_VERSION="${OPERATING_SYSTEM_VERSION:-24.04}"

# Leave AD_NAMES empty to auto-discover all ADs in the current region.
AD_NAMES=()

MAX_ATTEMPTS="${MAX_ATTEMPTS:-30}"
SLEEP_SECONDS="${SLEEP_SECONDS:-600}"
BOOT_WAIT_SECONDS="${BOOT_WAIT_SECONDS:-900}"
POLL_INTERVAL_SECONDS="${POLL_INTERVAL_SECONDS:-15}"

# Optional: set this if you want to use a non-default OCI CLI profile.
OCI_PROFILE="${OCI_PROFILE:-}"

OCI_CMD=(oci)
if [[ -n "$OCI_PROFILE" ]]; then
  OCI_CMD+=(--profile "$OCI_PROFILE")
fi

TEMP_SSH_KEY_FILE=""
RUN_STAMP="$(date +%Y%m%d-%H%M%S)"

log() {
  printf '[%s] %s\n' "$(date +%Y-%m-%d' '%H:%M:%S)" "$*"
}

die() {
  printf '[%s] ERROR: %s\n' "$(date +%Y-%m-%d' '%H:%M:%S)" "$*" >&2
  exit 1
}

cleanup() {
  if [[ -n "$TEMP_SSH_KEY_FILE" && -f "$TEMP_SSH_KEY_FILE" ]]; then
    rm -f "$TEMP_SSH_KEY_FILE"
  fi
}

trap cleanup EXIT

run_oci() {
  "${OCI_CMD[@]}" "$@"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    die "Required command not found: $1"
  fi
}

require_value() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" || "$value" == *"REPLACE_ME"* ]]; then
    die "Please set $name before running this script."
  fi
}

prepare_ssh_key_file() {
  if [[ -n "${SSH_PUBLIC_KEY_VALUE:-}" ]]; then
    TEMP_SSH_KEY_FILE="$(mktemp)"
    printf '%s\n' "$SSH_PUBLIC_KEY_VALUE" >"$TEMP_SSH_KEY_FILE"
    SSH_PUBLIC_KEY_PATH="$TEMP_SSH_KEY_FILE"
  fi

  if [[ -z "${SSH_PUBLIC_KEY_PATH:-}" ]]; then
    die "Set SSH_PUBLIC_KEY_VALUE or SSH_PUBLIC_KEY_PATH."
  fi

  if [[ ! -f "$SSH_PUBLIC_KEY_PATH" ]]; then
    die "SSH public key file not found: $SSH_PUBLIC_KEY_PATH"
  fi
}

discover_ads() {
  if (( ${#AD_NAMES[@]} > 0 )); then
    return
  fi

  log "Discovering availability domains..."
  local ads_json
  ads_json="$(run_oci iam availability-domain list --compartment-id "$COMPARTMENT_ID")" \
    || die "Failed to list availability domains."

  mapfile -t AD_NAMES < <(
    printf '%s' "$ads_json" | python3 -c \
      'import json,sys; data=json.load(sys.stdin)["data"]; print("\n".join(item["name"] for item in data))'
  )

  if (( ${#AD_NAMES[@]} == 0 )); then
    die "No availability domains were returned."
  fi
}

resolve_image_id() {
  if [[ -n "$IMAGE_ID" ]]; then
    return
  fi

  log "Resolving latest compatible Ubuntu image for ${SHAPE}..."
  local images_json
  images_json="$(
    run_oci compute image list \
      --compartment-id "$COMPARTMENT_ID" \
      --operating-system "$OPERATING_SYSTEM" \
      --operating-system-version "$OPERATING_SYSTEM_VERSION" \
      --shape "$SHAPE" \
      --sort-by TIMECREATED \
      --sort-order DESC \
      --all
  )" || die "Failed to list images."

  IMAGE_ID="$(
    printf '%s' "$images_json" | python3 -c \
      'import json,sys; data=json.load(sys.stdin)["data"]; print(data[0]["id"] if data else "")'
  )"

  if [[ -z "$IMAGE_ID" ]]; then
    die "Could not find a compatible Ubuntu image automatically. Set IMAGE_ID manually."
  fi

  log "Using image: $IMAGE_ID"
}

validate_subnet() {
  log "Checking whether the subnet allows public IPs..."
  local prohibit_public_ip
  prohibit_public_ip="$(run_oci network subnet get --subnet-id "$SUBNET_ID" --query 'data."prohibit-public-ip-on-vnic"' --raw-output)" \
    || die "Failed to inspect subnet. Check SUBNET_ID."

  if [[ "$prohibit_public_ip" == "true" ]]; then
    die "SUBNET_ID points to a private subnet. Use a PUBLIC subnet OCID instead."
  fi
}

is_capacity_error() {
  local text="$1"
  local lower
  lower="$(printf '%s' "$text" | tr '[:upper:]' '[:lower:]')"
  [[ "$lower" == *"out of capacity"* || "$lower" == *"outofhostcapacity"* || "$lower" == *"host capacity"* ]]
}

fetch_public_ip() {
  local instance_id="$1"
  run_oci compute instance list-vnics \
    --instance-id "$instance_id" \
    --all \
    --query 'data[0]."public-ip"' \
    --raw-output 2>/dev/null || true
}

wait_until_running() {
  local instance_id="$1"
  local deadline=$((SECONDS + BOOT_WAIT_SECONDS))

  while (( SECONDS < deadline )); do
    local state
    state="$(run_oci compute instance get --instance-id "$instance_id" --query 'data."lifecycle-state"' --raw-output 2>/dev/null || true)"

    case "$state" in
      RUNNING)
        local public_ip
        public_ip="$(fetch_public_ip "$instance_id")"
        log "Instance is RUNNING."
        log "Instance OCID: $instance_id"
        if [[ -n "$public_ip" && "$public_ip" != "null" ]]; then
          log "Public IP: $public_ip"
        else
          log "Public IP: not available yet; check the OCI console if needed."
        fi
        return 0
        ;;
      PROVISIONING|STARTING|STOPPING|"")
        log "Current lifecycle state: ${state:-UNKNOWN}. Waiting..."
        sleep "$POLL_INTERVAL_SECONDS"
        ;;
      *)
        die "Instance reached unexpected state: $state"
        ;;
    esac
  done

  die "The instance was created, but it did not reach RUNNING within ${BOOT_WAIT_SECONDS}s."
}

launch_once() {
  local availability_domain="$1"
  local instance_name="$2"

  run_oci compute instance launch \
    --availability-domain "$availability_domain" \
    --compartment-id "$COMPARTMENT_ID" \
    --display-name "$instance_name" \
    --shape "$SHAPE" \
    --shape-config "{\"ocpus\": ${OCPU_COUNT}, \"memoryInGBs\": ${MEMORY_IN_GBS}}" \
    --image-id "$IMAGE_ID" \
    --subnet-id "$SUBNET_ID" \
    --assign-public-ip true \
    --ssh-authorized-keys-file "$SSH_PUBLIC_KEY_PATH" \
    --query 'data.id' \
    --raw-output
}

main() {
  require_command oci
  require_command python3
  require_command mktemp

  require_value "COMPARTMENT_ID" "$COMPARTMENT_ID"
  require_value "SUBNET_ID" "$SUBNET_ID"

  prepare_ssh_key_file
  discover_ads
  resolve_image_id
  validate_subnet

  log "Retry loop will rotate through: ${AD_NAMES[*]}"
  log "Shape config: ${SHAPE} / ${OCPU_COUNT} OCPU / ${MEMORY_IN_GBS} GB"

  local attempt
  for (( attempt=1; attempt<=MAX_ATTEMPTS; attempt++ )); do
    local ad_index=$(( (attempt - 1) % ${#AD_NAMES[@]} ))
    local availability_domain="${AD_NAMES[$ad_index]}"
    local instance_name="${INSTANCE_NAME_PREFIX}-${RUN_STAMP}-${attempt}"

    log "Attempt ${attempt}/${MAX_ATTEMPTS}: launching ${instance_name} in ${availability_domain}"

    local launch_output
    launch_output="$(launch_once "$availability_domain" "$instance_name" 2>&1)"
    local status=$?

    if (( status == 0 )); then
      local instance_id="$launch_output"
      log "Launch request accepted. Instance OCID: $instance_id"
      wait_until_running "$instance_id"
      return 0
    fi

    if is_capacity_error "$launch_output"; then
      log "Capacity shortage in ${availability_domain}. Will retry."
      if (( attempt < MAX_ATTEMPTS )); then
        log "Sleeping ${SLEEP_SECONDS}s before the next attempt..."
        sleep "$SLEEP_SECONDS"
      fi
      continue
    fi

    printf '\n%s\n' "$launch_output" >&2
    die "Stopped because the error did not look like a capacity issue."
  done

  die "No capacity found after ${MAX_ATTEMPTS} attempts."
}

main "$@"
