# SPDX-License-Identifier: GPL-2.0-only
override KREL := 7.3.3-300.fc45.x86_64
KDIR ?= /usr/lib/modules/$(KREL)/build
MODULE_DIR := $(CURDIR)/module

.PHONY: all clean
all:
	@test -s "$(KDIR)/Module.symvers" || { echo "Missing matching kernel-devel Module.symvers" >&2; exit 1; }
	@test "$$(cat "$(KDIR)/include/config/kernel.release")" = "$(KREL)" || { echo "Expected kernel-devel $(KREL)" >&2; exit 1; }
	$(MAKE) -C "$(KDIR)" M="$(MODULE_DIR)" modules

clean:
	$(MAKE) -C "$(KDIR)" M="$(MODULE_DIR)" clean
