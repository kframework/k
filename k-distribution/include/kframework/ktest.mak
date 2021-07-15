# path to the current makefile
MAKEFILE_PATH := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
# path to the kompile binary of this distribuition
KOMPILE=$(abspath $(MAKEFILE_PATH)/../../bin/kompile)
# ditto for krun
KRUN=$(abspath $(MAKEFILE_PATH)/../../bin/krun)
# and kdep
KDEP=$(abspath $(MAKEFILE_PATH)/../../bin/kdep)
# and kprove
KPROVE=$(abspath $(MAKEFILE_PATH)/../../bin/kprove)
KPROVEX=$(abspath $(MAKEFILE_PATH)/../../bin/kprovex)
# and kbmc
KBMC=$(abspath $(MAKEFILE_PATH)/../../bin/kbmc)
# and kast
KAST=$(abspath $(MAKEFILE_PATH)/../../bin/kast)
# and keq
KEQ=$(abspath $(MAKEFILE_PATH)/../../bin/keq)
# and kserver
KSERVER=$(abspath $(MAKEFILE_PATH)/../../bin/kserver)
# and ksearch
KSEARCH:=$(KRUN) --search-all
# and kast
KAST=$(abspath $(MAKEFILE_PATH)/../../bin/kast)
# and kprint
KPRINT=$(abspath $(MAKEFILE_PATH)/../../bin/kprint)
# and krun-legacy
KRUN_LEGACY=$(abspath $(MAKEFILE_PATH)/../../bin/krun-legacy)
# path relative to current definition of test programs
TESTDIR?=tests
# path to put -kompiled directory in
DEFDIR?=.
# path to kompile output directory
KOMPILED_DIR=$(DEFDIR)/$(notdir $(DEF))-kompiled
# path relative to current definition of output/input files
RESULTDIR?=$(TESTDIR)
# all tests in test directory with matching file extension
TESTS?=$(wildcard $(TESTDIR)/krun.nopgm) $(wildcard $(TESTDIR)/*.$(EXT))
PROOF_TESTS?=$(wildcard $(TESTDIR)/*-spec.k) $(wildcard $(TESTDIR)/*-spec.md)
BMC_TESTS?=$(wildcard $(TESTDIR)/*-spec-bmc.k) $(wildcard $(TESTDIR)/*-spec-bmc.md)
SEARCH_TESTS?=$(wildcard $(TESTDIR)/*.$(EXT).search)
STRAT_TESTS?=$(wildcard $(TESTDIR)/*.strat)
KAST_TESTS?=$(wildcard $(TESTDIR)/*.kast)
KAST_BISON_TESTS?=$(wildcard $(TESTDIR)/*.kast-bison)
# default KOMPILE_BACKEND
KOMPILE_BACKEND?=llvm
# check if .k file exists, if not, check if .md file exists
# if not, default to .k to give error message
SOURCE_EXT?=$(or $(and $(wildcard $(DEF).k), k), $(or $(and $(wildcard $(DEF).md), md), k))
KOMPILE_FLAGS+=--no-exc-wrap
KPROVE_FLAGS+=--no-exc-wrap
KRUN_FLAGS+=--no-exc-wrap

KRUN_OR_LEGACY=$(KRUN)
KPROVE_OR_X=$(KPROVE)

CHECK?=| diff -
REMOVE_PATHS=| sed 's!'`pwd`'/\(\./\)\{0,2\}!!g'
CONSIDER_ERRORS=2>&1
# null by default, add CONSIDER_PROVER_ERRORS=2>&1 to the local Makefile to test kprove output
#CONSIDER_PROVER_ERRORS=

.PHONY: kompile krun all clean update-results proofs bmc

# run all tests
all: kompile krun proofs bmc searches strat kast kast-bison

# run only kompile
kompile: $(KOMPILED_DIR)/timestamp

$(KOMPILED_DIR)/timestamp: $(DEF).$(SOURCE_EXT)
	$(KOMPILE) $(KOMPILE_FLAGS) --backend $(KOMPILE_BACKEND) $(DEBUG) $< -d $(DEFDIR)

krun: $(TESTS)

proofs: $(PROOF_TESTS)

bmc: $(BMC_TESTS)

searches: $(SEARCH_TESTS)

strat: $(STRAT_TESTS)

kast: $(KAST_TESTS)

kast-bison: $(KAST_BISON_TESTS)

# run all tests and regenerate output files
update-results: all
update-results: CHECK=>

# run a single test. older versions of make run pattern rules in order, so
# if some programs should be run with different options their rule should be
# specified in the makefile prior to including ktest.mak.
%.$(EXT): kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	cat $@.in 2>/dev/null | $(KRUN_OR_LEGACY) $@ $(KRUN_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $@.out
else
	cat $(RESULTDIR)/$(notdir $@).in 2>/dev/null | $(KRUN_OR_LEGACY) $@ $(KRUN_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

krun.nopgm: kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	cat $@.in 2>/dev/null | $(KRUN_OR_LEGACY) $(KRUN_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $@.out
else
	cat $(RESULTDIR)/$(notdir $@).in 2>/dev/null | $(KRUN_OR_LEGACY) $(KRUN_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

%-spec.k %-spec.md: kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	$(KPROVE_OR_X) $@ $(KPROVE_FLAGS) $(DEBUG) -d $(DEFDIR) $(CONSIDER_PROVER_ERRORS) $(REMOVE_PATHS) $(CHECK) $@.out
else
	$(KPROVE_OR_X) $@ $(KPROVE_FLAGS) $(DEBUG) -d $(DEFDIR) $(CONSIDER_PROVER_ERRORS) $(REMOVE_PATHS) $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

%-broken-spec.k %-broken-spec.md: kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	$(KPROVE_OR_X) $@ $(KPROVE_FLAGS) $(DEBUG) -d $(DEFDIR) $(CONSIDER_ERRORS) $(REMOVE_PATHS) $(CHECK) $@.out
else
	$(KPROVE_OR_X) $@ $(KPROVE_FLAGS) $(DEBUG) -d $(DEFDIR) $(CONSIDER_ERRORS) $(REMOVE_PATHS) $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

%-spec-bmc.k %-spec-bmc.md: kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	$(KBMC) --raw-spec $@ $(KBMC_FLAGS) $(DEBUG) -d $(DEFDIR) --depth 20 $(CHECK) $@.out
else
	$(KBMC) --raw-spec $@ $(KBMC_FLAGS) $(DEBUG) -d $(DEFDIR) --depth 20 $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

%.search: kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	$(KSEARCH) $@ $(KSEARCH_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $@.out
else
	$(KSEARCH) $@ $(KSEARCH_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

%.strat: kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	$(KRUN_OR_LEGACY) $@.input $(KRUN_FLAGS) $(DEBUG) -d $(DEFDIR) -cSTRATEGY="$(shell cat $@)" $(CHECK) $@.out
else
	$(KRUN_OR_LEGACY) $@.input $(KRUN_FLAGS) $(DEBUG) -d $(DEFDIR) -cSTRATEGY="$(shell cat $@)" $(CHECK) $(RESULT_DIR)/$(notdir $@).out
endif

%.kast: kompile
ifeq ($(TESTDIR),$(RESULTDIR))
	$(KAST) $@ $(KAST_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $@.out
else
	$(KAST) $@ $(KAST_FLAGS) $(DEBUG) -d $(DEFDIR) $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

%.kast-bison: kompile
	$(KAST) $(KAST_FLAGS) $(DEBUG) -d $(DEFDIR) bison_parser
ifeq ($(TESTDIR),$(RESULTDIR))
	./bison_parser $@ $(CHECK) $@.out
else
	./bison_parser $@ $(CHECK) $(RESULTDIR)/$(notdir $@).out
endif

clean:
	rm -rf $(KOMPILED_DIR) .depend-tmp .depend .kompile-* .krun-* .kprove-* .kbmc-* kore-exec.tar.gz

.depend:
	@$(KDEP) $(DEF).$(SOURCE_EXT) > .depend-tmp
	@mv .depend-tmp .depend

-include .depend
