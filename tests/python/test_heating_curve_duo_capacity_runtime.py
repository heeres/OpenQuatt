"""Execute the production curve Duo scoring with a realistic power ladder."""

from pathlib import Path
import tempfile
import unittest

from tests.support.cpp import COMPILE_TIMEOUT_SECONDS, RUN_TIMEOUT_SECONDS, compiler_command
from tests.support.process import run_process


ROOT = Path(__file__).resolve().parents[2]


class HeatingCurveDuoCapacityRuntimeTest(unittest.TestCase):
    def test_saturated_recovery_can_prefer_duo(self) -> None:
        runtime = (ROOT / "openquatt/includes/control/oq_heating_curve_runtime.h").read_text()
        start = runtime.index("    float target_power_w =")
        end = runtime.index(";", runtime.index("    const bool single_sufficient =")) + 1
        harness = r'''
#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstdint>
#include <cstdlib>
#include "openquatt/includes/control/oq_heating_curve_logic.h"
#define id(x) x
struct Number { float state=3; } oq_dual_hp_enable_hold_min, oq_dual_hp_disable_hold_min;
uint32_t hp1_last_start_ms=0, hp2_last_start_ms=0;
struct Result { float target_w; bool saturated, duo_better, single_sufficient; int single_level, duo_total; };
float unit_w(int level) { return level > 0 ? 800.0f * level : 0.0f; }
Result evaluate(bool heat_phase, float demand_u, int previous_hp1, int previous_hp2, int hp1_fixed_level=0) {
  const bool demand_active=true, lead_is_hp1=true;
  const int single_owner=1, hp2_fixed_level=0, owner_max=10, hp1_pair_max=10, hp2_pair_max=10;
  const float owner_capacity_w=8000, duo_capacity_w=16000;
  const uint32_t now_ms=1000;
  const struct { int dual_startup_grace_s=0; } tuning;
  const auto candidate=[&](int hp1, int hp2, float target_w) {
    if (hp1_fixed_level > 0 && hp1 != hp1_fixed_level) return oq_curve::invalid_dispatch_candidate();
    const float power_w=unit_w(hp1) + unit_w(hp2);
    return oq_curve::DispatchCandidate{true, hp1, hp2, power_w, std::fabs(power_w - target_w),
                                       (hp1 > 0) + (hp2 > 0), std::abs(hp1 - hp2), 0};
  };
  // PRODUCTION_BLOCK
  (void)dual_on_hold_min; (void)dual_off_hold_min; (void)startup_grace; (void)duo_enable_min_u; (void)duo_disable_max_u;
  return {target_power_w, single_saturated, duo_better, single_sufficient, best_single.hp1_level,
          best_duo.hp1_level + best_duo.hp2_level};
}
int main() {
  // The owner can always reach a one-HP target, so only a Duo-scale target can show the shortfall.
  auto out=evaluate(true, 1.0f, 10, 0);
  assert(out.saturated && out.target_w == 16000.0f && out.duo_better && !out.single_sufficient);
  assert(out.single_level == 10 && out.duo_total == 20);
  out=evaluate(true, 0.9f, 9, 0);
  assert(out.saturated && out.duo_better);
  // A ramping owner stays on its own scale and does not call for the second HP.
  out=evaluate(true, 0.6f, 6, 0);
  assert(!out.saturated && out.target_w == 4800.0f && !out.duo_better && out.single_sufficient);
  assert(out.single_level == 6);
  // Running Duo must keep delivering more than one HP during recovery.
  out=evaluate(true, 0.7f, 5, 5);
  assert(!out.saturated && out.target_w == 11200.0f && out.duo_total == 14 && !out.single_sufficient);
  // Maintain keeps using the Duo scale.
  out=evaluate(false, 0.4f, 5, 0);
  assert(out.target_w == 6400.0f && out.single_level == 8);
  // A held owner keeps its own scale: the fixed level already exposes the shortfall.
  out=evaluate(true, 1.0f, 2, 0, 2);
  assert(out.saturated && out.single_level == 2 && out.target_w == 8000.0f && out.duo_better);
}
'''.replace("  // PRODUCTION_BLOCK", runtime[start:end])
        with tempfile.TemporaryDirectory(prefix="oq-curve-duo-capacity-") as directory:
            source = Path(directory) / "curve_duo_capacity.cpp"
            binary = Path(directory) / "curve_duo_capacity"
            source.write_text(harness)
            run_process(compiler_command("-I", str(ROOT), str(source), "-o", str(binary)),
                        check=True, cwd=ROOT, timeout=COMPILE_TIMEOUT_SECONDS)
            run_process([str(binary)], check=True, timeout=RUN_TIMEOUT_SECONDS)


if __name__ == "__main__":
    unittest.main()
