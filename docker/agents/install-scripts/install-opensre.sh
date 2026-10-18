#!/usr/bin/env bash
set -euo pipefail

VERSION="${AGENT_VERSION:-v0.1.2026.9.2}"
INSTALL_DIR="${OPENSRE_INSTALL_DIR:-/opt/agent-tools}"

echo "[$(date -Iseconds)] Installing OpenSRE CLI (version: $VERSION)..."
curl -fsSL https://install.opensre.com -o /tmp/install-opensre.sh
# Release archives preserve their build UID/GID.  SREGym's runtime drops
# CAP_CHOWN, so extraction must retain the current container owner instead.
sed -i 's/tar -xzf /tar --no-same-owner -xzf /' /tmp/install-opensre.sh
OPENSRE_AUTO_LAUNCH=0 bash /tmp/install-opensre.sh --version "$VERSION" --install-dir "$INSTALL_DIR"

# The installer may place the executable either directly in INSTALL_DIR or in
# its bin directory. ContainerRunner puts /opt/agent-tools/bin on PATH.
mkdir -p "$INSTALL_DIR/bin"
if [ -x "$INSTALL_DIR/opensre" ]; then
  ln -sf "$INSTALL_DIR/opensre" "$INSTALL_DIR/bin/opensre"
fi

"$INSTALL_DIR/bin/opensre" investigate --help >/dev/null
echo "[$(date -Iseconds)] OpenSRE CLI installed: $("$INSTALL_DIR/bin/opensre" version)"
