# Build the nuBoard FPGA images.
#
#   make -C fpga              # route every project
#   make -C fpga heartbeat    # one project
#   make -C fpga test         # Verilator behavioural tests (runs on the host)
#   make -C fpga shell        # interactive shell with the Efinity tools
#   make -C fpga efx CMD="efx_run --help"
#   make -C fpga -j2 hyperram-sweep   # template at every HyperRAM clock/phase
#
# Efinity runs natively on Linux when EFINITY_HOME points at an install, and
# otherwise in the Apple Container image built by
# tools/efinity/setup-container.sh.  Outputs land in build/fpga/<project>/.

REPO_ROOT := $(abspath $(CURDIR)/..)
BUILD     := $(REPO_ROOT)/build/fpga
EFX_RUN   := $(REPO_ROOT)/tools/efinity/efinity-run

PROJECTS  := heartbeat template
TESTS     := heartbeat template

TEMPLATE_SRCS := $(wildcard template/*.v template/*.vh template/*.sdc template/*.isf)

# HyperRAM sweep: one template image per PLL frequency and capture phase,
# in build/fpga/template-hr<MHz>-p<phase>/. Run tools/hyperram-sweep.py on
# the results.
SWEEP_MHZ    := 50 75 100 125 150
SWEEP_PHASES := 0 45 90 135 180 270
SWEEP_IMAGES := $(foreach m,$(SWEEP_MHZ),$(foreach p,$(SWEEP_PHASES),\
                  $(BUILD)/template-hr$(m)-p$(p)/outflow/template.hex.bin))

.PHONY: all test shell efx clean hyperram-sweep $(PROJECTS) $(addprefix test-,$(TESTS))

all: $(PROJECTS)

image = $(BUILD)/$(1)/outflow/$(1).hex.bin
$(foreach p,$(PROJECTS),$(eval $(p): $(call image,$(p))))

# Each image depends on its own project files.
$(BUILD)/heartbeat/outflow/heartbeat.hex.bin: $(wildcard heartbeat/*.v heartbeat/*.sdc heartbeat/*.isf heartbeat/*.xml heartbeat/build.sh)
$(BUILD)/template/outflow/template.hex.bin:   $(TEMPLATE_SRCS) template/template.xml template/build.sh

hyperram-sweep: $(SWEEP_IMAGES)

# Listed before the generic rule: make 3.81 takes the first matching pattern.
$(BUILD)/template-hr%/outflow/template.hex.bin: $(TEMPLATE_SRCS) template/template.xml template/build.sh
	HR_MHZ=$(firstword $(subst -p, ,$*)) HR_CAL_PHASE=$(lastword $(subst -p, ,$*)) ./template/build.sh
	touch $@

# Efinity rewrites the project .xml at the end of every run; touch the image
# afterwards so it stays newer than its inputs.
$(BUILD)/%.hex.bin:
	./$(firstword $(subst /, ,$*))/build.sh
	touch $@

test: $(addprefix test-,$(TESTS))

$(addprefix test-,$(TESTS)): test-%:
	./$*/test.sh

shell:
	$(EFX_RUN) bash

efx:
	@test -n "$(CMD)" || { echo 'usage: make efx CMD="<efinity command>"' >&2; exit 2; }
	$(EFX_RUN) $(CMD)

clean:
	rm -rf $(addprefix $(BUILD)/,$(PROJECTS)) $(BUILD)/template-hr*
