#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0-only
exec bash "$(dirname -- "$0")/manage-module.sh" rollback "$@"
