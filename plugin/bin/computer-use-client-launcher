#!/bin/sh

set -eu

codex_home="${CODEX_HOME:-${HOME}/.codex}"
client="${codex_home}/computer-use/Codex Computer Use.app/Contents/SharedSupport/SkyComputerUseClient.app/Contents/MacOS/SkyComputerUseClient"

if [ ! -x "${client}" ]; then
  echo "Codex Computer Use client was not found at ${client}." >&2
  exit 1
fi

exec "${client}" "$@"
