# Zone Gore Overhaul - zgo_native.dll (mingw-w64, x86_64)
#
#   dev/run.sh make -C native              build ../bin/zgo_native.dll
#   dev/run.sh make -C native test         + build and run the tests under Wine
#   dev/run.sh make -C native check-deps   list the DLL's imports (must be system DLLs only)
#   dev/run.sh make -C native clean
#
# Statically linked runtime: the DLL imports only KERNEL32 and the system C
# runtime (msvcrt), never libgcc_s, libstdc++ or libwinpthread DLLs.

CC      = x86_64-w64-mingw32-gcc
OBJDUMP = x86_64-w64-mingw32-objdump
VERSION = 1.0.0

BUILD   = build
DLL     = ../bin/zgo_native.dll
TESTEXE = $(BUILD)/zgo_native_test.exe

CFLAGS  = -std=c11 -O2 -g0 -Wall -Wextra -Wno-unused-parameter -Wno-cast-function-type \
          -march=x86-64 -mtune=generic -fno-strict-aliasing -fno-asynchronous-unwind-tables \
          -Iinclude -Isrc -DZGO_NATIVE_VERSION=\"$(VERSION)\"
LDDLL   = -shared -static -static-libgcc -s -Wl,--no-insert-timestamp -Wl,--enable-stdcall-fixup
# the test exe must stay clear of 0x140000000, where it maps the game exe
LDTEST  = -static -static-libgcc -Wl,--image-base,0x10000000 -Wl,--disable-dynamicbase

CORE    = src/zgo_pe.c src/zgo_finder.c src/zgo_bones.c
SRC     = $(CORE) src/zgo_hook.c src/zgo_dll.c
HDR     = include/zgo_native.h src/zgo_pe.h src/zgo_finder.h src/zgo_bones.h src/zgo_hook.h

all: $(DLL)

$(DLL): $(SRC) $(HDR) Makefile
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -DZGO_BUILDING_DLL $(SRC) -o $@ $(LDDLL)

$(TESTEXE): tests/zgo_native_test.c $(CORE) src/zgo_hook.c $(HDR) Makefile
	@mkdir -p $(BUILD)
	$(CC) $(CFLAGS) tests/zgo_native_test.c $(CORE) src/zgo_hook.c -o $@ $(LDTEST)

test: $(DLL) $(TESTEXE)
	tests/run.sh

check-deps: $(DLL)
	@$(OBJDUMP) -p $(DLL) | grep "DLL Name" | sort -u

clean:
	rm -rf $(BUILD)

.PHONY: all test check-deps clean
